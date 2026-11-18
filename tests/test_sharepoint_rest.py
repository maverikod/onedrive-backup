"""Server surface contract: no REST layer, token gate inputs, download link, transfer confinement.

The file keeps its historical name; the SharePoint inventory contract itself is covered by
test_sharepoint_discovery.
"""

from __future__ import annotations

import base64
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
    """Temporary configuration, credentials file and one staged export."""

    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.cert = self.root / "fake-cert"
        self.cert.write_text("not-a-real-certificate")
        self.data = self.root / "data"
        self.exports = self.data / "exports"
        self.exports.mkdir(parents=True)
        self.credentials = self.root / "api-credentials"
        self.credentials.write_text("debug:not-a-real-password\n")
        self.config_path = self.root / "server.json"
        self.config_path.write_text(json.dumps(self.config()))
        env = {
            "ONEDRIVE_SCAFFOLD_MODE": "1",
            "ONEDRIVE_BACKUP_DATA": str(self.data),
            "ONEDRIVE_BACKUP_CONFIG": str(self.root / "backup.json"),
            server.CREDENTIALS_FILE_ENV: str(self.credentials),
        }
        patcher = patch.dict(os.environ, env)
        patcher.start()
        self.addCleanup(patcher.stop)

    def config(self) -> dict:
        return {
            "server": {
                "protocol": "mtls",
                "ssl": {"cert": str(self.cert), "key": str(self.cert), "ca": str(self.cert)},
            },
            "auth": {"use_token": True, "tokens": {}},
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


class TokenGateTests(ServerFixture):
    """The interim token T = base64(login:password) and the fail-closed gate."""

    def test_token_is_base64_of_login_and_password(self) -> None:
        expected = base64.b64encode(b"debug:not-a-real-password").decode("ascii")
        self.assertEqual(server.api_token(), expected)

    def test_absent_credentials_leave_no_token_but_an_internal_one(self) -> None:
        self.credentials.unlink()
        self.assertIsNone(server.api_token())
        config = self.config()
        internal = server.secure_auth(config)
        self.assertTrue(internal)
        self.assertEqual(list(config["auth"]["tokens"]), [internal])

    def test_malformed_credentials_leave_no_token_and_do_not_stop_startup(self) -> None:
        for text in ("", "nologin\n", ":nopassword\n", "nopassword:\n"):
            with self.subTest(text=text):
                self.credentials.write_text(text)
                self.assertIsNone(server.api_token())
                config = self.config()
                internal = server.secure_auth(config)
                self.assertEqual(list(config["auth"]["tokens"]), [internal])

    def test_secure_auth_installs_the_credentials_token_and_the_internal_one(self) -> None:
        config = self.config()
        config["auth"]["tokens"] = {"committed-token": ["other"]}
        internal = server.secure_auth(config)
        self.assertEqual(set(config["auth"]["tokens"]), {internal, server.api_token()})
        self.assertNotEqual(internal, server.api_token())

    def test_internal_token_is_random_per_start(self) -> None:
        self.assertNotEqual(server.secure_auth(self.config()), server.secure_auth(self.config()))

    def test_token_gate_must_be_on(self) -> None:
        for auth in ({}, {"use_token": False}, {"use_token": "yes"}):
            with self.subTest(auth=auth):
                with self.assertRaises(ValueError):
                    server.secure_auth({"auth": auth})
        with self.assertRaises(ValueError):
            server.secure_auth({})

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
class RouteFilterTests(ServerFixture):
    """make_app keeps only the intended routes and binds the download resolver."""

    def test_only_allowed_routes_remain(self) -> None:
        fake = FastAPI()
        for path in ("/api/v1/health", "/api/v1/exports/{export_id}", "/ws", "/api/transfer/uploads",
                     "/downloads/{file_id}/{filename}", "/api/transfer/downloads", "/health"):
            fake.add_api_route(path, lambda: {}, methods=["GET"])
        with (
            patch("mcp_proxy_adapter.api.app.create_app", return_value=fake),
            patch("onedrive_api.ui.install_ui"),
        ):
            app = server.make_app(self.config_path)
        paths = {getattr(route, "path", None) for route in app.router.routes}
        self.assertEqual(paths - {None}, paths & server.ALLOWED_ROUTES)
        for gone in ("/api/v1/health", "/api/v1/exports/{export_id}", "/ws", "/api/transfer/uploads"):
            self.assertNotIn(gone, paths)
        for kept in ("/downloads/{file_id}/{filename}", "/api/transfer/downloads", "/health"):
            self.assertIn(kept, paths)
        self.assertIs(app.state.public_download_resolver, server._resolve_download)

    def test_make_app_starts_without_a_valid_secret_and_arms_the_proxy_middleware(self) -> None:
        for state in ("present", "absent", "empty", "malformed"):
            with self.subTest(state=state):
                if state == "absent":
                    self.credentials.unlink(missing_ok=True)
                elif state == "present":
                    self.credentials.write_text("debug:not-a-real-password\n")
                else:
                    self.credentials.write_text("" if state == "empty" else "nopassword\n")
                fake = FastAPI()
                with (
                    patch("mcp_proxy_adapter.api.app.create_app", return_value=fake) as created,
                    patch("onedrive_api.ui.install_ui"),
                ):
                    server.make_app(self.config_path)
                tokens = created.call_args.kwargs["app_config"]["auth"]["tokens"]
                armed = fake.user_middleware[0]
                self.assertIs(armed.cls, server.ProxyTrustMiddleware)
                options = getattr(armed, "kwargs", None) or armed.options
                self.assertIn(options["token"], tokens)
                self.assertEqual(len(tokens), 2 if state == "present" else 1)

    def test_make_app_refuses_an_open_token_gate(self) -> None:
        config = self.config()
        config["auth"]["use_token"] = False
        self.config_path.write_text(json.dumps(config))
        with self.assertRaises(ValueError):
            server.make_app(self.config_path)


class ProxyTrustTests(unittest.TestCase):
    """The MCP Proxy peer carries the internal token; every other peer does not, whatever its headers say."""

    def run_request(self, peer, hosts=("127.0.0.1",), token="INTERNAL", incoming=()):
        import asyncio
        seen = {}

        async def app(scope, receive, send):
            seen["headers"] = dict(scope["headers"])

        middleware = server.ProxyTrustMiddleware(app, list(hosts), token)
        scope = {"type": "http", "client": (peer, 5000), "headers": list(incoming)}
        asyncio.run(middleware(scope, None, None))
        return seen["headers"]

    def test_proxy_peer_gets_the_internal_token(self) -> None:
        self.assertEqual(self.run_request("127.0.0.1")[b"x-api-key"], b"INTERNAL")

    def test_proxy_peer_cannot_inject_another_token(self) -> None:
        headers = self.run_request("127.0.0.1", incoming=[(b"x-api-key", b"other")])
        self.assertEqual(headers[b"x-api-key"], b"INTERNAL")

    def test_other_peer_gets_nothing(self) -> None:
        self.assertNotIn(b"x-api-key", self.run_request("10.9.9.9"))

    def test_direct_peer_keeps_its_own_token_header(self) -> None:
        headers = self.run_request("10.9.9.9", incoming=[(b"x-api-key", b"T")])
        self.assertEqual(headers[b"x-api-key"], b"T")

    def test_spoofed_proxy_headers_grant_nothing(self) -> None:
        spoof = [(b"x-forwarded-for", b"127.0.0.1"), (b"forwarded", b"for=127.0.0.1;host=127.0.0.1"),
                 (b"x-real-ip", b"127.0.0.1"), (b"host", b"127.0.0.1")]
        self.assertNotIn(b"x-api-key", self.run_request("10.9.9.9", incoming=spoof))

    def test_closed_without_hosts_or_token(self) -> None:
        self.assertNotIn(b"x-api-key", self.run_request("127.0.0.1", hosts=()))
        self.assertNotIn(b"x-api-key", self.run_request("127.0.0.1", token=None))

    def test_unresolvable_host_trusts_nothing(self) -> None:
        self.assertNotIn(b"x-api-key", self.run_request("127.0.0.1", hosts=("no-such-host.invalid",)))


if __name__ == "__main__":
    unittest.main()
