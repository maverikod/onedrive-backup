"""Persistent per-snapshot file name index (matrix 10.19.6): a SQLite file inside the service data directory.

The index is derived data: it is filled from restic, rebuildable at any time and never the source of truth. A snapshot is
immutable, so it is indexed exactly once, in one transaction, and never updated.
"""

from __future__ import annotations

from collections.abc import Iterable
import contextlib
from datetime import datetime, timedelta, timezone
import fcntl
import os
from pathlib import Path
import re
import sqlite3
from typing import Any, Iterator

from .name_match import Pattern

INDEX_DIR = "file-index"
INDEX_FILE = "index.sqlite3"
TIME = re.compile(r"^(\d{4})-(\d\d)-(\d\d)T(\d\d):(\d\d):(\d\d)(?:\.(\d+))?(Z|[+-]\d\d:\d\d)$")
SCHEMA = (
    "CREATE TABLE IF NOT EXISTS snapshot (snapshot_id TEXT PRIMARY KEY, time_utc TEXT NOT NULL, site_key TEXT NOT NULL,"
    " drive_key TEXT NOT NULL, files INTEGER NOT NULL, indexed_at TEXT NOT NULL)",
    "CREATE TABLE IF NOT EXISTS file (snapshot_id TEXT NOT NULL, dir TEXT NOT NULL, name TEXT NOT NULL,"
    " name_key TEXT NOT NULL, stored TEXT NOT NULL, size INTEGER NOT NULL, mtime TEXT NOT NULL,"
    " copy_index INTEGER NOT NULL)",
    "CREATE INDEX IF NOT EXISTS file_snapshot ON file (snapshot_id)",
    "CREATE INDEX IF NOT EXISTS file_name ON file (name_key)",
)
FILE_COLUMNS = "snapshot_id, dir, name, name_key, stored, size, mtime, copy_index"
INSERT = "INSERT INTO file (%s) VALUES (?,?,?,?,?,?,?,?)" % FILE_COLUMNS
ESCAPE = " ESCAPE '\\'"
BATCH = 5000
SELECT = (
    "SELECT f.snapshot_id, f.dir, f.name, f.size, f.mtime, f.copy_index, f.stored, s.time_utc, s.site_key, s.drive_key "
    "FROM file f JOIN snapshot s ON s.snapshot_id = f.snapshot_id WHERE "
)
ORDER = " ORDER BY f.name_key, s.time_utc DESC, "


def utc_time(value: str) -> str:
    """Normalise a restic time stamp to UTC with six fractional digits and a Z suffix.

    Args:
        value: An RFC 3339 time stamp with any number of fractional digits.

    Returns:
        The same instant as YYYY-MM-DDTHH:MM:SS.ffffffZ; the input unchanged when it does not parse.
    """
    found = TIME.match(value)
    if found is None:
        return value
    year, month, day, hour, minute, second = (int(found.group(n)) for n in range(1, 7))
    micro = int((found.group(7) or "0")[:6].ljust(6, "0"))
    zone = found.group(8)
    shift = 0 if zone == "Z" else (1 if zone[0] == "+" else -1) * (int(zone[1:3]) * 60 + int(zone[4:6]))
    moment = datetime(year, month, day, hour, minute, second, micro, tzinfo=timezone.utc) - timedelta(minutes=shift)
    return moment.strftime("%Y-%m-%dT%H:%M:%S.%fZ")


class FileIndex:
    """The name index of the indexed snapshots.

    Attributes:
        directory: Folder of the index file, created privately by the service.
        path: The SQLite file.
    """

    def __init__(self, data_dir: str | Path) -> None:
        """Name the index paths below the service data directory without creating anything.

        Args:
            data_dir: The service data directory.
        """
        self.directory = Path(data_dir) / INDEX_DIR
        self.path = self.directory / INDEX_FILE

    def connect(self) -> sqlite3.Connection:
        """Open the index, creating the folder (mode 0700) and the schema when absent.

        Returns:
            A connection with WAL, a 60 s busy timeout and case-sensitive LIKE.
        """
        self.directory.mkdir(mode=0o700, parents=True, exist_ok=True)
        conn = sqlite3.connect(str(self.path), timeout=60, isolation_level=None)
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA synchronous=NORMAL")
        conn.execute("PRAGMA case_sensitive_like=ON")
        for statement in SCHEMA:
            conn.execute(statement)
        return conn

    @contextlib.contextmanager
    def lock(self) -> Iterator[bool]:
        """Take the cross-process build lock without waiting.

        Returns:
            A context manager that yields True when this process holds the lock and False when another builder does.
        """
        self.directory.mkdir(mode=0o700, parents=True, exist_ok=True)
        descriptor = os.open(str(self.directory / "build.lock"), os.O_CREAT | os.O_RDWR, 0o600)
        held = False
        try:
            try:
                fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
                held = True
            except OSError:
                held = False
            yield held
        finally:
            os.close(descriptor)

    def snapshots(self) -> list[dict[str, Any]]:
        """Return every indexed snapshot.

        Returns:
            Rows with snapshot_id, time_utc, site_key, drive_key and files.
        """
        conn = self.connect()
        try:
            sql = "SELECT snapshot_id, time_utc, site_key, drive_key, files FROM snapshot ORDER BY time_utc"
            cursor = conn.execute(sql)
            names = [item[0] for item in cursor.description]
            return [dict(zip(names, row)) for row in cursor.fetchall()]
        finally:
            conn.close()

    def add_snapshot(
        self, snapshot_id: str, time_utc: str, site_key: str, drive_key: str, rows: Iterable[tuple[Any, ...]]
    ) -> int:
        """Index one snapshot in one transaction; a snapshot that is already indexed is left alone.

        Args:
            snapshot_id: The restic snapshot id.
            time_utc: The snapshot time, normalised by utc_time.
            site_key: The site key of the snapshot tags.
            drive_key: The library key of the snapshot tags.
            rows: Tuples (dir, name, name_key, stored, size, mtime, copy_index) of the files; consumed once.

        Returns:
            The number of files indexed, 0 when the snapshot was already there. A failure rolls everything back.
        """
        conn = self.connect()
        try:
            conn.execute("BEGIN IMMEDIATE")
            if conn.execute("SELECT 1 FROM snapshot WHERE snapshot_id = ?", (snapshot_id,)).fetchone():
                conn.execute("ROLLBACK")
                return 0
            count = 0
            try:
                batch: list[tuple[Any, ...]] = []
                for row in rows:
                    batch.append((snapshot_id,) + tuple(row))
                    if len(batch) >= BATCH:
                        conn.executemany(INSERT, batch)
                        count += len(batch)
                        batch = []
                conn.executemany(INSERT, batch)
                count += len(batch)
                now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
                values = (snapshot_id, time_utc, site_key, drive_key, count, now)
                conn.execute("INSERT INTO snapshot VALUES (?,?,?,?,?,?)", values)
                conn.execute("COMMIT")
            except BaseException:
                conn.execute("ROLLBACK")
                raise
            return count
        finally:
            conn.close()

    @staticmethod
    def _where(snapshot_ids: list[str], pattern: Pattern) -> tuple[str, list[Any]]:
        """Build the WHERE clause of a search.

        Args:
            snapshot_ids: The chosen snapshots.
            pattern: The parsed name part.

        Returns:
            The clause and its parameters.
        """
        marks = ",".join("?" * len(snapshot_ids))
        clause, params = "f.snapshot_id IN (%s)" % marks, list(snapshot_ids)
        if not pattern.empty:
            clause += " AND f.name_key LIKE ?" + ESCAPE
            params.append(pattern.like)
        return clause, params

    def search(
        self, snapshot_ids: list[str], pattern: Pattern, site_order: list[str], limit: int, offset: int
    ) -> tuple[int, list[dict[str, Any]]]:
        """Return one page of the files of the chosen snapshots whose name matches.

        Args:
            snapshot_ids: The chosen snapshots; an empty list gives an empty result.
            pattern: The parsed name part.
            site_order: Site keys in the order of their labels, the tie-break after the date.
            limit: Page size.
            offset: Rows to skip.

        Returns:
            The total of matching rows and the page, ordered by name key, then snapshot time newest first, the site order,
            the folder and the copy index.
        """
        if not snapshot_ids:
            return 0, []
        where, params = self._where(snapshot_ids, pattern)
        cases = "".join("WHEN ? THEN %d " % number for number in range(len(site_order)))
        rank = "CASE s.site_key " + cases + "ELSE 100000 END" if site_order else "0"
        conn = self.connect()
        try:
            total = conn.execute("SELECT COUNT(*) FROM file f WHERE " + where, params).fetchone()[0]
            query = SELECT + where + ORDER + rank + ", f.dir, f.copy_index LIMIT ? OFFSET ?"
            cursor = conn.execute(query, params + list(site_order) + [limit, offset])
            names = [item[0] for item in cursor.description]
            return int(total), [dict(zip(names, row)) for row in cursor.fetchall()]
        finally:
            conn.close()

    def suggest(self, snapshot_ids: list[str], pattern: Pattern, limit: int) -> tuple[list[str], bool]:
        """Return distinct shown names (key-distinct) that match, prefix matches first.

        Args:
            snapshot_ids: The chosen snapshots; an empty list gives no name.
            pattern: The parsed name part.
            limit: Maximum number of names.

        Returns:
            The names and whether more distinct names exist than limit.
        """
        if not snapshot_ids:
            return [], False
        where, params = self._where(snapshot_ids, pattern)
        first = "CASE WHEN f.name_key LIKE ?" + ESCAPE + " THEN 0 ELSE 1 END, f.name_key" if pattern.prefix else "f.name_key"
        conn = self.connect()
        try:
            query = "SELECT f.name_key, MIN(f.name) FROM file f WHERE " + where
            query += " GROUP BY f.name_key ORDER BY " + first + " LIMIT ?"
            extra = [pattern.prefix] if pattern.prefix else []
            rows = conn.execute(query, params + extra + [limit + 1]).fetchall()
        finally:
            conn.close()
        return [row[1] for row in rows[:limit]], len(rows) > limit
