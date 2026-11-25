"""File addresses of backup_prepare_download (matrix 10.22.4.1): file_id, snapshot_id + file_path, or names.

FORM A is the file_id alone, FORM B is snapshot_id + file_path, FORM C is snapshot_id + site_id + drive_id + dir + name
[+ copy_index]; snapshot_id alone is the archive form. A file_id is <first 8 hex of the snapshot id>.<first 24 hex of
sha256(snapshot id + LF + file path)> (RM3) and is resolved by hashing the rows of one indexed snapshot.
"""

from __future__ import annotations

import hashlib
import re
from typing import Any

from .catalog import NOT_FOUND_HINT, CatalogError
from .file_index import FileIndex
from .folder_tree import digest, drive_keys
from .sharepoint_base import DiscoveryError

FILE_ID_RE = re.compile(r"^[0-9a-f]{8}[.][0-9a-f]{24}$")
FILE_ID_EXPECTED = "^[0-9a-f]{8}[.][0-9a-f]{24}$"
ID_RE = re.compile(r"^[A-Za-z0-9_,.!@-]{1,300}$")
FORM_NAMES = ("file_id", "snapshot_id+file_path", "snapshot_id+site_id+drive_id+dir+name[+copy_index]")
NAME_FIELDS = ("site_id", "drive_id", "dir", "name")
OTHERS = ("snapshot_id", "file_path", "site_id", "drive_id", "dir", "name", "copy_index")
ADDRESS_HINT = (
    "Give exactly one address: file_id alone; snapshot_id and file_path; snapshot_id with site_id, drive_id, dir and "
    "name (copy_index optional); or snapshot_id alone for the whole snapshot archive."
)


def make_file_id(snapshot_id: str, file_path: str) -> str:
    """Return the file id of a file of a snapshot (RM3).

    Args:
        snapshot_id: The full lowercase snapshot id.
        file_path: The file_path of the file in the snapshot.

    Returns:
        The 33-character id.
    """
    text = ("%s\n%s" % (snapshot_id, file_path)).encode("utf-8")
    return "%s.%s" % (snapshot_id[:8], hashlib.sha256(text).hexdigest()[:24])


def invalid(code: str, field: str, value: Any, expected: str, hint: str) -> DiscoveryError:
    """Build a 400 error carrying error.data {field, value, expected, hint} (RM6).

    Args:
        code: The code word, which is the error message.
        field: The offending parameter.
        value: Its value, cut to 64 characters.
        expected: What the parameter must be.
        hint: What to do next.

    Returns:
        The error to raise.
    """
    shown = value if isinstance(value, (int, float)) or value is None else str(value)[:64]
    return DiscoveryError(code, 400, {"field": field, "value": shown, "expected": expected, "hint": hint})


def check_address(params: dict[str, Any]) -> str:
    """Check the address parameters of one call and name its form.

    Args:
        params: file_id, snapshot_id, file_path, site_id, drive_id, dir, name and copy_index; None means omitted.

    Returns:
        A, B, C or archive.

    Raises:
        DiscoveryError: INVALID_FILE_ADDRESS, INVALID_FILE_ID, INVALID_FILE_NAME, INVALID_SITE_ID, INVALID_DRIVE_ID or
            INVALID_DIR (400).
    """
    got = sorted(key for key, value in params.items() if value is not None and key in OTHERS + ("file_id",))
    bad = DiscoveryError("INVALID_FILE_ADDRESS", 400, {"forms": list(FORM_NAMES), "got": got, "hint": ADDRESS_HINT})
    names = [key for key in NAME_FIELDS if params.get(key) is not None]
    if params.get("file_id") is not None:
        if any(params.get(key) is not None for key in OTHERS):
            raise bad
        if not isinstance(params["file_id"], str) or not FILE_ID_RE.fullmatch(params["file_id"]):
            raise invalid("INVALID_FILE_ID", "file_id", params["file_id"], FILE_ID_EXPECTED, NOT_FOUND_HINT)
        return "A"
    if params.get("file_path") is not None and (names or params.get("copy_index") is not None):
        raise bad
    if names or params.get("copy_index") is not None:
        if len(names) != len(NAME_FIELDS):
            raise bad
        _check_names(params)
        return "C"
    return "B" if params.get("file_path") is not None else "archive"


def _check_names(params: dict[str, Any]) -> None:
    """Check the values of a FORM C address.

    Args:
        params: The address parameters.

    Returns:
        None.

    Raises:
        DiscoveryError: INVALID_SITE_ID, INVALID_DRIVE_ID, INVALID_DIR or INVALID_FILE_NAME (400).
    """
    for field, code in (("site_id", "INVALID_SITE_ID"), ("drive_id", "INVALID_DRIVE_ID")):
        if not isinstance(params[field], str) or not ID_RE.fullmatch(params[field]):
            raise invalid(code, field, params[field], "1..300 characters of A-Z a-z 0-9 _ , . ! @ -", ADDRESS_HINT)
    where = params["dir"]
    parts = where.split("/") if where else []
    if not isinstance(where, str) or len(where) > 1024 or "\\" in where or any(p in ("", ".", "..") for p in parts):
        raise invalid("INVALID_DIR", "dir", where, "'' for the library root or folders joined by '/'", ADDRESS_HINT)
    name = params["name"]
    ok = isinstance(name, str) and 1 <= len(name) <= 255 and "/" not in name and name not in (".", "..")
    if not ok or any(ord(c) < 32 or ord(c) == 127 for c in name):
        raise invalid("INVALID_FILE_NAME", "name", name, "1..255 characters, no '/', no control characters", ADDRESS_HINT)


def not_found(text: str, details: dict[str, Any] | None = None) -> CatalogError:
    """Build a 404 whose error.data carries the search hint (RM4).

    Args:
        text: The unchanged message.
        details: More fields of error.data, or None.

    Returns:
        The error to raise.
    """
    return CatalogError(text, 404, {**(details or {}), "hint": NOT_FOUND_HINT})


def full_snapshot_id(index: FileIndex, snapshot_id: str) -> str | None:
    """Return the full id of an indexed snapshot named by its id or a prefix of it.

    Args:
        index: The file name index.
        snapshot_id: A lowercase hex snapshot id or prefix.

    Returns:
        The 64-hex id, or None when no single indexed snapshot has it.
    """
    if len(snapshot_id) == 64:
        return snapshot_id
    found = [row["snapshot_id"] for row in index.snapshots() if row["snapshot_id"].startswith(snapshot_id)]
    return found[0] if len(found) == 1 else None


def resolve_file_id(index: FileIndex, file_id: str) -> tuple[str, str, int]:
    """Find the file a file_id names by hashing the rows of the indexed snapshots with its prefix.

    Args:
        index: The file name index.
        file_id: A well-formed file id.

    Returns:
        The snapshot id, the file_path and the size of the file.

    Raises:
        CatalogError: 404 when no indexed snapshot has the prefix or none of its files hashes to the id.
    """
    conn = index.connect()
    try:
        query = "SELECT snapshot_id, site_key, drive_key FROM snapshot WHERE snapshot_id LIKE ?"
        for snapshot, site, drive in conn.execute(query, (file_id[:8] + "%",)).fetchall():
            lead = "sharepoint/%s/%s/" % (site, drive)
            base = hashlib.sha256((snapshot + "\n" + lead).encode("utf-8"))
            for where, stored, size in conn.execute("SELECT dir, stored, size FROM file WHERE snapshot_id = ?", (snapshot,)):
                tail = (where + "/" if where else "") + stored
                digest_ = base.copy()
                digest_.update(tail.encode("utf-8"))
                if digest_.hexdigest()[:24] == file_id[9:]:
                    return snapshot, lead + tail, int(size)
    finally:
        conn.close()
    raise not_found("File not found in snapshot", {"field": "file_id", "value": file_id})


def resolve_names(index: FileIndex, params: dict[str, Any]) -> tuple[str, str, int]:
    """Find the file of a FORM C address in the index.

    Args:
        index: The file name index.
        params: snapshot_id, site_id, drive_id, dir, name and copy_index (None means 0).

    Returns:
        The full snapshot id, the file_path and the size of the file.

    Raises:
        CatalogError: 404 when the snapshot, the library or the file is not indexed.
    """
    snapshot, copy = str(params["snapshot_id"]).lower(), params.get("copy_index") or 0
    checked = {"dir": params["dir"], "name": params["name"], "copy_index": copy}
    conn = index.connect()
    try:
        query = "SELECT snapshot_id, site_key, drive_key FROM snapshot WHERE snapshot_id LIKE ?"
        for found, site, drive in conn.execute(query, (snapshot + "%",)).fetchall():
            if site != digest(params["site_id"]) or drive not in drive_keys(params["drive_id"]):
                continue
            sql = "SELECT stored, size FROM file WHERE snapshot_id = ? AND dir = ? AND name = ? AND copy_index = ?"
            row = conn.execute(sql, (found, params["dir"], params["name"], copy)).fetchone()
            if row is not None:
                lead = "sharepoint/%s/%s/" % (site, drive)
                return found, lead + (params["dir"] + "/" if params["dir"] else "") + row[0], int(row[1])
    finally:
        conn.close()
    raise not_found("File not found in snapshot", {"checked": checked})
