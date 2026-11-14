"""API catalogue security and interface tests (no live secrets)."""
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from onedrive_api.catalog import Catalog, CatalogError


class CatalogValidationTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.catalog = Catalog(self.root / "backup.json", self.root)

    def test_snapshot_ids_restrict_shell_and_traversal(self):
        for value in ("../../etc/shadow", "", "-flag", "ab;echo", "a" * 7):
            with self.subTest(value=value):
                with self.assertRaises(CatalogError):
                    self.catalog._check_snapshot(value)
        self.assertEqual(self.catalog._check_snapshot("a1b2c3d4"), "a1b2c3d4")

    def test_export_ids_are_opaque(self):
        with self.assertRaises(CatalogError):
            self.catalog.get_export("../../etc/passwd")
        with self.assertRaises(CatalogError):
            self.catalog.get_export("a" * 32)

    def test_paths_cannot_escape_mirror(self):
        for value in ("../file", "/etc/passwd", "folder/../../secret",
                      "folder//file", "folder/./file", "folder\\file"):
            with self.subTest(value=value):
                with self.assertRaises(CatalogError):
                    self.catalog._check_path(value)
        self.assertEqual(self.catalog._check_path("docs/sub/file.txt"), "docs/sub/file.txt")

    def test_missing_repository_refuses_listing(self):
        with self.assertRaises(CatalogError) as err:
            self.catalog.snapshots()
        self.assertEqual(err.exception.status, 503)

    def test_failed_export_staging_cleaned(self):
        fake = {
            "path": "docs/a.txt",
            "type": "file",
            "size": 9,
            "restic_path": "/data/mirror/docs/a.txt",
        }
        with patch.object(self.catalog, "_all_nodes", return_value=[fake]), \
             patch.object(self.catalog, "_dump_file", side_effect=CatalogError("failed", 503)):
            with self.assertRaises(CatalogError):
                self.catalog.prepare("abcdefab", "docs/a.txt")
        self.assertFalse(list(self.catalog.exports.glob("*.bin")))
        self.assertFalse(list(self.catalog.exports.glob("*.json")))

    def test_export_retrieval_restricts_path(self):
        self.catalog.exports.mkdir(exist_ok=True)
        eid = "a" * 32
        (self.catalog.exports / (eid + ".bin")).write_bytes(b"ok")
        (self.catalog.exports / (eid + ".json")).write_text(json.dumps({
            "export_id": eid,
            "path": "docs/a",
            "expires_at": "2100-01-01T00:00:00+00:00",
            "size_bytes": 2,
        }))
        info, filename = self.catalog.get_export(eid)
        self.assertEqual(info["size_bytes"], 2)
        self.assertEqual(filename.read_bytes(), b"ok")


if __name__ == "__main__":
    unittest.main()
