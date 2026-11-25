"""Run records of the backup: runs.jsonl written by backup_run for every start and read by the scheduler (10.20.5)."""

from __future__ import annotations

import json
import logging
import os
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from .schedule_cron import iso_utc

LOG = logging.getLogger("onedrive_backup")
KEEP_RUNS = 500
TRIM_LINES = 2000
MAX_REASON = 500
STATUS_OF_CODE = {0: "ok", 1: "errors", 2: "refused"}


def runs_path(data_dir: str | Path) -> Path:
    """Return the run record file of a data directory.

    Args:
        data_dir: The service data directory.

    Returns:
        <data>/schedule/runs.jsonl.
    """
    return Path(data_dir) / "schedule" / "runs.jsonl"


def append_line(path: Path, record: dict[str, Any]) -> bool:
    """Append one JSON line with a single O_APPEND write; a failure is one WARNING and never an exception.

    Args:
        path: The runs.jsonl file.
        record: The record.

    Returns:
        True when the line was written.
    """
    line = (json.dumps(record, ensure_ascii=False) + "\n").encode("utf-8")
    try:
        path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        handle = os.open(path, os.O_WRONLY | os.O_APPEND | os.O_CREAT, 0o600)
        try:
            os.write(handle, line)
        finally:
            os.close(handle)
        return True
    except OSError as exc:
        LOG.warning("scheduler: run record not written (%s): %s", path, exc)
        return False


def current_revision(data_dir: str | Path) -> str | None:
    """Read the revision of the stored schedule file for a run record, without parsing it.

    Args:
        data_dir: The service data directory.

    Returns:
        The sha256 of the file, or None when it cannot be read.
    """
    import hashlib

    try:
        return hashlib.sha256((Path(data_dir) / "schedule" / "schedule.cron").read_bytes()).hexdigest()
    except OSError:
        return None


class RunRecorder:
    """Writes the start and the end record of one backup run.

    Attributes:
        data_dir: The service data directory.
        path: The run record file.
    """

    def __init__(self, data_dir: str | Path) -> None:
        """Remember the data directory.

        Args:
            data_dir: The service data directory.
        """
        self.data_dir = Path(data_dir)
        self.path = runs_path(data_dir)

    def start(self, dry_run: bool = False) -> str:
        """Write the start line of this process; the trigger and the slot come from the environment.

        Args:
            dry_run: True for a run with --dry-run.

        Returns:
            The run id.
        """
        run_id = str(uuid.uuid4())
        record: dict[str, Any] = {
            "event": "start", "run_id": run_id, "started_at": iso_utc(datetime.now(UTC)),
            "trigger": os.environ.get("ONEDRIVE_RUN_TRIGGER", "manual"), "slot": os.environ.get("ONEDRIVE_RUN_SLOT"),
            "pid": os.getpid(), "schedule_revision": current_revision(self.data_dir),
        }
        if dry_run:
            record["dry_run"] = True
        append_line(self.path, record)
        return run_id

    def end(self, run_id: str, exit_code: int, reason: str | None = None) -> None:
        """Write the end line of a run; a non-zero exit code carries the bounded, already scrubbed reason.

        Args:
            run_id: The id returned by start().
            exit_code: The exit code of the run.
            reason: The text of the failure (at most 500 characters), used only when the exit code is not zero.

        Returns:
            None.
        """
        stamp = iso_utc(datetime.now(UTC))
        record: dict[str, Any] = {"event": "end", "run_id": run_id, "finished_at": stamp, "exit_code": exit_code}
        if exit_code != 0 and reason:
            record["reason"] = reason[:MAX_REASON]
        append_line(self.path, record)


def append_complete(
    path: Path, status: str, trigger: str, slot: str | None, now: datetime, exit_code: int | None = None
) -> None:
    """Write a complete record (start and end lines, no pid) for a start that never ran.

    Args:
        path: The runs.jsonl file.
        status: skipped_busy, launch_failed or another final status.
        trigger: The trigger of the slot.
        slot: The slot instant, or None.
        now: The instant of the decision.
        exit_code: The exit code when there is one.

    Returns:
        None.
    """
    run_id = str(uuid.uuid4())
    stamp = iso_utc(now)
    begin = {
        "event": "start", "run_id": run_id, "started_at": stamp, "trigger": trigger, "slot": slot, "pid": None,
        "schedule_revision": None,
    }
    append_line(path, begin)
    append_line(path, {"event": "end", "run_id": run_id, "finished_at": stamp, "exit_code": exit_code, "status": status})


def _status(end: dict[str, Any] | None) -> str:
    """Map an end line to the status of the run.

    Args:
        end: The end line, or None for a run without one.

    Returns:
        ok, errors, refused, interrupted, launch_failed, skipped_busy or running.
    """
    if end is None:
        return "running"
    if isinstance(end.get("status"), str):
        return str(end["status"])
    return STATUS_OF_CODE.get(end.get("exit_code"), "interrupted")  # type: ignore[arg-type]


def read_lines(path: Path) -> list[dict[str, Any]]:
    """Read the JSON objects of runs.jsonl; a missing file or a damaged line gives nothing for it.

    Args:
        path: The runs.jsonl file.

    Returns:
        The records in file order.
    """
    try:
        raw = path.read_text(encoding="utf-8").splitlines()
    except OSError:
        return []
    found = []
    for line in raw:
        try:
            item = json.loads(line)
        except ValueError:
            continue
        if isinstance(item, dict) and item.get("run_id"):
            found.append(item)
    return found


def load_runs(path: Path) -> list[dict[str, Any]]:
    """Join the start and the end lines into one record per run, oldest first.

    Args:
        path: The runs.jsonl file.

    Returns:
        Records with run_id, started_at, finished_at, exit_code, status, trigger, slot_utc, pid and dry_run.
    """
    starts: dict[str, dict[str, Any]] = {}
    ends: dict[str, dict[str, Any]] = {}
    for item in read_lines(path):
        if item.get("event") == "start":
            starts.setdefault(str(item["run_id"]), item)
        elif item.get("event") == "end":
            ends[str(item["run_id"])] = item
    runs = []
    for run_id, begin in starts.items():
        end = ends.get(run_id)
        runs.append({
            "run_id": run_id,
            "started_at": begin.get("started_at"),
            "finished_at": end.get("finished_at") if end else None,
            "exit_code": end.get("exit_code") if end else None,
            "status": _status(end),
            "trigger": begin.get("trigger", "manual"),
            "slot_utc": begin.get("slot"),
            "pid": begin.get("pid"),
            "dry_run": bool(begin.get("dry_run")),
        })
    runs.sort(key=lambda item: str(item["started_at"]))
    return runs


def reconcile(path: Path, now: datetime) -> int:
    """Close every start line without an end line as interrupted; the caller proved the backup lock is free.

    Args:
        path: The runs.jsonl file.
        now: The instant of the reconciliation.

    Returns:
        The number of runs closed.
    """
    closed = 0
    for run in load_runs(path):
        if run["status"] == "running":
            append_line(path, {"event": "end", "run_id": run["run_id"], "finished_at": iso_utc(now), "exit_code": None,
                               "status": "interrupted"})
            closed += 1
    return closed


def trim(path: Path) -> None:
    """Keep the lines of the newest 500 runs when the file holds more than 2000 lines (atomic rewrite).

    Args:
        path: The runs.jsonl file.

    Returns:
        None.
    """
    lines = read_lines(path)
    if len(lines) <= TRIM_LINES:
        return
    order = list(dict.fromkeys(str(item["run_id"]) for item in lines))
    keep = set(order[-KEEP_RUNS:])
    body = "".join(json.dumps(item, ensure_ascii=False) + "\n" for item in lines if str(item["run_id"]) in keep)
    temp = path.with_name(path.name + ".tmp-%d" % os.getpid())
    try:
        temp.write_text(body, encoding="utf-8")
        os.replace(temp, path)
    except OSError as exc:
        LOG.warning("scheduler: run records not trimmed: %s", exc)
        temp.unlink(missing_ok=True)
