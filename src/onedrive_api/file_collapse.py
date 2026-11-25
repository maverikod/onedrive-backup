"""Collapsed and ordered reads of the file name index (matrix 10.22.2.2, 10.22.2.4, RD5, RD8).

Collapse 'none' is a row per snapshot and file object; 'version' is one row per distinct (library, folder, name, copy_index,
size, mtime), shown from the newest snapshot that holds it; 'file' is the newest version of every (library, folder, name,
copy_index). A common table expression c holds the rows of the chosen collapse, so one query shape serves the page, the
total and the counts of the folder tree.
"""

from __future__ import annotations

from typing import Any

from .file_index import FileIndex, folder_clause
from .name_match import Pattern

COLUMNS = (
    "f.snapshot_id AS snapshot_id, f.dir AS dir, f.name AS name, f.name_key AS name_key, f.stored AS stored, "
    "f.size AS size, f.mtime AS mtime, f.copy_index AS copy_index, s.site_key AS site_key, s.drive_key AS drive_key, "
    's.time_utc AS time_utc, s.backup_type AS backup_type, s."trigger" AS "trigger", s.run_id AS run_id'
)
JOIN = " FROM file f JOIN snapshot s ON s.snapshot_id = f.snapshot_id WHERE "
VERSION_KEY = "s.site_key, s.drive_key, f.dir, f.name, f.copy_index, f.size, f.mtime"
FILE_KEY = "site_key, drive_key, dir, name, copy_index"
VERSION_ORDER = "s.time_utc DESC, f.snapshot_id"
OUTPUT = (
    "snapshot_id, dir, name, name_key, stored, size, mtime, copy_index, site_key, drive_key, time_utc, backup_type, "
    '"trigger", run_id'
)
ORDERS = {
    "name": "name_key, time_utc DESC, {rank}, dir, copy_index, snapshot_id",
    "snapshot_time": "time_utc DESC, name_key, dir, copy_index, snapshot_id",
    "mtime": "mtime DESC, name_key, dir, copy_index, snapshot_id",
    "size": "size DESC, name_key, dir, copy_index, snapshot_id",
}


def collapsed(where: str, mode: str) -> str:
    """Build the WITH clause that defines c, the rows of one collapse.

    Args:
        where: The WHERE clause over f and s, without the keyword.
        mode: none, version or file.

    Returns:
        SQL text ending with the definition of c: the columns of the row plus snapshot_count, first_time, last_time and
        version_count.
    """
    if mode == "none":
        extra = "1 AS snapshot_count, s.time_utc AS first_time, s.time_utc AS last_time, 1 AS version_count"
        return "WITH c AS (SELECT " + COLUMNS + ", " + extra + JOIN + where + ")"
    over = "OVER (PARTITION BY " + VERSION_KEY + ")"
    inner = (
        "SELECT " + COLUMNS + ", ROW_NUMBER() OVER (PARTITION BY " + VERSION_KEY + " ORDER BY " + VERSION_ORDER + ") AS rn, "
        "COUNT(*) " + over + " AS snapshot_count, MIN(s.time_utc) " + over + " AS first_time, "
        "MAX(s.time_utc) " + over + " AS last_time" + JOIN + where
    )
    if mode == "version":
        return "WITH v AS (" + inner + "), c AS (SELECT *, 1 AS version_count FROM v WHERE rn = 1)"
    group = "OVER (PARTITION BY " + FILE_KEY + ")"
    middle = (
        "SELECT *, ROW_NUMBER() OVER (PARTITION BY " + FILE_KEY + " ORDER BY time_utc DESC, snapshot_id) AS rn2, "
        "COUNT(*) " + group + " AS version_count, SUM(snapshot_count) " + group + " AS total_count, "
        "MIN(first_time) " + group + " AS min_time, MAX(last_time) " + group + " AS max_time FROM v WHERE rn = 1"
    )
    final = (
        "SELECT " + OUTPUT + ", total_count AS snapshot_count, min_time AS first_time, max_time AS last_time, "
        "version_count FROM w WHERE rn2 = 1"
    )
    return "WITH v AS (" + inner + "), w AS (" + middle + "), c AS (" + final + ")"


def search_rows(
    index: FileIndex, snapshot_ids: list[str], pattern: Pattern, site_order: list[str], limit: int, offset: int,
    folder: tuple[str, bool] | None, collapse: str, order_by: str,
) -> tuple[int, list[dict[str, Any]]]:
    """Return one page of the collapsed rows of the chosen snapshots whose name matches.

    Args:
        index: The name index.
        snapshot_ids: The chosen snapshots; an empty list gives an empty result.
        pattern: The parsed name part.
        site_order: Site keys in the order of their labels, the tie-break after the date for order_by name.
        limit: Page size.
        offset: Rows to skip.
        folder: None for every folder, else (folder, recursive).
        collapse: none, version or file.
        order_by: name, snapshot_time, mtime or size.

    Returns:
        The total of collapsed rows and the page; every row has the index columns, snapshot_count, first_time, last_time
        and version_count.
    """
    if not snapshot_ids:
        return 0, []
    where, params = index._where(snapshot_ids, pattern)
    extra, values = folder_clause(folder)
    head = collapsed(where + extra, collapse)
    params = params + values
    cases = "".join("WHEN ? THEN %d " % number for number in range(len(site_order)))
    rank = "CASE site_key " + cases + "ELSE 100000 END" if site_order else "0"
    tail = list(site_order) if order_by == "name" and site_order else []
    conn = index.connect()
    try:
        total = conn.execute(head + " SELECT COUNT(*) FROM c", params).fetchone()[0]
        query = head + " SELECT * FROM c ORDER BY " + ORDERS[order_by].replace("{rank}", rank) + " LIMIT ? OFFSET ?"
        cursor = conn.execute(query, params + tail + [limit, offset])
        names = [item[0] for item in cursor.description]
        return int(total), [dict(zip(names, row)) for row in cursor.fetchall()]
    finally:
        conn.close()


def library_counts(
    index: FileIndex, snapshot_ids: list[str], pattern: Pattern, collapse: str
) -> dict[tuple[str, str], tuple[int, int]]:
    """Count the collapsed rows of every library of the chosen snapshots, all of them and the ones in the library root.

    Args:
        index: The name index.
        snapshot_ids: The chosen snapshots.
        pattern: The parsed name part.
        collapse: none, version or file.

    Returns:
        (site key, library key) to (rows, rows with an empty dir).
    """
    if not snapshot_ids:
        return {}
    where, params = index._where(snapshot_ids, pattern)
    query = collapsed(where, collapse)
    query += " SELECT site_key, drive_key, COUNT(*), SUM(dir = '') FROM c GROUP BY site_key, drive_key"
    conn = index.connect()
    try:
        found = conn.execute(query, params).fetchall()
    finally:
        conn.close()
    return {(str(row[0]), str(row[1])): (int(row[2]), int(row[3])) for row in found}


def folder_counts(
    index: FileIndex, snapshot_ids: list[str], pattern: Pattern, parent: str, collapse: str
) -> list[tuple[str, int, int]]:
    """Count the collapsed rows below a folder per child folder.

    Args:
        index: The name index.
        snapshot_ids: The chosen snapshots.
        pattern: The parsed name part.
        parent: The parent folder, '' for the library root.
        collapse: none, version or file.

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
    rest = "substr(dir, %d)" % (len(prefix) + 1)
    child = "substr(%s, 1, instr(%s || '/', '/') - 1)" % (rest, rest)
    query = collapsed(where, collapse)
    query += " SELECT %s AS child, COUNT(*), SUM(instr(%s, '/') = 0) FROM c GROUP BY child" % (child, rest)
    conn = index.connect()
    try:
        found = conn.execute(query, params).fetchall()
    finally:
        conn.close()
    return [(str(row[0]), int(row[1]), int(row[2])) for row in found]
