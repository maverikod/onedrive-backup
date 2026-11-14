"""Read-only restic catalogue and bounded export staging for OneDrive backups.

Only opaque export identifiers, never filesystem paths, cross the public API.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import shutil
import subprocess
import tarfile
import tempfile
from uuid import uuid4

from onedrive_backup import load_config, BackupError


SNAPSHOT_RE = re.compile(r"^[0-9a-fA-F]{8,64}$")
EXPORT_RE = re.compile(r"^[0-9a-f]{32}$")


class CatalogError(Exception):
    """Error with an appropriate HTTP status code."""

    def __init__(self, message: str, status: int = 400):
        super().__init__(message)
        self.status = status


class Catalog:
    """Restic snapshot browsing and safe, encrypted-source exports."""

    def __init__(
        self,
        config_path: str | Path,
        data_dir: str | Path,
        max_export_bytes: int = 10 * 1024 ** 3,
        export_ttl_hours: int = 24,
    ) -> None:
        self.config_path = Path(config_path)
        self.data_dir = Path(data_dir).resolve()
        self.exports = self.data_dir / "exports"
        self.max_export_bytes = max_export_bytes
        self.ttl = timedelta(hours=export_ttl_hours)
        if max_export_bytes < 1 or export_ttl_hours < 1:
            raise ValueError("Invalid export limits")

    def _config(self) -> dict:
        try:
            cfg = load_config(self.config_path)
            root = cfg["required_mountpoint"]
            if root and not root.is_mount():
                raise CatalogError("Backup storage is not mounted", 503)
            repo = cfg["repository_dir"]
            mirror = cfg["mirror_dir"]
            if not (repo / "config").is_file():
                raise CatalogError("Restic repository is not initialized", 503)
            if not self._within(self.data_dir, repo) or not self._within(self.data_dir, mirror):
                raise CatalogError("Repository and mirror must be inside data directory", 503)
            secret = cfg["password_file"]
            if not secret.is_file() or secret.stat().st_mode & 0o077:
                raise CatalogError("Restic password missing or insufficiently protected", 503)
            return cfg
        except (BackupError, OSError) as exc:
            raise CatalogError("Backup configuration unavailable: " + str(exc), 503) from exc

    @staticmethod
    def _within(parent: Path, candidate: Path) -> bool:
        return candidate == parent or parent in candidate.parents

    def _base(self) -> tuple[list[str], dict, dict]:
        cfg = self._config()
        env = os.environ.copy()
        env["RESTIC_REPOSITORY"] = str(cfg["repository_dir"])
        env["RESTIC_PASSWORD_FILE"] = str(cfg["password_file"])
        return [cfg["restic_bin"]], env, cfg

    @staticmethod
    def _check_snapshot(value: str) -> str:
        if not isinstance(value, str) or not SNAPSHOT_RE.fullmatch(value):
            raise CatalogError("Invalid snapshot identifier")
        return value.lower()

    @staticmethod
    def _check_path(value: str) -> str:
        if not isinstance(value, str) or not value or value.startswith("/") or "\\" in value:
            raise CatalogError("Expected a relative, nonempty POSIX file path")
        pure = PurePosixPath(value)
        if any(p in ("", ".", "..") for p in value.split("/")) or pure.is_absolute():
            raise CatalogError("Path traversal is forbidden")
        return pure.as_posix()

    @staticmethod
    def _check_export(value: str) -> str:
        if not isinstance(value, str) or not EXPORT_RE.fullmatch(value):
            raise CatalogError("Invalid export identifier")
        return value

    def _run(self, arguments: list[str], *, timeout: int = 120) -> str:
        base, env, _ = self._base()
        try:
            proc = subprocess.run(
                base + arguments, env=env, stdout=subprocess.PIPE,
                stderr=subprocess.PIPE, timeout=timeout, check=False, text=True,
                encoding="utf-8", errors="replace",
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            raise CatalogError("Restic is unavailable or timed out", 503) from exc
        if proc.returncode:
            raise CatalogError("Restic failed: " + proc.stderr.strip()[:350], 503)
        return proc.stdout

    def snapshots(self, limit: int = 100) -> dict:
        if type(limit) is not int or not 1 <= limit <= 1000:
            raise CatalogError("limit must be 1..1000")
        try:
            items = json.loads(self._run(["snapshots", "--json", "--tag", "onedrive"]))
        except (ValueError, TypeError) as exc:
            raise CatalogError("Invalid restic snapshot JSON", 503) from exc
        if not isinstance(items, list):
            raise CatalogError("Invalid restic snapshot format", 503)
        items.sort(key=lambda x: x.get("time", ""), reverse=True)
        return {"items": items[:limit], "count": len(items)}

    def _all_nodes(self, snapshot_id: str) -> list[dict]:
        snapshot_id = self._check_snapshot(snapshot_id)
        base, env, cfg = self._base()
        mirror_prefix = cfg["mirror_dir"].as_posix().rstrip("/") + "/"
        found: list[dict] = []
        try:
            with tempfile.TemporaryFile() as errors:
                proc = subprocess.Popen(
                    base + ["ls", "--json", snapshot_id],
                    env=env, stdout=subprocess.PIPE, stderr=errors,
                    text=True, encoding="utf-8", errors="replace",
                )
                try:
                    assert proc.stdout is not None
                    scanned = 0
                    for line in proc.stdout:
                        scanned += 1
                        if scanned > 500000:
                            raise CatalogError("Snapshot has too many nodes; refusing unbounded listing", 413)
                        try:
                            node = json.loads(line)
                        except ValueError as exc:
                            raise CatalogError("Invalid restic listing JSON", 503) from exc
                        if node.get("struct_type") != "node":
                            continue
                        full = node.get("path", "")
                        if not isinstance(full, str) or not full.startswith(mirror_prefix):
                            continue
                        rel = full[len(mirror_prefix):]
                        if not rel:
                            continue
                        found.append({
                            "path": rel,
                            "restic_path": full,
                            "type": node.get("type", ""),
                            "size": node.get("size", 0),
                            "mtime": node.get("mtime", ""),
                        })
                    rc = proc.wait(timeout=120)
                    if rc:
                        errors.seek(0)
                        raise CatalogError(
                            "Restic listing failed: " + errors.read(300).decode("utf-8", "replace"),
                            503,
                        )
                except BaseException:
                    if proc.poll() is None:
                        proc.kill()
                    proc.wait()
                    raise
        except OSError as exc:
            raise CatalogError("Cannot list restic snapshot", 503) from exc
        return found

    def files(self, snapshot_id: str, prefix: str = "", limit: int = 1000,
              offset: int = 0) -> dict:
        if type(limit) is not int or not 1 <= limit <= 5000:
            raise CatalogError("limit must be 1..5000")
        if type(offset) is not int or not 0 <= offset <= 500000:
            raise CatalogError("offset must be 0..500000")
        if prefix:
            prefix = self._check_path(prefix)
        nodes = [n for n in self._all_nodes(snapshot_id)
                 if not prefix or n["path"] == prefix or n["path"].startswith(prefix + "/")]
        return {
            "snapshot_id": snapshot_id, "items": [
                {k: v for k, v in n.items() if k != "restic_path"}
                for n in nodes[offset:offset + limit]
            ], "total": len(nodes), "offset": offset, "limit": limit,
        }

    def _output_path(self, export_id: str, *, archive: bool = False) -> Path:
        return self.exports / (export_id + (".tar.gz" if archive else ".bin"))

    def _metadata_path(self, export_id: str) -> Path:
        return self.exports / (export_id + ".json")

    def _validate_size(self, size: int) -> None:
        if type(size) is not int or size < 0 or size > self.max_export_bytes:
            raise CatalogError("Requested export exceeds configured limit", 413)

    def _dump_file(self, snapshot_id: str, internal_path: str, output: Path) -> None:
        base, env, _ = self._base()
        try:
            with output.open("xb") as stream:
                proc = subprocess.run(
                    base + ["dump", snapshot_id, internal_path],
                    env=env, stdout=stream, stderr=subprocess.PIPE,
                    timeout=3600, check=False,
                )
            if proc.returncode:
                raise CatalogError("Restic dump failed: " +
                                   proc.stderr.decode("utf-8", "replace")[-250:], 503)
            self._validate_size(output.stat().st_size)
        except (OSError, subprocess.TimeoutExpired) as exc:
            raise CatalogError("Restic dump failed or timed out", 503) from exc

    def _archive_snapshot(self, snapshot_id: str, output: Path) -> None:
        base, env, cfg = self._base()
        with tempfile.TemporaryDirectory(prefix="restore-", dir=self.exports) as tmp:
            try:
                proc = subprocess.run(
                    base + ["restore", snapshot_id, "--target", tmp],
                    env=env, capture_output=True, timeout=7200, check=False,
                )
                if proc.returncode:
                    raise CatalogError("Restic restore failed: " +
                                       proc.stderr.decode("utf-8", "replace")[-250:], 503)
                source = Path(tmp) / cfg["mirror_dir"].as_posix().lstrip("/")
                if not source.is_dir() or source.is_symlink():
                    raise CatalogError("Restored mirror directory not found", 503)
                with tarfile.open(output, "x:gz") as tar:
                    for node in sorted(source.rglob("*")):
                        if node.is_symlink():
                            raise CatalogError("Symlinks cannot be exported", 400)
                        if not (node.is_file() or node.is_dir()):
                            raise CatalogError("Unsupported file type in snapshot", 400)
                        tar.add(node, arcname=str(node.relative_to(source)),
                                recursive=False)
                    # No absolute paths or links in generated archives.
                self._validate_size(output.stat().st_size)
            except (OSError, subprocess.TimeoutExpired, tarfile.TarError) as exc:
                raise CatalogError("Snapshot archive failed or timed out", 503) from exc

    def prepare(self, snapshot_id: str, file_path: str | None = None) -> dict:
        snapshot_id = self._check_snapshot(snapshot_id)
        self.exports.mkdir(mode=0o700, parents=True, exist_ok=True)
        nodes = self._all_nodes(snapshot_id)
        selected: dict | None = None
        total_size = 0
        if file_path is not None:
            relative = self._check_path(file_path)
            selected = next((n for n in nodes
                             if n["path"] == relative and n["type"] == "file"), None)
            if selected is None:
                raise CatalogError("File not found in snapshot", 404)
            self._validate_size(selected["size"])
        else:
            total_size = sum(n["size"] for n in nodes
                             if n["type"] == "file" and isinstance(n["size"], int))
            self._validate_size(total_size)
        export_id = uuid4().hex
        archive = selected is None
        output = self._output_path(export_id, archive=archive)
        filename = "onedrive-" + snapshot_id[:12] + ".tar.gz" if archive else Path(selected["path"]).name
        try:
            if archive:
                self._archive_snapshot(snapshot_id, output)
            else:
                self._dump_file(snapshot_id, selected["restic_path"], output)
            digest = hashlib.sha256()
            with output.open("rb") as inp:
                for block in iter(lambda: inp.read(1024 * 1024), b""):
                    digest.update(block)
            meta = {
                "export_id": export_id, "snapshot_id": snapshot_id,
                "path": file_path, "filename": filename,
                "size_bytes": output.stat().st_size, "sha256": digest.hexdigest(),
                "created_at": datetime.now(timezone.utc).isoformat(),
                "expires_at": (datetime.now(timezone.utc) + self.ttl).isoformat(),
            }
            metadata = self._metadata_path(export_id)
            with metadata.open("x", encoding="utf-8") as fp:
                json.dump(meta, fp)
            metadata.chmod(0o600)
            return meta
        except BaseException:
            output.unlink(missing_ok=True)
            self._metadata_path(export_id).unlink(missing_ok=True)
            raise

    def get_export(self, export_id: str) -> tuple[dict, Path]:
        export_id = self._check_export(export_id)
        meta_path = self._metadata_path(export_id)
        try:
            meta = json.loads(meta_path.read_text(encoding="utf-8"))
            if meta.get("export_id") != export_id:
                raise CatalogError("Invalid export metadata", 503)
            expire = datetime.fromisoformat(meta["expires_at"])
            if expire < datetime.now(timezone.utc):
                raise CatalogError("Export has expired", 410)
            filename = self._output_path(export_id, archive=meta["path"] is None)
            if not filename.is_file() or filename.is_symlink():
                raise CatalogError("Export data is missing", 404)
            return meta, filename
        except FileNotFoundError as exc:
            raise CatalogError("Unknown export identifier", 404) from exc
        except (ValueError, KeyError, OSError) as exc:
            raise CatalogError("Invalid export metadata", 503) from exc

    def export_status(self, export_id: str) -> dict:
        return self.get_export(export_id)[0]

    def delete_export(self, export_id: str) -> dict:
        _, output = self.get_export(export_id)
        output.unlink()
        self._metadata_path(export_id).unlink()
        return {"export_id": export_id, "deleted": True}

