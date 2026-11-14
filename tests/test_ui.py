"""API browser login and admin password checks (no real backup credentials)."""
from __future__ import annotations

import hashlib
import os
from pathlib import Path
import re
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from onedrive_api.admin_password import (
    AuthError, authenticate_session, issue_session,
    load_record, password_hash, save_record, verify_password,
)

try:
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from onedrive_api.ui import install_ui
    HAS_FASTAPI = True
except ImportError:
    HAS_FASTAPI = False


PASSWORD = "correct-horse-battery-staple"


class PasswordTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.hash_file = Path(self.tmp.name) / "admin-password.hash"

    def test_password_hash_verification_and_permissions(self):
        record = password_hash(PASSWORD)
        save_record(self.hash_file, record)
        self.assertEqual(os.stat(self.hash_file).st_mode & 0o777, 0o600)
        self.assertTrue(verify_password(PASSWORD, load_record(self.hash_file)))
        self.assertFalse(verify_password("incorrect-password", load_record(self.hash_file)))
        self.assertNotIn(PASSWORD, self.hash_file.read_text())

    def test_no_default_password_and_restrict_permissions(self):
        with self.assertRaises(AuthError):
            load_record(self.hash_file)
        save_record(self.hash_file, password_hash(PASSWORD))
        self.hash_file.chmod(0o644)
        with self.assertRaises(AuthError):
            load_record(self.hash_file)

    def test_rotation_revokes_old_sessions(self):
        original = password_hash(PASSWORD)
        cookie, csrf = issue_session(original)
        self.assertEqual(authenticate_session(original, cookie)["csrf"], csrf)
        newer = password_hash(PASSWORD + "-new")
        self.assertIsNone(authenticate_session(newer, cookie))
        self.assertIsNone(authenticate_session(original, cookie + "x"))

    def test_reject_short_password(self):
        with self.assertRaises(ValueError):
            password_hash("admin")


class FakeCatalog:
    def __init__(self, root: Path):
        self.root = root
        self.file = root / "test-file.txt"
        self.file.write_text("HELLO WORLD")

    def snapshots(self, limit=100):
        return {"items": [{
            "id": "a" * 64,
            "time": "2026-11-14T10:00:00Z",
            "tags": ["onedrive", "<script>alert(1)</script>"]
        }], "count": 1}

    def files(self, snapshot_id, prefix="", limit=100, offset=0):
        nodes = [{"path": "<img src=x onerror=alert(1)>.txt",
                  "type": "file", "size": 12, "mtime": "now"},
                 {"path": "Documents", "type": "dir", "size": 0, "mtime": "now"}]
        return {"items": nodes[offset:offset+limit], "total": len(nodes),
                "offset": offset, "limit": limit}

    def prepare(self, snapshot_id, file_path=None):
        return self.export_status("b" * 32)

    def get_export(self, export_id):
        return self.export_status(export_id), self.file

    def export_status(self, export_id):
        return {"export_id": export_id, "snapshot_id": "a" * 64,
                "path": None, "filename": "test-file.txt",
                "size_bytes": self.file.stat().st_size,
                "sha256": hashlib.sha256(self.file.read_bytes()).hexdigest(),
                "expires_at": "2030-01-01T00:00:00+00:00"}

    def delete_export(self, export_id):
        return {"deleted": True, "export_id": export_id}


@unittest.skipUnless(HAS_FASTAPI, "FastAPI is installed in the production image")
class BrowserTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.record = self.root / "admin-password.hash"
        save_record(self.record, password_hash(PASSWORD))
        self.catalog = FakeCatalog(self.root)
        app = FastAPI()
        install_ui(app, lambda: self.catalog, password_file=self.record)
        self.client = TestClient(app, base_url="https://backup-srv")
        self.addCleanup(self.client.close)

    @staticmethod
    def csrf(page):
        match = re.search('name="csrf" value="([^"]+)"', page.text)
        assert match
        return match.group(1)

    def login(self):
        form = self.client.get("/ui/login")
        self.assertEqual(form.status_code, 200)
        response = self.client.post("/ui/login",
                                    data={"username": "admin",
                                          "password": PASSWORD,
                                          "csrf": self.csrf(form)},
                                    follow_redirects=False)
        self.assertEqual(response.status_code, 303, response.text)

    def test_scaffold_never_authenticates_without_password(self):
        self.record.unlink()
        self.assertEqual(self.client.get("/ui/login").status_code, 503)
        self.assertEqual(self.client.get("/ui/", follow_redirects=False).status_code, 503)
        self.assertEqual(self.client.post("/ui/login", data={
            "username": "admin", "password": PASSWORD, "csrf": "test"
        }).status_code, 503)

    def test_protected_before_auth_and_missing_hash(self):
        self.assertEqual(self.client.get("/ui/", follow_redirects=False).status_code, 303)
        self.assertEqual(self.client.get("/ui/snapshots/" + "a" * 64,
                                         follow_redirects=False).status_code, 303)
        self.assertEqual(self.client.get("/ui/exports/" + "b" * 32 + "/download",
                                         follow_redirects=False).status_code, 303)
        self.record.unlink()
        self.assertEqual(self.client.get("/ui/login").status_code, 503)

    def test_login_rejects_wrong_csrf_and_password(self):
        form = self.client.get("/ui/login")
        self.assertEqual(self.client.post("/ui/login",
                                         data={"username": "admin",
                                               "password": PASSWORD,
                                               "csrf": "bad"}).status_code, 403)
        response = self.client.post("/ui/login",
                                    data={"username": "admin",
                                          "password": "not-the-password",
                                          "csrf": self.csrf(form)})
        self.assertEqual(response.status_code, 200)
        self.assertNotIn("Set-Cookie: " + "__Secure-onedrive-admin", str(response.headers))

    def test_login_rate_limit(self):
        form = self.client.get("/ui/login")
        for _ in range(5):
            self.client.post("/ui/login", data={
                "username": "admin", "password": "incorrect-password",
                "csrf": self.csrf(form)})
        blocked = self.client.post("/ui/login", data={
            "username": "admin", "password": PASSWORD, "csrf": self.csrf(form)})
        self.assertEqual(blocked.status_code, 429)

    def test_browse_and_escape_html(self):
        self.login()
        page = self.client.get("/ui/")
        self.assertEqual(page.status_code, 200)
        self.assertIn("Снимки резервных копий", page.text)
        self.assertNotIn("<script>alert(1)</script>", page.text)
        self.assertIn("&lt;script&gt;", page.text)
        detail = self.client.get("/ui/snapshots/" + "a" * 64)
        self.assertEqual(detail.status_code, 200)
        self.assertNotIn("<img src=x onerror=alert(1)>", detail.text)
        self.assertIn("&lt;img", detail.text)
        self.assertEqual(detail.headers.get("cache-control"), "no-store, private")
        self.assertIn("frame-ancestors", detail.headers.get("content-security-policy", ""))

    def test_export_download_logout_csrf(self):
        self.login()
        detail = self.client.get("/ui/snapshots/" + "a" * 64)
        invalid = self.client.post("/ui/export", data={"snapshot_id": "a" * 64, "csrf": "wrong"})
        self.assertEqual(invalid.status_code, 403)
        ready = self.client.post("/ui/export",
                                 data={"snapshot_id": "a" * 64,
                                       "csrf": self.csrf(detail)},
                                 follow_redirects=False)
        self.assertEqual(ready.status_code, 303)
        destination = ready.headers["location"]
        page = self.client.get(destination)
        self.assertIn("Выгрузка готова", page.text)
        response = self.client.get(destination + "/download")
        self.assertEqual(response.content, b"HELLO WORLD")
        self.assertEqual(response.headers["x-content-sha256"],
                         hashlib.sha256(b"HELLO WORLD").hexdigest())
        logout = self.client.post("/ui/logout", data={"csrf": self.csrf(page)},
                                  follow_redirects=False)
        self.assertEqual(logout.status_code, 303)
        self.assertEqual(self.client.get("/ui/", follow_redirects=False).status_code, 303)

if __name__ == "__main__":
    unittest.main()

