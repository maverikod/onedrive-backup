"""Smoke-check actual adapter-backed FastAPI routes using external test mTLS certs.

Run only when ONEDRIVE_TEST_CERT_DIR is set; never packages certificates.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
import tempfile

from fastapi.testclient import TestClient

from onedrive_api.admin_password import password_hash, save_record
from onedrive_api.server import make_app, tls_server_settings


def main() -> None:
    certdir = Path(os.environ["ONEDRIVE_TEST_CERT_DIR"])
    with tempfile.TemporaryDirectory(prefix="onedrive-ui-probe-") as tmp:
        root = Path(tmp)
        config = json.loads(Path("config/server.json").read_text(encoding="utf-8"))
        config["registration"]["enabled"] = False
        config["registration"]["auto_on_startup"] = False
        config["registration"]["auto_on_shutdown"] = False
        bundle = root / "trust-bundle.pem"
        bundle.write_bytes(
            (certdir / "for-proxy/ca/ca.crt").read_bytes()
            + b"\n"
            + (certdir / "cacert.pem").read_bytes()
        )
        config["server"]["ssl"].update({
            "cert": str(certdir / "for-proxy/issued/onedrive-backup.crt"),
            "key": str(certdir / "for-proxy/issued/onedrive-backup.key"),
            "ca": str(bundle),
            "crl": None,
        })
        path = root / "server.json"
        path.write_text(json.dumps(config), encoding="utf-8")
        hashed = root / "admin-password.hash"
        save_record(hashed, password_hash("TemporaryOnlyPassword2026!"))
        os.environ["ONEDRIVE_ADMIN_HASH_FILE"] = str(hashed)
        app = make_app(path)
        if os.environ.get("ONEDRIVE_SMOKE_SKIP_TLS") != "1":
            settings = tls_server_settings(config, str(path))
            assert settings["ssl_context"].verify_mode == 2
        paths = {r.path for r in app.routes if hasattr(r, "path")}
        assert "/ui/login" in paths, sorted(paths)
        assert "/ui/" in paths
        assert "/ui/exports/{export_id}/download" in paths
        assert "/commands" in paths, "MCP Proxy method discovery endpoint missing"
        assert "/api/v1/snapshots" in paths
        assert "/api/transfer/downloads" not in paths
        assert "/api/transfer/uploads" not in paths
        with TestClient(app, base_url="https://backup-srv") as client:
            assert client.get("/ui/login").status_code == 200
            assert client.get("/ui/", follow_redirects=False).status_code == 303
            health = client.get("/api/v1/health")
            assert health.status_code == 200, health.text
        print("FastAPI route smoke test: OK (TLS context check " + ("skipped" if os.environ.get("ONEDRIVE_SMOKE_SKIP_TLS") == "1" else "passed") + ")")


if __name__ == "__main__":
    main()

