"""Fail-closed CLI startup and persistence tests for SharePoint discovery."""

from __future__ import annotations

import importlib
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

cli = importlib.import_module("onedrive_api.sharepoint_discover_cli")
models = importlib.import_module("onedrive_api.sharepoint_discovery")


class SharePointCliTests(unittest.TestCase):
    """Exercise the operator entrypoint without contacting Microsoft."""

    def setUp(self) -> None:
        """Create a temporary JSON backup configuration and data directory."""
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.conf = self.root / "backup.json"
        self.data = self.root / "data"
        self.data.mkdir()
        self.conf.write_text(json.dumps({
            "rclone_config": "/secrets/rclone.conf",
        }))

    def test_scaffold_and_unmounted_volume_are_refused(self) -> None:
        """Prevent unattended scans in scaffold or on root filesystem."""
        with patch.dict(os.environ, {"ONEDRIVE_SCAFFOLD_MODE": "1"}):
            with self.assertRaises(models.DiscoveryError) as ctx:
                cli.discover(self.conf, self.data)
        self.assertEqual(ctx.exception.code, "SCAFFOLD_ONLY")
        with patch.dict(os.environ, {"ONEDRIVE_SCAFFOLD_MODE": "0"}):
            with self.assertRaises(models.DiscoveryError) as ctx:
                cli.discover(self.conf, self.data)
        self.assertEqual(ctx.exception.code, "STORAGE_NOT_MOUNTED")

    def test_discovery_refuses_nonsecret_path(self) -> None:
        """Prevent loading credential files from arbitrary host locations."""
        self.conf.write_text(json.dumps({
            "rclone_config": "/tmp/untrusted.conf",
        }))
        with (
            patch.dict(os.environ, {"ONEDRIVE_SCAFFOLD_MODE": "0"}),
            patch.object(Path, "is_mount", return_value=True),
        ):
            with self.assertRaises(models.DiscoveryError) as ctx:
                cli.discover(self.conf, self.data)
        self.assertEqual(ctx.exception.code, "RCLONE_CONFIG_PATH_UNSAFE")

    def test_dry_run_does_not_create_files(self) -> None:
        """Validate that preview never mutates the inventory."""
        credentials = models.EntraCredentials(
            "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa",
            "bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb",
            "fake-secret",
        )
        report = {
            "complete": True, "checked_at": "2026-11-17T00:00:00Z",
            "sites": [], "libraries": [], "errors": [],
            "coverage": {"sites": 0, "libraries": 0},
        }
        with (
            patch.dict(os.environ, {"ONEDRIVE_SCAFFOLD_MODE": "0"}),
            patch.object(Path, "is_mount", return_value=True),
            patch.object(
                models.EntraCredentials, "from_rclone",
                return_value=credentials,
            ),
            patch.object(cli, "SharePointDiscovery") as scanner,
        ):
            scanner.return_value.scan.return_value = report
            result = cli.discover(self.conf, self.data, dry_run=True)
        self.assertTrue(result["complete"])
        self.assertFalse((self.data / "sharepoint").exists())

    def test_success_and_partial_scan_state(self) -> None:
        """Keep last good scan while recording a failed follow-up attempt."""
        credentials = models.EntraCredentials(
            "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa",
            "bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb",
            "fake-secret",
        )
        result = {
            "complete": True, "checked_at": "2026-11-17T00:00:00Z",
            "sites": [], "libraries": [], "errors": [],
            "coverage": {"sites": 0, "libraries": 0},
        }
        with (
            patch.dict(os.environ, {"ONEDRIVE_SCAFFOLD_MODE": "0"}),
            patch.object(Path, "is_mount", return_value=True),
            patch.object(
                models.EntraCredentials, "from_rclone",
                return_value=credentials,
            ),
            patch.object(cli, "SharePointDiscovery") as scanner,
        ):
            scanner.return_value.scan.return_value = result
            cli.discover(self.conf, self.data)
            scanner.return_value.scan.return_value = {
                **result,
                "complete": False,
                "errors": [{"source": "site", "code": "GRAPH_HTTP_403"}],
            }
            cli.discover(self.conf, self.data)
        state = models.SharePointInventory(self.data / "sharepoint")
        self.assertFalse(state.status()["ready"])
        self.assertTrue(json.loads(
            state.inventory_path.read_text()
        )["complete"])


if __name__ == "__main__":
    unittest.main()
