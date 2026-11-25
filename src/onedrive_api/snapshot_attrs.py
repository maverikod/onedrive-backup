"""Snapshot attributes of revision 14 (matrix 10.22.2.5): backup type, trigger and run id of every indexed snapshot.

New snapshots carry the restic tags type-full, trigger-<scheduled|manual|unknown> and run-<run id>. The attributes of a
snapshot without those tags come from the run records (the run whose time window holds the snapshot) or, when no record
matches, from a derived cluster: snapshots less than six hours apart form one legacy run. Nothing is ever written to
restic, and an attribute that is already set is never changed.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from pathlib import Path
import sqlite3
from typing import Any

from .run_records import load_runs, runs_path

TRIGGER_WORDS = ("scheduled", "manual", "unknown")
SCHEDULED = ("schedule", "catchup", "scheduled")
LEGACY_GAP = timedelta(hours=6)
OPEN_RUN = timedelta(hours=12)
COLUMNS = (("backup_type", "TEXT"), ("trigger", "TEXT"), ("run_id", "TEXT"), ("type_source", "TEXT"))
TAGS = (("type-", "backup_type"), ("trigger-", "trigger"), ("run-", "run_id"))
SCHEMA_VERSION = 1
UPDATE = (
    'UPDATE snapshot SET backup_type = ?, "trigger" = ?, run_id = ?, type_source = ? '
    "WHERE snapshot_id = ? AND type_source IS NULL"
)


def trigger_word(raw: object) -> str:
    """Map the trigger of a run to the word of the snapshot tag.

    Args:
        raw: The trigger of the run: schedule, catchup, manual, cli or None.

    Returns:
        scheduled for the scheduler, unknown for no trigger, else manual.
    """
    if not isinstance(raw, str) or not raw:
        return "unknown"
    return "scheduled" if raw in SCHEDULED else "manual"


def run_tags(run_id: str, trigger: object) -> list[str]:
    """Return the restic tags that mark a new snapshot with its attributes.

    Args:
        run_id: The run id of the backup run.
        trigger: The trigger of the run.

    Returns:
        The tags type-full, trigger-<word> and run-<run id>.
    """
    return ["type-full", "trigger-" + trigger_word(trigger), "run-" + run_id]


def from_tags(tags: object) -> dict[str, str] | None:
    """Read the attributes from the tags of a snapshot.

    Args:
        tags: The restic tags.

    Returns:
        backup_type, trigger, run_id and type_source 'tag', or None when a tag is missing.
    """
    found: dict[str, str] = {}
    for tag in tags if isinstance(tags, list) else []:
        for prefix, name in TAGS:
            if isinstance(tag, str) and tag.startswith(prefix):
                found.setdefault(name, tag[len(prefix):])
    if len(found) == len(TAGS) and found["trigger"] in TRIGGER_WORDS and found["run_id"]:
        return {**found, "type_source": "tag"}
    return None


def _moment(value: object) -> datetime | None:
    """Parse an RFC 3339 time stamp.

    Args:
        value: The text.

    Returns:
        The aware time, or None when it does not parse.
    """
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None


def _windows(data_dir: str | Path) -> list[tuple[datetime, datetime, str, str]]:
    """List the time windows of the recorded runs.

    Args:
        data_dir: The service data directory.

    Returns:
        Tuples (start, end, run id, trigger word) of the runs that are not dry runs.
    """
    found = []
    for run in load_runs(runs_path(data_dir)):
        start = _moment(run.get("started_at"))
        if run.get("dry_run") or start is None:
            continue
        end = _moment(run.get("finished_at")) or start + OPEN_RUN
        found.append((start, end, str(run["run_id"]), trigger_word(run.get("trigger"))))
    return found


def backfill(conn: sqlite3.Connection, data_dir: str | Path) -> int:
    """Give every indexed snapshot without attributes its record or derived attributes; set ones stay.

    Args:
        conn: An open index connection inside a transaction.
        data_dir: The service data directory.

    Returns:
        The number of snapshots that had no attributes.
    """
    rows = conn.execute("SELECT snapshot_id, time_utc FROM snapshot WHERE type_source IS NULL ORDER BY time_utc").fetchall()
    windows = _windows(data_dir) if rows else []
    last: datetime | None = None
    cluster = "legacy-undated"
    for snapshot_id, stamp in rows:
        when = _moment(stamp)
        hit = next((w for w in windows if when is not None and w[0] <= when <= w[1]), None)
        if hit is not None:
            values: tuple[Any, ...] = ("full", hit[3], hit[2], "record")
        else:
            if when is not None and (last is None or when - last > LEGACY_GAP):
                cluster = "legacy-" + when.strftime("%Y%m%dT%H%M%SZ")
            last = when or last
            values = ("full", "unknown", cluster, "derived")
        conn.execute(UPDATE, values + (snapshot_id,))
    return len(rows)


def migrate(conn: sqlite3.Connection, data_dir: str | Path) -> None:
    """Add the attribute columns to the snapshot table and backfill them, once (PRAGMA user_version 1).

    Args:
        conn: An open index connection in autocommit mode.
        data_dir: The service data directory.
    """
    if conn.execute("PRAGMA user_version").fetchone()[0] >= SCHEMA_VERSION:
        return
    conn.execute("BEGIN IMMEDIATE")
    try:
        if conn.execute("PRAGMA user_version").fetchone()[0] < SCHEMA_VERSION:
            have = {row[1] for row in conn.execute("PRAGMA table_info(snapshot)")}
            for name, kind in COLUMNS:
                if name not in have:
                    conn.execute('ALTER TABLE snapshot ADD COLUMN "%s" %s' % (name, kind))
            backfill(conn, data_dir)
            conn.execute("PRAGMA user_version = %d" % SCHEMA_VERSION)
        conn.execute("COMMIT")
    except BaseException:
        conn.execute("ROLLBACK")
        raise
