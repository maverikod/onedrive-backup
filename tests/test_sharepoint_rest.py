"""Server surface contract: no REST layer, adapter-only transport, download link, transfer confinement.

The file keeps its historical name; the SharePoint inventory contract itself is covered by
test_sharepoint_discovery.
"""

from __future__ import annotations

import hashlib
import importlib
import json
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

try:
    FastAPI = importlib.import_module("fastapi").FastAPI
    TestClient = importlib.import_module("fastapi.testclient").TestClient
    importlib.import_module("mcp_proxy_adapter.api.app")
except ImportError:
    FastAPI = None
    TestClient = None

server = importlib.import_module("onedrive_api.server")
models = importlib.import_module("onedrive_api.sharepoint_discovery")
catalog = importlib.import_module("onedrive_api.catalog")

EXPORT_ID = "ab" * 16


class ServerFixture(unittest.TestCase):
    """Temporary configuration and one staged export."""

    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.cert = self.root / "fake-cert"
        self.cert.write_text("not-a-real-certificate")
        (self.root / "web").mkdir()
        self.data = self.root / "data"
        self.exports = self.data / "exports"
        self.exports.mkdir(parents=True)
        self.config_path = self.root / "server.json"
        self.config_path.write_text(json.dumps(self.config()))
        env = {
            "ONEDRIVE_SCAFFOLD_MODE": "1",
            "ONEDRIVE_BACKUP_DATA": str(self.data),
            "ONEDRIVE_BACKUP_CONFIG": str(self.root / "backup.json"),
            server.WEB_DIR_ENV: str(self.root / "web"),
        }
        patcher = patch.dict(os.environ, env)
        patcher.start()
        self.addCleanup(patcher.stop)

    def config(self) -> dict:
        return {
            "server": {
                "protocol": "https",
                "ssl": {"cert": str(self.cert), "key": str(self.cert), "ca": str(self.cert)},
            },
            "auth": {"use_token": False, "tokens": {}},
            "transfer": {"allowed_directories": [str(self.exports)]},
        }

    def stage(self, body: bytes = b"hello export") -> None:
        (self.exports / (EXPORT_ID + ".bin")).write_bytes(body)
        expires = datetime.now(timezone.utc) + timedelta(hours=1)
        (self.exports / (EXPORT_ID + ".json")).write_text(json.dumps({
            "export_id": EXPORT_ID, "snapshot_id": "abcdef12", "path": "a/b.txt",
            "filename": "b.txt", "size_bytes": len(body),
            "sha256": hashlib.sha256(body).hexdigest(),
            "created_at": "2026-11-18T00:00:00+00:00", "expires_at": expires.isoformat(),
        }))


class TransferConfinementTests(ServerFixture):
    """The transfer section must stay confined to the exports directory."""

    def test_transfer_must_be_confined(self) -> None:
        for transfer in (None, {}, {"allowed_directories": []}, {"allowed_directories": [""]}):
            with self.subTest(transfer=transfer):
                with self.assertRaises(ValueError):
                    server.validate_transfer({"transfer": transfer})
        self.assertEqual(
            server.validate_transfer(self.config())["allowed_directories"], [str(self.exports)]
        )


class DownloadLinkTests(ServerFixture):
    """The temporary link /downloads/<export_id>/<filename> and the url field."""

    def test_resolver_serves_only_the_staged_name(self) -> None:
        self.stage()
        record, path = server._resolve_download(EXPORT_ID, "b.txt")
        self.assertEqual(record["name"], "b.txt")
        self.assertEqual(path.read_bytes(), b"hello export")
        with self.assertRaises(FileNotFoundError):
            server._resolve_download(EXPORT_ID, "other.txt")
        with self.assertRaises(FileNotFoundError):
            server._resolve_download("0" * 32, "b.txt")
        for bad in ("not-an-id", "AB" * 16, "../../etc/passwd", ""):
            with self.subTest(file_id=bad):
                with self.assertRaises(ValueError):
                    server._resolve_download(bad, "b.txt")

    def test_status_carries_the_url_and_stores_none(self) -> None:
        self.stage()
        meta = catalog.Catalog(self.root / "backup.json", self.data).export_status(EXPORT_ID)
        self.assertEqual(meta["url"], "/downloads/%s/b.txt" % EXPORT_ID)
        stored = json.loads((self.exports / (EXPORT_ID + ".json")).read_text())
        self.assertNotIn("url", stored)


class SharePointValidationTests(unittest.TestCase):
    """Format validation does not depend on readiness (R5)."""

    def test_site_id_format(self) -> None:
        for value in ("a b", "q" * 301, "", 7, None):
            with self.subTest(value=value):
                with self.assertRaises(models.DiscoveryError) as err:
                    models.SharePointInventory.check_site_id(value)
                self.assertEqual((err.exception.code, err.exception.status), ("INVALID_SITE_ID", 400))
        models.SharePointInventory.check_site_id("host.sharepoint.com,1,2")

    def test_query_format(self) -> None:
        for value in ("q" * 129, 7, None):
            with self.subTest(value=value):
                with self.assertRaises(models.DiscoveryError) as err:
                    models.SharePointInventory.check_query(value)
                self.assertEqual((err.exception.code, err.exception.status), ("INVALID_QUERY", 400))
        models.SharePointInventory.check_query("q" * 128)
        models.SharePointInventory.check_query("")


@unittest.skipUnless(FastAPI is not None, "FastAPI is in service image")
class AdapterOnlyTests(ServerFixture):
    """make_app adds no filter, no middleware and no authentication: only the resolver and the one static mount."""

    def make(self):
        fake = FastAPI()
        for path in ("/api/jsonrpc", "/ws", "/api/transfer/uploads", "/downloads/{file_id}/{filename}", "/health"):
            fake.add_api_route(path, lambda: {}, methods=["GET"])
        before = list(fake.router.routes)
        with patch("mcp_proxy_adapter.api.app.create_app", return_value=fake) as created:
            app = server.make_app(self.config_path)
        return app, before, created

    def test_every_adapter_route_stays_and_the_mount_is_last(self) -> None:
        app, before, _ = self.make()
        routes = app.router.routes
        self.assertEqual(routes[:len(before)], before)
        self.assertEqual(len(routes), len(before) + 1)
        self.assertEqual(getattr(routes[-1], "path", None), "")
        self.assertIs(app.state.public_download_resolver, server._resolve_download)

    def test_no_middleware_and_the_open_gate_is_not_touched(self) -> None:
        app, _, created = self.make()
        self.assertEqual(app.user_middleware, [])
        self.assertEqual(created.call_args.kwargs["app_config"]["auth"], {"use_token": False, "tokens": {}})

    def test_the_mount_serves_get_only_and_answers_404_for_an_absent_file(self) -> None:
        app, _, _ = self.make()
        client = TestClient(app)
        self.assertEqual(client.get("/ui").status_code, 404)
        self.assertEqual(client.get("/index.html").status_code, 404)


if __name__ == "__main__":
    unittest.main()
