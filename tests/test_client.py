"""Client integrity and mTLS policy tests without external services."""

from __future__ import annotations

import hashlib
from io import BytesIO
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "client"))
from onedrive_backup_client.api import BackupClient, ClientError


class ClientTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.dest = Path(self.tmp.name) / "download.bin"
        self.client = BackupClient.__new__(BackupClient)
        self.client.url = "https://onedrive-backup:8050"
        self.client.timeout = 5
        self.client.context = object()

    def test_url_must_be_https(self):
        with self.assertRaisesRegex(ClientError, "TLS is mandatory"):
            BackupClient("http://localhost:8050", "/missing",
                         "/missing", "/missing")

    def test_correct_download_verified_and_deleted(self):
        payload = b"hello from an encrypted snapshot"
        meta = {"size_bytes": len(payload), "sha256": hashlib.sha256(payload).hexdigest()}
        with patch.object(BackupClient, "status", return_value=meta), \
             patch.object(BackupClient, "_request", return_value=BytesIO(payload)), \
             patch.object(BackupClient, "delete", return_value={"deleted": True}) as delete:
            result = self.client.fetch("abc123", self.dest, delete_after=True)
        self.assertEqual(result, self.dest)
        self.assertEqual(self.dest.read_bytes(), payload)
        delete.assert_called_once_with("abc123")

    def test_corrupt_download_refused_and_temp_erased(self):
        payload = b"bad"
        meta = {"size_bytes": 3, "sha256": "0" * 64}
        with patch.object(BackupClient, "status", return_value=meta), \
             patch.object(BackupClient, "_request", return_value=BytesIO(payload)):
            with self.assertRaisesRegex(ClientError, "integrity mismatch"):
                self.client.fetch("abc123", self.dest)
        self.assertFalse(self.dest.exists())
        self.assertEqual(list(self.dest.parent.glob(".onedrive-download-*")), [])

    def test_existing_target_preserved(self):
        self.dest.write_bytes(b"keep")
        with self.assertRaisesRegex(ClientError, "exists"):
            self.client.fetch("abc123", self.dest)
        self.assertEqual(self.dest.read_bytes(), b"keep")

    def test_path_is_encoded_in_request(self):
        with patch.object(BackupClient, "_json", return_value={"items": []}) as call:
            self.client.files("ab12", "docs/R&D and spaces", 3, 20)
        self.assertIn("R%26D+and+spaces", call.call_args.args[1])
        self.assertIn("offset=3", call.call_args.args[1])


if __name__ == "__main__":
    unittest.main()

