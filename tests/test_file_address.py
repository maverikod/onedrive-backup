"""Unit tests of the file addresses and the chunk reader of the BYTES group (matrix 10.22.4)."""

from __future__ import annotations

import base64
import hashlib
import importlib
from pathlib import Path
import tempfile
import unittest
from unittest import mock

catalog_bytes = importlib.import_module("onedrive_api.catalog_bytes")
file_address = importlib.import_module("onedrive_api.file_address")
Catalog = importlib.import_module("onedrive_api.catalog").Catalog
CatalogError = importlib.import_module("onedrive_api.catalog").CatalogError
FileIndex = importlib.import_module("onedrive_api.file_index").FileIndex
digest = importlib.import_module("onedrive_api.folder_tree").digest
DiscoveryError = importlib.import_module("onedrive_api.sharepoint_base").DiscoveryError

SNAPSHOT = "ab" * 32
SITE, DRIVE = "site-1", "drive-1"


class AddressTests(unittest.TestCase):
    """Address forms, file ids and their resolution through the index."""

    def test_file_id_shape_and_determinism(self) -> None:
        """The id keeps the snapshot prefix and hashes the snapshot id and the path.

        Returns:
            Nothing; the assertions fail the test.
        """
        one = file_address.make_file_id(SNAPSHOT, "sharepoint/a/b/x.txt")
        self.assertRegex(one, r"^[0-9a-f]{8}[.][0-9a-f]{24}$")
        self.assertEqual(one, file_address.make_file_id(SNAPSHOT, "sharepoint/a/b/x.txt"))
        self.assertNotEqual(one, file_address.make_file_id(SNAPSHOT, "sharepoint/a/b/y.txt"))
        want = hashlib.sha256((SNAPSHOT + "\nsharepoint/a/b/x.txt").encode()).hexdigest()[:24]
        self.assertEqual(one, SNAPSHOT[:8] + "." + want)

    def test_forms(self) -> None:
        """Each address form is recognised and a mixed set is refused before any value check.

        Returns:
            Nothing; the assertions fail the test.
        """
        names = {"site_id": SITE, "drive_id": DRIVE, "dir": "", "name": "x.txt"}
        self.assertEqual(file_address.check_address({"file_id": "abababab." + "0" * 24}), "A")
        self.assertEqual(file_address.check_address({"snapshot_id": SNAPSHOT, "file_path": "x"}), "B")
        self.assertEqual(file_address.check_address({"snapshot_id": SNAPSHOT, **names, "copy_index": 1}), "C")
        self.assertEqual(file_address.check_address({"snapshot_id": SNAPSHOT}), "archive")
        for params, code in (
            ({"file_id": "abababab." + "0" * 24, "snapshot_id": SNAPSHOT}, "INVALID_FILE_ADDRESS"),
            ({"snapshot_id": SNAPSHOT, "file_path": "x", "site_id": SITE}, "INVALID_FILE_ADDRESS"),
            ({"snapshot_id": SNAPSHOT, "site_id": SITE, "drive_id": DRIVE, "dir": ""}, "INVALID_FILE_ADDRESS"),
            ({"file_id": "abc"}, "INVALID_FILE_ID"),
            ({"snapshot_id": SNAPSHOT, **names, "name": "../x"}, "INVALID_FILE_NAME"),
        ):
            with self.subTest(params=params):
                with self.assertRaises(DiscoveryError) as raised:
                    file_address.check_address(params)
                self.assertEqual(raised.exception.code, code)
                self.assertEqual(raised.exception.status, 400)
                self.assertIn("hint", raised.exception.details or {})

    def test_resolution_by_file_id_and_by_names(self) -> None:
        """Form A and form C find the same file in the index; an unknown id is a 404 with a hint.

        Returns:
            Nothing; the assertions fail the test.
        """
        with tempfile.TemporaryDirectory() as data:
            index = FileIndex(data)
            site, drive = digest(SITE), digest(DRIVE)
            rows = [("docs", "x.txt", "x.txt", "x.txt", 12, "t", 0), ("docs", "x.txt", "x.txt", "x.txt.1", 13, "t", 1)]
            index.add_snapshot(SNAPSHOT, "2026-11-24T10:00:00.000000Z", site, drive, rows)
            path = "sharepoint/%s/%s/docs/x.txt" % (site, drive)
            fid = file_address.make_file_id(SNAPSHOT, path)
            self.assertEqual(file_address.resolve_file_id(index, fid), (SNAPSHOT, path, 12))
            names = {"snapshot_id": SNAPSHOT[:8], "site_id": SITE, "drive_id": DRIVE, "dir": "docs", "name": "x.txt"}
            self.assertEqual(file_address.resolve_names(index, names), (SNAPSHOT, path, 12))
            self.assertEqual(file_address.resolve_names(index, {**names, "copy_index": 1})[2], 13)
            with self.assertRaises(CatalogError) as raised:
                file_address.resolve_file_id(index, SNAPSHOT[:8] + "." + "0" * 24)
            self.assertEqual(raised.exception.status, 404)
            self.assertIn("backup_search_files", (raised.exception.details or {})["hint"])
            with self.assertRaises(CatalogError) as missing:
                file_address.resolve_names(index, {**names, "name": "none.txt"})
            self.assertEqual((missing.exception.details or {})["checked"]["name"], "none.txt")


class ChunkTests(unittest.TestCase):
    """Slices of a staged export reassemble to its payload without touching it."""

    def test_slices_reassemble_and_offsets_are_checked(self) -> None:
        """Read an export slice by slice, then the end, a bad offset and a too large export.

        Returns:
            Nothing; the assertions fail the test.
        """
        payload = bytes(range(256)) * 20
        with tempfile.TemporaryDirectory() as data:
            path = Path(data) / "export.bin"
            path.write_bytes(payload)
            meta = {"sha256": hashlib.sha256(payload).hexdigest()}
            cat = mock.Mock(spec=Catalog)
            cat.get_export.return_value = (meta, path)
            parts, offset = [], 0
            while True:
                part = catalog_bytes.read_chunk(cat, "0" * 32, offset, 1000)
                parts.append(base64.b64decode(part["data_b64"]))
                self.assertEqual(part["total_size"], len(payload))
                self.assertEqual(part["sha256"], meta["sha256"])
                if part["eof"]:
                    break
                offset += part["length"]
            self.assertEqual(b"".join(parts), payload)
            end = catalog_bytes.read_chunk(cat, "0" * 32, len(payload), 10)
            self.assertEqual((end["length"], end["eof"], end["data_b64"]), (0, True, ""))
            with self.assertRaises(DiscoveryError) as raised:
                catalog_bytes.read_chunk(cat, "0" * 32, len(payload) + 1, 10)
            self.assertEqual(raised.exception.code, "INVALID_OFFSET")
            self.assertEqual((raised.exception.details or {})["total_size"], len(payload))
            with mock.patch.dict("os.environ", {catalog_bytes.CHUNK_ENV: "100"}):
                with self.assertRaises(DiscoveryError) as large:
                    catalog_bytes.read_chunk(cat, "0" * 32, 0, 10)
            self.assertEqual((large.exception.code, large.exception.status), ("EXPORT_TOO_LARGE_FOR_CHUNKS", 413))


if __name__ == "__main__":
    unittest.main()
