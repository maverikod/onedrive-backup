"""Folder scope of the filter commands and the folder tree of backup_folder_children (matrix 10.21.2 to 10.21.5).

The tree has three levels, site -> library -> folders; the folders come from the dir column of the file name index, so no
folder is stored anywhere: children and counts are computed at query time from the rows of the chosen snapshots.
"""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import re
from typing import Any

from .file_index import FileIndex
from .name_match import Pattern, key
from .sharepoint_base import IDENTIFIER, DiscoveryError

HEX64 = re.compile(r"^[0-9a-f]{64}$")
CONTROL = re.compile(r"[\x00-\x1f\x7f]")
MAX_SEGMENTS = 64
MAX_SEGMENT = 255
MAX_DIR = 1024


def digest(value: str) -> str:
    """Return the stable key of an id, as the backup writes it into the snapshot tags.

    Args:
        value: A Graph site or drive id.

    Returns:
        The lowercase hex SHA-256 of the id.
    """
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def drive_keys(drive_id: str) -> set[str]:
    """Return the library keys an address can mean: the key of the id, or the id itself when it is a 64-hex drive key.

    Args:
        drive_id: The drive_id parameter.

    Returns:
        The candidate keys.
    """
    keys = {digest(drive_id)}
    if HEX64.fullmatch(drive_id):
        keys.add(drive_id)
    return keys


def check_dir(value: object) -> str:
    """Validate a folder address: '' is the library root, else segments joined by a slash.

    Args:
        value: The dir parameter.

    Returns:
        The folder.

    Raises:
        DiscoveryError: INVALID_DIR (400) for a malformed folder.
    """
    if not isinstance(value, str):
        raise DiscoveryError("INVALID_DIR", 400)
    if value == "":
        return value
    parts = value.split("/")
    bad = len(value) > MAX_DIR or len(parts) > MAX_SEGMENTS or bool(CONTROL.search(value))
    if bad or any(part in ("", ".", "..") or len(part) > MAX_SEGMENT for part in parts):
        raise DiscoveryError("INVALID_DIR", 400)
    return value


def _identifier(value: object, code: str) -> str:
    """Validate a site or drive id.

    Args:
        value: The parameter value.
        code: The error code of the parameter.

    Returns:
        The id.

    Raises:
        DiscoveryError: The code (400) for a malformed id.
    """
    if not isinstance(value, str) or not IDENTIFIER.fullmatch(value):
        raise DiscoveryError(code, 400)
    return value


@dataclass(frozen=True)
class Scope:
    """The folder scope of a request: a site, a library of it, a folder of the library.

    Attributes:
        site_id: The site or None.
        drive_id: The library or None.
        folder: The folder ('' is the library root) or None.
        recursive: The recursive flag or None.
    """

    site_id: str | None = None
    drive_id: str | None = None
    folder: str | None = None
    recursive: bool | None = None

    def rows(self) -> tuple[str, bool] | None:
        """Return the folder restriction of the rows: the folder and whether the whole subtree counts.

        Returns:
            None when no library is addressed, else (folder, recursive).
        """
        if self.drive_id is None:
            return None
        return (self.folder or "", bool(self.recursive))


def parse_scope(site_id: object, drive_id: object, folder: object, recursive: object) -> Scope:
    """Validate the scope parameters: the chain first (RT1, RT2), then every value.

    Args:
        site_id: The site id or None.
        drive_id: The library id or None.
        folder: The dir parameter or None.
        recursive: The recursive parameter or None.

    Returns:
        The scope.

    Raises:
        DiscoveryError: INVALID_FOLDER_SCOPE with the missing fields in details, then INVALID_SITE_ID, INVALID_DRIVE_ID or
            INVALID_DIR (all 400).
    """
    fields: list[str] = []
    if (folder is not None or recursive is not None) and drive_id is None:
        fields.append("drive_id")
    if (drive_id is not None or fields) and site_id is None:
        fields.append("site_id")
    if fields:
        raise DiscoveryError("INVALID_FOLDER_SCOPE", 400, {"fields": sorted(fields)})
    site = None if site_id is None else _identifier(site_id, "INVALID_SITE_ID")
    drive = None if drive_id is None else _identifier(drive_id, "INVALID_DRIVE_ID")
    where = None if folder is None else check_dir(folder)
    return Scope(site, drive, where, None if recursive is None else bool(recursive))


def _node(kind: str, site: str, drive: str, folder: str, name: str, rows: int, direct: int) -> dict[str, Any]:
    """Build one tree node.

    Args:
        kind: site, library or folder.
        site: The site id.
        drive: The library id, '' for a site.
        folder: The folder address, '' for a site or a library.
        name: The label.
        rows: File rows of the whole subtree.
        direct: File rows directly in the node.

    Returns:
        The node of the result.
    """
    return {
        "kind": kind, "site_id": site, "drive_id": drive, "dir": folder, "name": name,
        "file_count": rows, "direct_count": direct, "has_children": rows > direct,
    }


def _entry(kind: str, name: str, site: str, drive: str, folder: str) -> dict[str, str]:
    """Build one entry of the path chain.

    Args:
        kind: site, library or folder.
        name: The label.
        site: The site id.
        drive: The library id, '' for a site.
        folder: The folder address.

    Returns:
        The entry.
    """
    return {"kind": kind, "name": name, "site_id": site, "drive_id": drive, "dir": folder}


def path_chain(scope: Scope, site_name: str, library_name: str) -> list[dict[str, str]]:
    """Return the chain site -> library -> folders down to the addressed parent inclusive.

    Args:
        scope: The address.
        site_name: The label of the site, '' when unknown.
        library_name: The label of the library, '' when unknown.

    Returns:
        The entries, [] for the root call.
    """
    if scope.site_id is None:
        return []
    chain = [_entry("site", site_name or scope.site_id, scope.site_id, "", "")]
    if scope.drive_id is None:
        return chain
    chain.append(_entry("library", library_name or scope.drive_id, scope.site_id, scope.drive_id, ""))
    parts = scope.folder.split("/") if scope.folder else []
    for number, part in enumerate(parts):
        chain.append(_entry("folder", part, scope.site_id, scope.drive_id, "/".join(parts[: number + 1])))
    return chain


def snapshot_counts(index: FileIndex, snapshot_ids: list[str], pattern: Pattern) -> dict[str, tuple[int, int]]:
    """Count the matching rows of every chosen snapshot, all of them and the ones in the library root.

    Args:
        index: The name index.
        snapshot_ids: The chosen snapshots.
        pattern: The parsed name part.

    Returns:
        Snapshot id to (rows, rows with an empty dir); a snapshot without a match is absent.
    """
    if not snapshot_ids:
        return {}
    where, params = index._where(snapshot_ids, pattern)
    query = "SELECT f.snapshot_id, COUNT(*), SUM(f.dir = '') FROM file f WHERE " + where + " GROUP BY f.snapshot_id"
    conn = index.connect()
    try:
        return {row[0]: (int(row[1]), int(row[2])) for row in conn.execute(query, params).fetchall()}
    finally:
        conn.close()


def folder_counts(index: FileIndex, snapshot_ids: list[str], pattern: Pattern, parent: str) -> list[tuple[str, int, int]]:
    """Count the matching rows below a folder per child folder, from the dir column (no folder is stored).

    Args:
        index: The name index.
        snapshot_ids: The chosen snapshots.
        pattern: The parsed name part.
        parent: The parent folder, '' for the library root.

    Returns:
        Tuples (child name, rows in its whole subtree, rows directly in it); only children with at least one row.
    """
    if not snapshot_ids:
        return []
    where, params = index._where(snapshot_ids, pattern)
    prefix = parent + "/" if parent else ""
    if parent:
        where += " AND f.dir >= ? AND f.dir < ?"
        params += [prefix, parent + "0"]
    else:
        where += " AND f.dir <> ''"
    rest = "substr(f.dir, %d)" % (len(prefix) + 1)
    child = "substr(%s, 1, instr(%s || '/', '/') - 1)" % (rest, rest)
    query = "SELECT %s AS child, COUNT(*), SUM(instr(%s, '/') = 0) FROM file f WHERE " % (child, rest)
    conn = index.connect()
    try:
        found = conn.execute(query + where + " GROUP BY child", params).fetchall()
    finally:
        conn.close()
    return [(str(row[0]), int(row[1]), int(row[2])) for row in found]


def build_children(
    index: FileIndex, chosen: list[dict[str, Any]], pattern: Pattern, scope: Scope,
    names: dict[str, tuple[str, str]], libraries: dict[tuple[str, str], tuple[str, str]],
) -> list[dict[str, Any]]:
    """Compute the children of the addressed parent over the chosen snapshots, pruned to file_count >= 1, sorted.

    Args:
        index: The name index.
        chosen: The index rows of the snapshots that pass the site, date and scope filters.
        pattern: The parsed name part.
        scope: The address of the parent.
        names: Site key to (site id, label).
        libraries: (site key, library key) to (drive id, label); the key itself stands in for a library the inventory lacks.

    Returns:
        The nodes ordered by key(name), then name.
    """
    ids = [row["snapshot_id"] for row in chosen]
    nodes: list[dict[str, Any]] = []
    if scope.drive_id is not None:
        parent = scope.folder or ""
        for child, rows, direct in folder_counts(index, ids, pattern, parent):
            where = parent + "/" + child if parent else child
            nodes.append(_node("folder", scope.site_id or "", scope.drive_id, where, child, rows, direct))
    else:
        counts = snapshot_counts(index, ids, pattern)
        per: dict[tuple[str, str], list[int]] = {}
        for row in chosen:
            rows, root = counts.get(row["snapshot_id"], (0, 0))
            sums = per.setdefault((row["site_key"], row["drive_key"]), [0, 0])
            sums[0] += rows
            sums[1] += root
        if scope.site_id is None:
            totals: dict[str, int] = {}
            for (site_key, _drive), sums in per.items():
                totals[site_key] = totals.get(site_key, 0) + sums[0]
            nodes = [_node("site", names[k][0], "", "", names[k][1], n, 0) for k, n in totals.items() if k in names and n > 0]
        else:
            for pair, sums in per.items():
                drive, label = libraries.get(pair, (pair[1], pair[1]))
                if sums[0] > 0:
                    nodes.append(_node("library", scope.site_id, drive, "", label or pair[1], sums[0], sums[1]))
    nodes.sort(key=lambda item: (key(item["name"]), item["name"]))
    return nodes
