"""Keep every copy of colliding SharePoint files (matrix revision 10).

After the sync mirrored the first file of every collision group, each further
member (an "extra") is fetched by its Graph item id and stored beside its twin
as ``<stem>.dup-<h><ext>``, verified against the size and quickXorHash of the
scan, and reported in the run record of the library. Problems are recorded,
never raised; nothing is deleted and nothing is written to SharePoint.
"""

from __future__ import annotations

import base64
import hashlib
import logging
import os
from pathlib import Path
from typing import Any, Callable

from .sharepoint_dupfetch import ContentFetcher, local_quickxor, new_file_mode
from .sharepoint_dupnames import (
    DIRECTORY_UNSUPPORTED, ERROR_ORDER, FETCH_FAILED, INTEGRITY_MISMATCH,
    NAME_RESERVED, collision_groups, duplicate_directories, is_reserved,
    item_id_of, name_key, pick_primary, plain_file, stored_as,
)

LOG = logging.getLogger("onedrive_backup")


def empty_record() -> dict[str, Any]:
    """Return the duplicate fields of a library that was not scanned.

    Returns:
        ``duplicates`` [] and an all-zero ``duplicate_summary``.
    """
    return {
        "duplicates": [],
        "duplicate_summary": {
            "groups": 0, "kept": 0, "failed": 0, "stale": 0,
        },
    }


def _digest(row: dict[str, Any]) -> str | None:
    """Return the lowercase hex quickXorHash of a listing row, if any.

    Args:
        row: File row of the scan.

    Returns:
        The hash string or None when Graph gave none.
    """
    value = (row.get("Hashes") or {}).get("quickxor")
    return str(value).lower() if value else None


def _store(
    cfg: dict[str, Any], runner: Callable[..., str],
    fetcher: ContentFetcher, target: Path, extra: dict[str, Any],
) -> None:
    """Fetch and verify one extra and fill its record.

    A stored copy that already equals the scan is not fetched again. A failed
    check is repeated once with a new download; a copy that still differs is
    kept under its stored name and flagged, a failed fetch leaves no file.

    Args:
        cfg: Validated backup configuration.
        runner: Command runner of the backup module (run_command).
        fetcher: Content fetcher of the library.
        target: Mirror directory of the library.
        extra: Record of the extra (item_id, stored_as, size, _digest).
    """
    wanted = extra["_digest"]
    good = "hash_unavailable" if wanted is None else "ok"
    dest = target / extra["stored_as"]

    def verified(path: Path) -> bool:
        """Compare size and hash of a local file with the scan."""
        if path.stat().st_size != extra["size"]:
            return False
        return wanted is None or local_quickxor(cfg, runner, path) == wanted

    if dest.is_file() and verified(dest):
        extra["integrity"] = good
        return
    tmp = target.parent / (
        ".dup-part-" + hashlib.sha256(
            extra["item_id"].encode("utf-8")).hexdigest()[:16]
    )
    ok = False
    for _ in range(2):
        if not fetcher.fetch(extra["item_id"], tmp):
            extra["integrity"] = "fetch_failed"
            extra["error"] = FETCH_FAILED
            return
        ok = verified(tmp)
        if ok:
            break
    dest.parent.mkdir(parents=True, exist_ok=True)
    os.chmod(tmp, new_file_mode())
    os.replace(tmp, dest)
    extra["integrity"] = good if ok else "mismatch"
    if not ok:
        extra["error"] = INTEGRITY_MISMATCH


def _extras(
    groups: list[list[dict[str, Any]]], target: Path,
    cfg: dict[str, Any], runner: Callable[..., str],
    taken: set[str],
) -> list[dict[str, Any]]:
    """Name the extras of every group (the primary stays at the plain path).

    Args:
        groups: Collision groups of the scan.
        target: Mirror directory of the library.
        cfg: Validated backup configuration.
        runner: Command runner of the backup module (run_command).
        taken: name_key of every source path; extended with the new names.

    Returns:
        One record per extra, in a stable order.
    """
    found: list[dict[str, Any]] = []
    for group in groups:
        plain = plain_file(target, group)
        size = plain.stat().st_size if plain else None
        digest = local_quickxor(cfg, runner, plain) if plain else None
        primary = pick_primary(group, size, digest)
        for row in sorted(group, key=item_id_of):
            if row is primary:
                continue
            name = stored_as(row["Path"], item_id_of(row), taken)
            taken.add(name_key(name))
            hashed = _digest(row)
            found.append({
                "path": primary["Path"], "name": row["Name"],
                "item_id": item_id_of(row), "stored_as": name,
                "size": row["Size"],
                "quickxor": base64.b64encode(
                    bytes.fromhex(hashed)).decode() if hashed else None,
                "integrity": "not_fetched", "error": None,
                "_digest": hashed,
            })
    return found


def keep_duplicates(
    cfg: dict[str, Any], runner: Callable[..., str], drive_id: str,
    target: Path, scan: tuple[list[dict[str, Any]], list[dict[str, Any]],
                              str | None], *, dry_run: bool,
) -> dict[str, Any]:
    """Store the extras of every collision group and build the record fields.

    Args:
        cfg: Validated backup configuration.
        runner: Command runner of the backup module (run_command).
        drive_id: Graph drive identifier of the library.
        target: Mirror directory of the library (already synced).
        scan: File rows, directory rows and scan error of the library.
        dry_run: When true nothing is fetched or written.

    Returns:
        ``duplicates``, ``duplicate_summary`` and ``errors`` (the codes found,
        in the order of the contract) of the library.
    """
    files, dirs, failure = scan
    errors: list[str] = [failure] if failure else []
    for row in files:
        if is_reserved(row["Name"]):
            LOG.error("Reserved name not synced: %s item_id=%s",
                      row["Path"], item_id_of(row))
            errors.append(NAME_RESERVED)
    if duplicate_directories(dirs):
        LOG.error("Duplicate directories are not supported; nothing merged")
        errors.append(DIRECTORY_UNSUPPORTED)
    groups = collision_groups(files)
    taken = {name_key(row["Path"]) for row in files + dirs}
    extras = _extras(groups, target, cfg, runner, taken)
    fetcher = ContentFetcher(cfg, drive_id)
    for extra in ([] if dry_run else extras):
        _store(cfg, runner, fetcher, target, extra)
        if extra["error"]:
            errors.append(extra["error"])
            LOG.error("Duplicate %s item_id=%s stored_as=%s: %s",
                      extra["path"], extra["item_id"], extra["stored_as"],
                      extra["error"])
        else:
            LOG.warning("Duplicate kept: path=%s item_id=%s stored_as=%s",
                        extra["path"], extra["item_id"], extra["stored_as"])
    current = {extra["stored_as"] for extra in extras}
    stored = [
        p.relative_to(target).as_posix() for p in target.rglob("*")
        if p.is_file() and is_reserved(p.name)
    ] if target.is_dir() else []
    for extra in extras:
        extra.pop("_digest")
    return {
        "duplicates": extras,
        "duplicate_summary": {
            "groups": len(groups),
            "kept": sum(1 for e in extras
                        if e["integrity"] in ("ok", "hash_unavailable")),
            "failed": sum(1 for e in extras if e["error"]),
            "stale": sum(1 for name in stored if name not in current),
        },
        "errors": sorted(set(errors), key=ERROR_ORDER.index),
    }
