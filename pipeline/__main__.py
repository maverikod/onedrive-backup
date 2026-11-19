"""OneDrive Backup project verification entrypoint: python -m pipeline."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
CHECKS = ("python_syntax", "shell_syntax", "config_contract", "unit_tests", "security")
EXTRA = ("smoke_mtls",)


def run(*args: str, env: dict | None = None) -> None:
    print("[RUN]", " ".join(args), flush=True)
    subprocess.run(args, cwd=ROOT, env=env, check=True)


def python_syntax() -> None:
    run(sys.executable, "-m", "compileall", "-q", "src", "client/onedrive_backup_client", "tests", "pipeline")


def shell_syntax() -> None:
    scripts = (
        "build.sh", "scripts/build-deb.sh", "scripts/smoke-mtls.sh",
        "docker/deploy.sh", "packaging/onedrive-backup-docker",
        "packaging/onedrive-backup", "packaging/postinst",
        "packaging/prerm", "packaging/postrm", "packaging/install-runtime.sh",
    )
    run("bash", "-n", *scripts)


def config_contract() -> None:
    from pipeline.environment import endpoint
    main = json.loads((ROOT / "config/server.json").read_text())
    backup = json.loads((ROOT / "config/backup.json").read_text())
    assert main["server"]["protocol"] == "mtls", "mTLS server required"
    assert main["server"]["port"] == 8050
    assert main["registration"]["server_id"] == "onedrive-backup"
    assert main["registration"]["enabled"] is True
    assert main["registration"]["protocol"] == "mtls"
    assert main["registration"]["register_url"] == endpoint("MCP_PROXY_REGISTER_URL")
    assert main["registration"]["heartbeat"]["url"] == endpoint("MCP_PROXY_HEARTBEAT_URL")
    for field in ("cert", "key", "ca"):
        assert main["server"]["ssl"][field].startswith("/config/certs/")
    for field in ("cert", "key"):
        assert main["registration"]["ssl"][field] == main["server"]["ssl"][field]
    assert main["registration"]["ssl"]["ca"] == "/config/certs/proxy-ca.crt"
    # Revocation checks are owned by MCP Proxy, not the internal FastAPI server.
    assert main["server"]["ssl"]["crl"] is None
    assert main["registration"]["ssl"]["crl"] is None
    assert json.loads((ROOT / "packaging/server.json").read_text()) == main
    assert "    ports:" not in (ROOT / "docker/compose.yml").read_text()
    assert "-p " not in (ROOT / "packaging/docker-run.sh").read_text()
    # Revision 9 (D10): the service reads a writable copy of rclone.conf under /rclone-state; the original and the restic
    # password stay under the read-only /secrets; /data is the container mount point (D8 (c)).
    api = json.loads((ROOT / "packaging/api-backup.json").read_text())
    for name, cfg in (("config/backup.json", backup), ("packaging/api-backup.json", api)):
        assert cfg["mirror_dir"] == "/data/mirror", name + ": mirror_dir"
        assert cfg["repository_dir"] == "/data/restic-repo", name + ": repository_dir"
        assert cfg["password_file"] == "/secrets/restic-password", name + ": password_file must stay /secrets/restic-password"
        assert cfg["rclone_config"].startswith("/rclone-state/"), name + ": rclone_config must start with /rclone-state/"
        assert cfg["required_mountpoint"] == "/data", name + ": required_mountpoint must stay /data inside the container"


def unit_tests() -> None:
    tmp = ROOT / ".test-run"
    tmp.mkdir(exist_ok=True)
    env = os.environ.copy()
    env["TMPDIR"] = str(tmp)
    env["PYTHONPATH"] = os.pathsep.join((str(ROOT / "src"), str(ROOT / "client")))
    run(sys.executable, "-m", "unittest", "discover",
        "-s", "tests", "-p", "test_*.py", "-v", env=env)


def security() -> None:
    tracked = subprocess.check_output(["git", "-c", "safe.directory=%s" % ROOT, "ls-files"], cwd=ROOT,
                                      text=True).splitlines()
    for path in tracked:
        name = Path(path).name.lower()
        assert name != ".env", "Credentials cannot be committed"
        assert not name.endswith((".key", ".pem", ".crt", ".crl")), (
            "Certificate material must be external: " + path
        )
    dockerfile = (ROOT / "docker/Dockerfile").read_text()
    assert "USER 1000:1000" in dockerfile
    assert "EXPOSE 8050" in dockerfile
    ignore = (ROOT / ".dockerignore").read_text()
    assert ".env" in ignore
    assert "*.key" in ignore
    assert (ROOT / "packaging/onedrive-backup-api.service").exists()


def smoke_mtls() -> None:
    run("bash", "scripts/smoke-mtls.sh")


def main(argv: list[str] | None = None) -> int:
    from pipeline import checks as named_checks

    matrix_names = tuple(named_checks.all_names())
    parser = argparse.ArgumentParser(description="OneDrive backup verification pipeline")
    parser.add_argument("check", nargs="?", choices=CHECKS + EXTRA + matrix_names)
    parser.add_argument("--list", action="store_true")
    args = parser.parse_args(argv)
    if args.list:
        for name in CHECKS + EXTRA + matrix_names:
            print(name)
        return 0
    selected = [args.check] if args.check else list(CHECKS) + list(matrix_names)
    for name in selected:
        print("[CHECK]", name, flush=True)
        if name in matrix_names:
            try:
                named_checks.run(name)
            except named_checks.CheckFailure as exc:
                print("[RED]", name, "-", exc, flush=True)
                return 1
        else:
            globals()[name]()
        print("[GREEN]", name, flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
