"""Staging and reading of exports (matrix 10.22.4): every address form, inline reads and backup_download_chunk.

A file addressed by file_id or by names is looked up in the file name index and dumped straight from restic; only the
snapshot_id + file_path form and the archive form list the whole snapshot.
"""

from __future__ import annotations

import base64
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import subprocess
from typing import Any
from uuid import uuid4

from .catalog import Catalog, CatalogError
from .file_address import check_address, full_snapshot_id, invalid, make_file_id, not_found, resolve_file_id, resolve_names
from .file_index import FileIndex
from .sharepoint_base import DiscoveryError

CHUNK_ENV = "ONEDRIVE_CHUNK_MAX_EXPORT_BYTES"
CHUNK_MAX_EXPORT = 4 * 1024 * 1024
FETCH_STAGED = (
    "Read the bytes with backup_download_chunk (export_id, offset, limit: up to 262144 bytes per call, base64) while "
    "size_bytes is at most 4194304; for a larger export open the url or use backup_download_begin. Verify size_bytes "
    "and sha256, then delete the export with backup_delete_export."
)
FETCH_INLINE = (
    "content_b64 holds the whole file (base64); no export was staged. Verify size_bytes and sha256 after decoding."
)


def _dump_bytes(cat: Catalog, snapshot_id: str, internal_path: str) -> bytes:
    """Read one file of a snapshot into memory with restic dump.

    Args:
        cat: The catalogue.
        snapshot_id: The snapshot id.
        internal_path: The path of the file inside the restic repository.

    Returns:
        The bytes of the file.
    """
    base, env, _ = cat._base()
    try:
        proc = subprocess.run(
            base + ["dump", snapshot_id, internal_path], env=env, capture_output=True, timeout=600, check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise CatalogError("Restic dump failed or timed out", 503) from exc
    if proc.returncode:
        raise CatalogError("Restic dump failed: " + proc.stderr.decode("utf-8", "replace")[-250:], 503)
    return proc.stdout


def _select(cat: Catalog, snapshot_id: str, relative: str, known: tuple[str, int] | None) -> dict[str, Any]:
    """Find the file node to stage: from the index answer, or by listing the snapshot.

    Args:
        cat: The catalogue.
        snapshot_id: The snapshot id.
        relative: The file_path of the file.
        known: The (file_path, size) the index gave, or None to list the snapshot.

    Returns:
        The node with path, restic_path and size.
    """
    if known is not None:
        prefix = cat._config()["mirror_dir"].as_posix().rstrip("/") + "/"
        return {"path": relative, "restic_path": prefix + relative, "size": known[1]}
    nodes = cat._all_nodes(snapshot_id)
    selected = next((n for n in nodes if n["path"] == relative and n["type"] == "file"), None)
    if selected is None:
        raise not_found("File not found in snapshot", {"field": "file_path", "value": relative[:64]})
    return selected


def stage(
    cat: Catalog, snapshot_id: str, file_path: str | None, *, known: tuple[str, int] | None = None, inline: int = 0,
) -> dict[str, Any]:
    """Stage one file or a whole snapshot archive, or answer a small file inline.

    Args:
        cat: The catalogue.
        snapshot_id: The snapshot id (a prefix of at least 8 hex digits is accepted).
        file_path: The file_path of one file, or None for the whole snapshot archive.
        known: The (file_path, size) the file name index gave for the file, or None.
        inline: Files up to this many bytes are returned inside the answer and stage no export.

    Returns:
        The export metadata with staged, content_b64 and how_to_fetch.
    """
    snapshot_id = cat._check_snapshot(snapshot_id)
    relative = cat._check_path(file_path) if file_path is not None else None
    cat._config()
    cat.exports.mkdir(mode=0o700, parents=True, exist_ok=True)
    cat._sweep_expired()
    selected, total_size = None, 0
    if relative is not None:
        selected = _select(cat, snapshot_id, relative, known)
        cat._validate_size(selected["size"])
    else:
        total_size = sum(n["size"] for n in cat._all_nodes(snapshot_id) if n["type"] == "file" and isinstance(n["size"], int))
        cat._validate_size(total_size)
    full = full_snapshot_id(FileIndex(cat.data_dir), snapshot_id) if relative is not None else None
    file_id = make_file_id(full, relative) if full and relative is not None else None
    now = datetime.now(timezone.utc)
    if selected is not None and 0 < inline and selected["size"] <= inline:
        data = _dump_bytes(cat, snapshot_id, selected["restic_path"])
        return {
            "export_id": None, "snapshot_id": snapshot_id, "path": file_path, "filename": Path(selected["path"]).name,
            "size_bytes": len(data), "sha256": hashlib.sha256(data).hexdigest(), "created_at": now.isoformat(),
            "expires_at": None, "url": None, "file_id": file_id, "kind": "file", "staged": False,
            "content_b64": base64.b64encode(data).decode("ascii"), "how_to_fetch": FETCH_INLINE,
        }
    export_id = uuid4().hex
    output = cat._output_path(export_id, archive=selected is None)
    filename = "onedrive-" + snapshot_id[:12] + ".tar.gz" if selected is None else Path(selected["path"]).name
    try:
        if selected is None:
            cat._archive_snapshot(snapshot_id, output)
        else:
            cat._dump_file(snapshot_id, selected["restic_path"], output)
        digest = hashlib.sha256()
        with output.open("rb") as inp:
            for block in iter(lambda: inp.read(1024 * 1024), b""):
                digest.update(block)
        meta = {
            "export_id": export_id, "snapshot_id": snapshot_id, "path": file_path, "filename": filename,
            "size_bytes": output.stat().st_size, "sha256": digest.hexdigest(), "file_id": file_id,
            "created_at": now.isoformat(), "expires_at": (now + cat.ttl).isoformat(),
        }
        metadata = cat._metadata_path(export_id)
        with metadata.open("x", encoding="utf-8") as fp:
            json.dump(meta, fp)
        metadata.chmod(0o600)
        return {**cat._with_url(meta), "staged": True, "content_b64": None, "how_to_fetch": FETCH_STAGED}
    except BaseException:
        output.unlink(missing_ok=True)
        cat._metadata_path(export_id).unlink(missing_ok=True)
        raise


def prepare_request(cat: Catalog, params: dict[str, Any]) -> dict[str, Any]:
    """Run backup_prepare_download for any address form.

    Args:
        cat: The catalogue.
        params: file_id, snapshot_id, file_path, site_id, drive_id, dir, name, copy_index and inline_max_bytes;
            None means omitted.

    Returns:
        The result of backup_prepare_download.
    """
    form = check_address(params)
    inline = params.get("inline_max_bytes") or 0
    if form == "B" or form == "archive":
        return stage(cat, params["snapshot_id"], params.get("file_path"), inline=inline)
    cat._config()
    index = FileIndex(cat.data_dir)
    if form == "A":
        snapshot, path, size = resolve_file_id(index, params["file_id"])
    else:
        snapshot, path, size = resolve_names(index, params)
    return stage(cat, snapshot, path, known=(path, size), inline=inline)


def read_chunk(cat: Catalog, export_id: str, offset: int = 0, limit: int = 65536) -> dict[str, Any]:
    """Return one base64 slice of a staged export; nothing is written and the expiry is not extended.

    Args:
        cat: The catalogue.
        export_id: The export id.
        offset: The first byte of the slice.
        limit: The most bytes of the slice.

    Returns:
        The slice with its total size, the sha256 of the whole export and the sha256 of the slice.
    """
    meta, path = cat.get_export(export_id)
    total = path.stat().st_size
    cap = int(os.environ.get(CHUNK_ENV) or CHUNK_MAX_EXPORT)
    if total > cap:
        raise DiscoveryError("EXPORT_TOO_LARGE_FOR_CHUNKS", 413, {
            "total_size": total, "limit": cap, "hint": "Use backup_download_begin, or the url of backup_download_status."})
    if offset > total:
        data = invalid("INVALID_OFFSET", "offset", offset, "0..%d" % total, "offset must not exceed total_size.")
        assert data.details is not None
        data.details["total_size"] = total
        raise data
    with path.open("rb") as stream:
        stream.seek(offset)
        raw = stream.read(limit)
    return {
        "export_id": export_id, "offset": offset, "length": len(raw), "eof": offset + len(raw) == total,
        "total_size": total, "sha256": meta["sha256"], "chunk_sha256": hashlib.sha256(raw).hexdigest(),
        "encoding": "base64", "data_b64": base64.b64encode(raw).decode("ascii"),
    }
