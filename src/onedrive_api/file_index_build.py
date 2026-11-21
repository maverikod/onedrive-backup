"""Filling of the file name index from restic (matrix 10.19.6, PL14).

A snapshot is indexed once, from `restic ls --json`, streamed into one transaction. The catch-up of the snapshots that are
not indexed yet runs in one background thread of the service, and once at the end of every backup cycle; both take the
same cross-process lock, so a snapshot is never listed twice at the same time. A failure never raises into the caller.
"""

from __future__ import annotations

from collections.abc import Callable, Iterator
import json
import logging
import sqlite3
import subprocess
import tempfile
import threading
import time
from typing import Any

from .catalog import Catalog, CatalogError
from .file_index import FileIndex, utc_time
from .name_match import key, split_stored

LOG = logging.getLogger(__name__)
COOLDOWN_SECONDS = 300
CopyRow = tuple[str, str, str, str, int, str]
_STATE: dict[str, Any] = {"thread": None, "failed_at": -1e9}


def _tag(tags: object, prefix: str) -> str:
    """Return the value of the first tag that starts with prefix.

    Args:
        tags: The restic tags of a snapshot.
        prefix: The tag prefix, for example site-.

    Returns:
        The rest of the tag, or the empty string.
    """
    for tag in tags if isinstance(tags, list) else []:
        if isinstance(tag, str) and tag.startswith(prefix):
            return tag[len(prefix):]
    return ""


def sharepoint_snapshots(catalog: Catalog) -> list[dict[str, Any]]:
    """List the SharePoint snapshots of the repository with their keys, oldest first.

    Args:
        catalog: The restic catalogue.

    Returns:
        Dicts with id, time (UTC, normalised), site_key and drive_key.

    Raises:
        CatalogError: Restic is not available or answered something that is not a snapshot list.
    """
    try:
        items = json.loads(catalog._run(["snapshots", "--json", "--tag", "sharepoint"]))
    except (ValueError, TypeError) as exc:
        raise CatalogError("Invalid restic snapshot JSON", 503) from exc
    if not isinstance(items, list):
        raise CatalogError("Invalid restic snapshot format", 503)
    found = []
    for item in items:
        if not isinstance(item, dict):
            continue
        site, drive = _tag(item.get("tags"), "site-"), _tag(item.get("tags"), "drive-")
        if site and drive and isinstance(item.get("id"), str):
            when = utc_time(str(item.get("time", "")))
            found.append({"id": str(item["id"]).lower(), "time": when, "site_key": site, "drive_key": drive})
    found.sort(key=lambda entry: entry["time"])
    return found


def _numbered(copies: list[CopyRow]) -> Iterator[tuple[Any, ...]]:
    """Number the stored copies of every name, in ascending order of their digits.

    Args:
        copies: Tuples (folder, shown name, digits, stored name, size, mtime).

    Returns:
        Index rows with copy_index 1, 2, ... inside each (folder, name key) group.
    """
    copies.sort(key=lambda row: (row[0], key(row[1]), row[2]))
    last: tuple[str, str] = ("", "")
    number = 0
    for folder, shown, _digits, stored, size, mtime in copies:
        group = (folder, key(shown))
        number = number + 1 if group == last else 1
        last = group
        yield (folder, shown, key(shown), stored, size, mtime, number)


def _rows(base: list[str], env: dict[str, str], snapshot_id: str, library: str) -> Iterator[tuple[Any, ...]]:
    """Stream the file rows of one snapshot from restic ls.

    Args:
        base: The restic command.
        env: The restic environment.
        snapshot_id: The snapshot.
        library: Absolute prefix of the library inside the snapshot, ending with a slash.

    Returns:
        An iterator of (dir, name, name key, stored name, size, mtime, copy_index); it raises CatalogError when restic fails.
    """
    copies: list[CopyRow] = []
    with tempfile.TemporaryFile() as errors:
        proc = subprocess.Popen(
            base + ["ls", "--json", snapshot_id], env=env, stdout=subprocess.PIPE, stderr=errors,
            text=True, encoding="utf-8", errors="replace",
        )
        try:
            assert proc.stdout is not None
            for line in proc.stdout:
                node = json.loads(line)
                full = node.get("path", "")
                if node.get("struct_type") != "node" or node.get("type") != "file" or not full.startswith(library):
                    continue
                folder, _, stored = full[len(library):].rpartition("/")
                shown, digits = split_stored(stored)
                size = node.get("size", 0)
                size = size if isinstance(size, int) else 0
                if digits:
                    copies.append((folder, shown, digits, stored, size, str(node.get("mtime", ""))))
                else:
                    yield (folder, shown, key(shown), stored, size, str(node.get("mtime", "")), 0)
            if proc.wait(timeout=120):
                errors.seek(0)
                raise CatalogError("Restic listing failed: " + errors.read(300).decode("utf-8", "replace"), 503)
        finally:
            if proc.poll() is None:
                proc.kill()
            proc.wait()
    yield from _numbered(copies)


def index_snapshot(catalog: Catalog, index: FileIndex, entry: dict[str, Any]) -> int:
    """Index one snapshot.

    Args:
        catalog: The restic catalogue.
        index: The name index.
        entry: One element of sharepoint_snapshots.

    Returns:
        The number of files indexed, 0 when it was already indexed.
    """
    base, env, cfg = catalog._base()
    library = cfg["mirror_dir"].as_posix().rstrip("/") + "/sharepoint/%s/%s/" % (entry["site_key"], entry["drive_key"])
    rows = _rows(base, env, entry["id"], library)
    return index.add_snapshot(entry["id"], entry["time"], entry["site_key"], entry["drive_key"], rows)


def index_pending(catalog: Catalog, index: FileIndex) -> tuple[int, int]:
    """Index every snapshot that is not indexed yet, oldest first, one at a time.

    Args:
        catalog: The restic catalogue.
        index: The name index.

    Returns:
        The number of snapshots indexed and the number that failed; (0, 0) when another builder holds the lock.
        Restic being unavailable is a failure that is logged and counted, never raised.
    """
    try:
        wanted = sharepoint_snapshots(catalog)
        with index.lock() as held:
            if not held:
                return 0, 0
            known = {row["snapshot_id"] for row in index.snapshots()}
            done = failed = 0
            for entry in [item for item in wanted if item["id"] not in known]:
                try:
                    index_snapshot(catalog, index, entry)
                    done += 1
                except (CatalogError, OSError, ValueError, sqlite3.Error) as exc:
                    failed += 1
                    LOG.error("File index: snapshot %s was not indexed: %s", entry["id"][:8], exc)
            return done, failed
    except (CatalogError, OSError, sqlite3.Error) as exc:
        LOG.error("File index: the catch-up could not run: %s", exc)
        return 0, 1


def ensure_catchup(make_catalog: Callable[[], Catalog], index: FileIndex) -> bool:
    """Start the background catch-up thread unless one runs or a failure is younger than five minutes.

    Args:
        make_catalog: Factory of the catalogue (built inside the thread).
        index: The name index.

    Returns:
        True when a thread was started.
    """
    thread = _STATE["thread"]
    if (thread is not None and thread.is_alive()) or time.monotonic() - _STATE["failed_at"] < COOLDOWN_SECONDS:
        return False

    def work() -> None:
        """Run one catch-up and remember a failure."""
        try:
            _done, failed = index_pending(make_catalog(), index)
            if failed:
                _STATE["failed_at"] = time.monotonic()
        except Exception:  # noqa: BLE001 - a derived index must never take the service down
            LOG.exception("File index: the catch-up thread failed")
            _STATE["failed_at"] = time.monotonic()

    _STATE["thread"] = threading.Thread(target=work, name="file-index-catchup", daemon=True)
    _STATE["thread"].start()
    return True
