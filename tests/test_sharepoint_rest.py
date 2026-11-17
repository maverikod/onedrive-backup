"""REST contract checks for SharePoint inventory-backed endpoints."""

from __future__ import annotations

import importlib
import json
import os
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


@unittest.skipUnless(FastAPI is not None, "FastAPI is in service image")
class SharePointRestTests(unittest.TestCase):
    """Use an in-memory FastAPI adapter with the real REST routes."""

    def setUp(self) -> None:
        """Create temporary test config and a private discovery inventory."""
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.cert = self.root / "fake-cert"
        self.cert.write_text("not-a-real-certificate")
        self.config = self.root / "server.json"
        self.config.write_text(json.dumps({
            "server": {
                "protocol": "mtls",
                "ssl": {
                    "cert": str(self.cert), "key": str(self.cert),
                    "ca": str(self.cert),
                },
            },
        }))
        self.data = self.root / "data"
        self.data.mkdir()
        self.store = models.SharePointInventory(
            self.data / "sharepoint"
        )

    def client(self, scaffold: bool):
        """Construct the real routes without binding any TCP listener."""
        env = {
            "ONEDRIVE_SCAFFOLD_MODE": "1" if scaffold else "0",
            "ONEDRIVE_BACKUP_DATA": str(self.data),
        }
        self.env_patch = patch.dict(os.environ, env)
        self.env_patch.start()
        self.addCleanup(self.env_patch.stop)
        with (
            patch(
                "mcp_proxy_adapter.api.app.create_app",
                return_value=FastAPI(),
            ),
            patch("onedrive_api.ui.install_ui"),
            patch(
                "onedrive_api.admin_password.load_record",
                return_value={},
            ),
        ):
            app = server.make_app(self.config)
        return TestClient(app)

    def test_scaffold_exposes_no_inventory(self) -> None:
        """Leave status available but refuse browse without backup data."""
        client = self.client(scaffold=True)
        resp = client.get("/api/v1/discovery/status")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()["state"], "SCAFFOLD_ONLY")
        self.assertEqual(
            client.get("/api/v1/sites").status_code, 503
        )
        self.assertEqual(
            client.get("/api/v1/sites/host,1,2/libraries").status_code,
            503,
        )

    def test_site_library_parity_and_errors(self) -> None:
        """Verify REST pages match the shared inventory store."""
        site_id = "host.sharepoint.com,1,2"
        report = {
            "complete": True,
            "checked_at": "2026-11-17T00:00:00Z",
            "sites": [{
                "site_id": site_id, "display_name": "Research",
                "web_url": "https://host.sharepoint.com/sites/Research",
                "library_count": 1, "source_status": "ok",
            }],
            "libraries": [{
                "site_id": site_id, "drive_id": "b!abc",
                "display_name": "Documents",
                "web_url": "https://host.sharepoint.com/sites/docs",
                "status": "ok",
            }],
            "errors": [],
            "coverage": {"sites": 1, "libraries": 1},
        }
        self.store.record(report)
        client = self.client(scaffold=False)
        self.assertTrue(
            client.get("/api/v1/discovery/status").json()["ready"]
        )
        sites = client.get(
            "/api/v1/sites", params={"limit": 1, "offset": 0}
        )
        self.assertEqual(sites.status_code, 200)
        self.assertEqual(
            sites.json(), self.store.sites(limit=1, offset=0)
        )
        libraries = client.get(
            "/api/v1/sites/" + site_id + "/libraries"
        )
        self.assertEqual(libraries.status_code, 200)
        self.assertEqual(
            libraries.json(), self.store.libraries(site_id)
        )
        self.assertEqual(
            client.get("/api/v1/sites", params={"limit": 0}).status_code,
            400,
        )
        self.assertEqual(
            client.get("/api/v1/sites/missing/libraries").status_code,
            404,
        )

    def test_failed_refresh_refuses_stale_browsing(self) -> None:
        """Do not reuse old inventory after a partial Graph scan."""
        self.store.record({
            "complete": True, "checked_at": "old",
            "sites": [], "libraries": [],
            "errors": [], "coverage": {"sites": 0, "libraries": 0},
        })
        self.store.record({
            "complete": False, "checked_at": "new",
            "sites": [], "libraries": [],
            "errors": [{"source": "sites", "code": "GRAPH_HTTP_403"}],
            "coverage": {"sites": 0, "libraries": 0},
        })
        client = self.client(scaffold=False)
        self.assertFalse(
            client.get("/api/v1/discovery/status").json()["ready"]
        )
        self.assertEqual(client.get("/api/v1/sites").status_code, 503)


if __name__ == "__main__":
    unittest.main()
