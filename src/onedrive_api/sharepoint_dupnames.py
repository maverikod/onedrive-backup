"""Collision detection and naming of the duplicate copies of a document library.

Two files of one library collide when they share a parent folder and their
names are equal after Unicode NFC normalisation and case folding (rclone then
mirrors one of them and ignores the rest). Every further member of such a group
is kept under a deterministic name, ``<stem>.dup-<h><ext>``. This module holds
the pure rules; it performs no I/O except reading the mirror folder of a group.
"""

from __future__ import annotations

import fnmatch
import hashlib
import json
import unicodedata
from pathlib import Path
from typing import Any, Callable

from onedrive_backup import BackupError

SCAN_FAILED = "DUPLICATE_SCAN_FAILED"
NAME_RESERVED = "DUPLICATE_NAME_RESERVED"
DIRECTORY_UNSUPPORTED = "DUPLICATE_DIRECTORY_UNSUPPORTED"
FETCH_FAILED = "DUPLICATE_FETCH_FAILED"
INTEGRITY_MISMATCH = "DUPLICATE_INTEGRITY_MISMATCH"
ERROR_ORDER = (
    SCAN_FAILED, NAME_RESERVED, DIRECTORY_UNSUPPORTED, FETCH_FAILED,
    INTEGRITY_MISMATCH,
)

# An rclone glob and the matching Python glob: a name that carries ".dup-" and
# eight lowercase hex digits looks like a stored copy. The sync leaves such
# names alone (it never deletes a stored copy), so a real source object of that
# name is not synced and is reported instead (DUPLICATE_NAME_RESERVED).
EXCLUDE_PATTERN = "*.dup-" + "[0-9a-f]" * 8 + "*"


def name_key(name: str) -> str:
    """Return the collision key of a name: NFC normalisation, then case folding.

    Args:
        name: File or folder name, or a whole path.

    Returns:
        The comparison key.
    """
    return unicodedata.normalize("NFC", name).casefold()


def is_reserved(name: str) -> bool:
    """Tell whether a name looks like a stored copy of this service.

    Args:
        name: Base name of a source object or a mirror file.

    Returns:
        True when the name matches the exclude pattern of the sync.
    """
    return fnmatch.fnmatchcase(name, EXCLUDE_PATTERN)


def item_id_of(row: dict[str, Any]) -> str:
    """Return the Graph item id of a listing row (rclone ID is drive#item).

    Args:
        row: Validated listing row.

    Returns:
        The part of the rclone ID after the last "#".
    """
    return str(row["ID"]).rpartition("#")[2]


def stored_as(
    path: str, item_id: str, taken: set[str]
) -> str:
    """Return the mirror-relative stored name of an extra copy.

    The digits come from sha256 of the item id; when the name already exists
    under name_key, four more digits of the same digest are taken.

    Args:
        path: Mirror-relative path of the extra as the source lists it.
        item_id: Graph item id of the extra.
        taken: name_key values of every path that is already in use.

    Returns:
        The path ``<folder>/<stem>.dup-<h><ext>``.
    """
    folder, _, name = path.rpartition("/")
    stem, dot, ext = name.rpartition(".")
    if not dot:
        stem, ext = name, ""
    digest = hashlib.sha256(item_id.encode("utf-8")).hexdigest()
    prefix = folder + "/" if folder else ""
    for digits in range(8, len(digest) + 1, 4):
        suffix = (dot + ext) if dot else ""
        candidate = prefix + stem + ".dup-" + digest[:digits] + suffix
        if name_key(candidate) not in taken:
            return candidate
    raise BackupError("DUPLICATE_NAME_EXHAUSTED")


def parse_listing(
    text: str
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Split an rclone recursive listing into files and directories.

    Args:
        text: Output of ``rclone lsjson -R --hash`` of the library.

    Returns:
        The file rows and the directory rows. Raises ValueError for a
        malformed listing.
    """
    rows = json.loads(text)
    if not isinstance(rows, list):
        raise ValueError("listing is not a list")
    files: list[dict[str, Any]] = []
    dirs: list[dict[str, Any]] = []
    for row in rows:
        if not isinstance(row, dict):
            raise ValueError("listing row is not an object")
        if not isinstance(row.get("Path"), str):
            raise ValueError("listing row without Path")
        if not isinstance(row.get("Name"), str):
            raise ValueError("listing row without Name")
        if row.get("IsDir") is True:
            dirs.append(row)
            continue
        if not isinstance(row.get("ID"), str) or not isinstance(
            row.get("Size"), int
        ):
            raise ValueError("file row without ID or Size")
        files.append(row)
    return files, dirs


def scan_library(
    runner: Callable[..., str], base: list[str]
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], str | None]:
    """Read the whole library listing once, read-only.

    Args:
        runner: Command runner of the backup module (run_command).
        base: rclone arguments that select the library.

    Returns:
        File rows, directory rows and an error code (None on success).
        A failed or malformed scan gives empty rows and DUPLICATE_SCAN_FAILED.
    """
    command = base + [
        "lsjson", "-R", "--hash", "--no-mimetype", "onedrive:"
    ]
    try:
        return (*parse_listing(runner(command, capture=True)), None)
    except (BackupError, ValueError):
        return [], [], SCAN_FAILED


def collision_groups(
    files: list[dict[str, Any]]
) -> list[list[dict[str, Any]]]:
    """Group the files that collide on the mirror path.

    Reserved names are never part of a group (they are not synced).

    Args:
        files: File rows of the scan.

    Returns:
        Groups of two or more rows in a stable order (folder, key).
    """
    found: dict[tuple[str, str], list[dict[str, Any]]] = {}
    for row in files:
        if is_reserved(row["Name"]):
            continue
        folder = row["Path"].rpartition("/")[0]
        found.setdefault((folder, name_key(row["Name"])), []).append(row)
    return [found[key] for key in sorted(found) if len(found[key]) > 1]


def duplicate_directories(dirs: list[dict[str, Any]]) -> bool:
    """Tell whether two directories share one collision key.

    Args:
        dirs: Directory rows of the scan.

    Returns:
        True when at least two directories collide.
    """
    seen: set[str] = set()
    for row in dirs:
        key = name_key(row["Path"])
        if key in seen:
            return True
        seen.add(key)
    return False


def plain_file(target: Path, group: list[dict[str, Any]]) -> Path | None:
    """Find the file rclone mirrored for a group.

    Args:
        target: Mirror directory of the library.
        group: Colliding rows of one folder.

    Returns:
        The mirrored file, or None when the mirror holds none yet.
    """
    first = group[0]
    folder = target / first["Path"].rpartition("/")[0]
    key = name_key(first["Name"])
    if not folder.is_dir():
        return None
    for child in sorted(folder.iterdir()):
        if child.is_file() and name_key(child.name) == key:
            return child
    return None


def pick_primary(
    group: list[dict[str, Any]], size: int | None, digest: str | None
) -> dict[str, Any]:
    """Choose the member whose bytes rclone mirrored at the plain path.

    The member whose size and quickXorHash equal the mirrored file is the
    primary; when none or several match, the smallest Graph item id is.

    Args:
        group: Colliding rows of one folder.
        size: Size of the mirrored file, None when it does not exist.
        digest: Lowercase hex quickXorHash of the mirrored file or None.

    Returns:
        The primary row.
    """
    if size is not None and digest is not None:
        matches = [
            row for row in group
            if row["Size"] == size
            and (row.get("Hashes") or {}).get("quickxor") == digest
        ]
        if len(matches) == 1:
            return matches[0]
    return min(group, key=item_id_of)
