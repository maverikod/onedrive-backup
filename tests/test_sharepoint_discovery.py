"""Security and pagination regressions for SharePoint Graph discovery."""

from __future__ import annotations

import importlib
import json
from pathlib import Path
import tempfile
import unittest

discovery = importlib.import_module("onedrive_api.sharepoint_discovery")


class FakeGraphTransport:
    """Deterministic Graph/OAuth transport with recorded requests."""

    def __init__(self, replies: dict) -> None:
        """Keep queues of Graph JSON response triples."""
        self.replies = replies
        self.calls: list[tuple[str, str]] = []

    def __call__(
        self, method: str, url: str, headers: dict, body: bytes | None
    ) -> tuple:
        """Respond with a prepared HTTP status and JSON body."""
        self.calls.append((method, url))
        if method == "POST":
            return 200, {"access_token": "test-token", "expires_in": 3600}, {}
        if url not in self.replies or not self.replies[url]:
            raise AssertionError("Unexpected Graph URL")
        return self.replies[url].pop(0)


class DiscoveryContractTests(unittest.TestCase):
    """Validate complete and incomplete Graph inventory behaviour."""

    def setUp(self) -> None:
        """Create nonsecret test credentials and a temporary data volume."""
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.directory = Path(self.tmp.name) / "sharepoint"
        self.creds = discovery.EntraCredentials(
            "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa",
            "bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb",
            "fake-secret",
        )
        self.sites_url = discovery.GRAPH_ROOT + "/sites/getAllSites"

    def client(self, replies: dict, sleeps: list | None = None):
        """Construct an injectable Graph client with no network access."""
        transport = FakeGraphTransport(replies)
        delays = sleeps if sleeps is not None else []
        client = discovery.GraphClient(
            self.creds, request=transport, sleep=delays.append
        )
        return client, transport

    @staticmethod
    def _site(site_id: str, title: str) -> dict:
        """Create one Graph site collection record."""
        return {
            "id": site_id, "displayName": title,
            "webUrl": "https://example.sharepoint.com/sites/" + title,
        }

    @staticmethod
    def _drive(drive_id: str, title: str) -> dict:
        """Create a document library record."""
        return {
            "id": drive_id, "driveType": "documentLibrary",
            "name": title, "webUrl": "https://example.sharepoint.com/" + title,
        }

    def test_all_pages_and_same_names_across_sites(self) -> None:
        """Collect all sites and all libraries without user OneDrive."""
        first = self._site("example.sharepoint.com,1,2", "One")
        second = self._site("example.sharepoint.com,2,3", "Two")
        third = self._site("example-my.sharepoint.com,3,4", "personal")
        third["webUrl"] = (
            "https://example-my.sharepoint.com/personal/account"
        )
        pages = self.sites_url + "?$skiptoken=next"
        drive_1 = (
            discovery.GRAPH_ROOT + "/sites/"
            "example.sharepoint.com,1,2/drives"
        )
        drive_2 = (
            discovery.GRAPH_ROOT + "/sites/"
            "example.sharepoint.com,2,3/drives"
        )
        next_drive = drive_1 + "?$skiptoken=more"
        replies: dict = {
            self.sites_url: [(
                200, {"value": [first, third], "@odata.nextLink": pages}, {}
            )],
            pages: [(200, {"value": [first, second]}, {})],
            drive_1: [(
                200, {
                    "value": [self._drive("drive-A", "Documents")],
                    "@odata.nextLink": next_drive,
                }, {}
            )],
            next_drive: [(200, {
                "value": [self._drive("drive-B", "Documents")]
            }, {})],
            drive_2: [(200, {
                "value": [self._drive("drive-C", "Documents")]
            }, {})],
        }
        client, transport = self.client(replies)
        report = discovery.SharePointDiscovery(client).scan()
        self.assertTrue(report["complete"])
        self.assertEqual(len(report["sites"]), 2)
        self.assertEqual(len(report["libraries"]), 3)
        self.assertEqual(report["coverage"]["excluded_personal_sites"], 1)
        self.assertEqual(report["sites"][0]["library_count"], 2)
        self.assertEqual(
            len([c for c in transport.calls if c[0] == "POST"]), 1
        )
        self.assertTrue(
            all(method in ("POST", "GET") for method, _ in transport.calls)
        )

        store = discovery.SharePointInventory(self.directory)
        store.record(report)
        self.assertTrue(store.status()["ready"])
        self.assertEqual(store.sites(limit=1)["total"], 2)
        self.assertEqual(store.libraries(first["id"])["total"], 2)
        self.assertEqual(
            store.libraries(second["id"])["items"][0]["drive_id"],
            "drive-C",
        )
        self.assertEqual(
            self.directory.joinpath("inventory.json").stat().st_mode
            & 0o077, 0
        )

    def test_failed_site_never_replaces_complete_inventory(self) -> None:
        """Keep the last verified snapshot but mark readiness false."""
        store = discovery.SharePointInventory(self.directory)
        original = {
            "complete": True, "checked_at": "old",
            "sites": [{"site_id": "existing", "display_name": "Old"}],
            "libraries": [], "errors": [],
            "coverage": {"sites": 1, "libraries": 0},
        }
        store.record(original)
        site_1 = self._site("host,1,2", "One")
        site_2 = self._site("host,3,4", "Two")
        replies: dict = {
            self.sites_url: [(
                200, {"value": [site_1, site_2]}, {}
            )],
            discovery.GRAPH_ROOT + "/sites/host,1,2/drives": [(
                200, {"value": [self._drive("lib", "Docs")]}, {}
            )],
            discovery.GRAPH_ROOT + "/sites/host,3,4/drives": [(
                403, {}, {}
            )],
        }
        client, _ = self.client(replies)
        result = discovery.SharePointDiscovery(client).scan()
        self.assertFalse(result["complete"])
        self.assertEqual(result["coverage"]["libraries"], 1)
        self.assertEqual(result["errors"][0]["code"], "GRAPH_HTTP_403")
        store.record(result)
        self.assertFalse(store.status()["ready"])
        with self.assertRaises(discovery.DiscoveryError):
            store.sites()
        preserved = json.loads(
            (self.directory / "inventory.json").read_text()
        )
        self.assertEqual(preserved["checked_at"], "old")

    def test_throttling_and_unsafe_next_link(self) -> None:
        """Retry 429 with Retry-After and reject hostile continuation URLs."""
        sleeps: list[float] = []
        replies: dict = {
            self.sites_url: [
                (429, {}, {"Retry-After": "2"}),
                (200, {"value": []}, {}),
            ]
        }
        client, transport = self.client(replies, sleeps=sleeps)
        result = discovery.SharePointDiscovery(client).scan()
        self.assertTrue(result["complete"])
        self.assertEqual(result["coverage"]["sites"], 0)
        self.assertEqual(sleeps, [2.0])
        self.assertEqual(len(transport.calls), 3)

        hostile: dict = {
            self.sites_url: [(
                200, {
                    "value": [],
                    "@odata.nextLink": "https://attacker.example/token",
                }, {}
            )],
        }
        client, _ = self.client(hostile)
        self.assertEqual(
            discovery.SharePointDiscovery(client).scan()["errors"][0]["code"],
            "GRAPH_NEXTLINK_UNSAFE",
        )

    def test_pagination_cycle_and_invalid_identifiers(self) -> None:
        """Refuse pagination loops and malformed site identifiers."""
        cyclic: dict = {
            self.sites_url: [(
                200, {
                    "value": [],
                    "@odata.nextLink": self.sites_url,
                }, {}
            )]
        }
        client, _ = self.client(cyclic)
        failed = discovery.SharePointDiscovery(client).scan()
        self.assertFalse(failed["complete"])
        self.assertEqual(
            failed["errors"][0]["code"], "GRAPH_PAGINATION_CYCLE"
        )
        malformed: dict = {
            self.sites_url: [(200, {
                "value": [self._site("../bad", "Bad")]
            }, {})],
        }
        client, _ = self.client(malformed)
        self.assertEqual(
            discovery.SharePointDiscovery(client).scan()["errors"][0]["code"],
            "SITE_ID_INVALID",
        )

    def test_credential_file_permissions(self) -> None:
        """Read protected app-only credentials, never the Secret ID."""
        conf = Path(self.tmp.name) / "rclone.conf"
        conf.write_text(
            "[onedrive]\n"
            "type = onedrive\n"
            "tenant = aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa\n"
            "client_id = bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb\n"
            "client_secret = password-value-not-secret-id\n"
            "client_credentials = true\n"
        )
        conf.chmod(0o600)
        c = discovery.EntraCredentials.from_rclone(conf)
        self.assertEqual(c.secret, "password-value-not-secret-id")
        conf.chmod(0o644)
        with self.assertRaises(discovery.DiscoveryError) as exc:
            discovery.EntraCredentials.from_rclone(conf)
        self.assertEqual(exc.exception.code, "CREDENTIALS_PERMISSIONS_UNSAFE")

    def test_untrusted_paging_and_paths(self) -> None:
        """Reject unknown sites, bad pagination and symlink inventory."""
        store = discovery.SharePointInventory(self.directory)
        report = {
            "complete": True,
            "checked_at": "now",
            "sites": [],
            "libraries": [],
            "errors": [],
            "coverage": {"sites": 0, "libraries": 0},
        }
        store.record(report)
        for args in (
            {"limit": 0}, {"limit": True}, {"offset": -1},
            {"offset": True},
        ):
            with self.subTest(args=args):
                with self.assertRaises(discovery.DiscoveryError):
                    store.sites(**args)
        with self.assertRaises(discovery.DiscoveryError) as error:
            store.libraries("../unsafe")
        self.assertEqual(error.exception.status, 400)
        with self.assertRaises(discovery.DiscoveryError):
            store.libraries("missing")
        store.inventory_path.unlink()
        store.inventory_path.symlink_to(
            Path(self.tmp.name) / "missing-secret"
        )
        with self.assertRaises(discovery.DiscoveryError):
            store.status()


if __name__ == "__main__":
    unittest.main()
