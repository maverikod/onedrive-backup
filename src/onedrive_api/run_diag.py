"""Run diagnostics: the keys reason, log and retried of a run object (M17) and the bounded read of one run log (M24).

Matrix 10.23.R: every run object of backup_schedule_status carries reason, log and retried; backup_run_log reads at most
64 KiB of <data>/schedule/logs/<run_id>.log. Both are reads: nothing is written and no lock the scheduler waits on is taken.
"""

from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Any

from .catalog import CatalogError
from .run_log import logs_dir, scrub
from .run_records import load_runs, read_lines, runs_path

RUN_ID = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$")
DEFAULT_LIMIT = 16384
STATUS_REASONS = {
    "skipped_busy": "skipped: another backup held the lock when the slot came",
    "launch_failed": "launch failed: the scheduler could not start the backup process",
    "interrupted": "interrupted: the run ended without an end record",
}
HINT_RUN = "take run_id from backup_schedule_status.history"
HINT_NO_LOG = "a run before the run log existed or one that never started has no log; read another run"


def end_reasons(data_dir: str | Path) -> dict[str, str]:
    """Collect the reason of every end record of runs.jsonl.

    Args:
        data_dir: The service data directory.

    Returns:
        Run id to the recorded reason, for the runs that have one.
    """
    found: dict[str, str] = {}
    for item in read_lines(runs_path(data_dir)):
        reason = item.get("reason")
        if item.get("event") == "end" and isinstance(reason, str) and reason:
            found[str(item["run_id"])] = reason
    return found


def log_ref(data_dir: str | Path, run_id: str) -> dict[str, Any] | None:
    """Describe the log file of a run.

    Args:
        data_dir: The service data directory.
        run_id: The run id.

    Returns:
        {name, size_bytes, available}, or None for a run id that is not a uuid (the scheduler child before its start record).
    """
    if not RUN_ID.match(run_id):
        return None
    name = run_id + ".log"
    try:
        size = (logs_dir(data_dir) / name).stat().st_size
    except OSError:
        return {"name": name, "size_bytes": 0, "available": False}
    return {"name": name, "size_bytes": size, "available": True}


def extra(data_dir: str | Path, run: dict[str, Any], reasons: dict[str, str], current: bool = False) -> dict[str, Any]:
    """Build the keys reason, log and retried of one run object.

    Args:
        data_dir: The service data directory.
        run: The run object (it holds run_id, exit_code and status).
        reasons: The result of end_reasons().
        current: True for the running run, whose reason is null.

    Returns:
        reason (null for exit 0 and for a running run), log and retried (always 0: a failed run is never retried).
    """
    run_id = str(run.get("run_id"))
    reason = None
    if not current and run.get("exit_code") != 0:
        reason = reasons.get(run_id) or STATUS_REASONS.get(str(run.get("status")))
    return {"reason": reason, "log": log_ref(data_dir, run_id), "retried": 0}


def read_run_log(
    data_dir: str | Path, run_id: str, offset: int | None = None, limit: int = DEFAULT_LIMIT, tail: bool = False
) -> dict[str, Any]:
    """Read one bounded slice of the log of a recorded run.

    Args:
        data_dir: The service data directory.
        run_id: The run id of a recorded run.
        offset: First byte of the slice, 0 when omitted; exclusive with tail.
        limit: Largest number of bytes, 1..65536.
        tail: True to read the last limit bytes.

    Returns:
        run_id, name, size_bytes, offset, length, eof, encoding, text and rotated.

    Raises:
        CatalogError: INVALID_LOG_RANGE, INVALID_RUN_ID or RUN_LOG_NOT_FOUND.
    """
    if tail and offset is not None:
        raise CatalogError(
            "INVALID_LOG_RANGE: tail true cannot be combined with offset", 400,
            {"fields": ["offset", "tail"], "hint": "send either tail true or an offset"},
        )
    if not RUN_ID.match(run_id) or run_id not in {item["run_id"] for item in load_runs(runs_path(data_dir))}:
        raise CatalogError(
            "INVALID_RUN_ID: no recorded run has this run_id", 400, {"field": "run_id", "value": run_id, "hint": HINT_RUN}
        )
    folder = logs_dir(data_dir)
    try:
        handle = (folder / (run_id + ".log")).open("rb")
    except OSError:
        raise CatalogError(
            "RUN_LOG_NOT_FOUND: the run has no log file", 404, {"run_id": run_id, "hint": HINT_NO_LOG}
        ) from None
    with handle:
        size = os.fstat(handle.fileno()).st_size
        start = max(size - limit, 0) if tail else (offset or 0)
        if start > size:
            raise CatalogError(
                "INVALID_LOG_RANGE: offset is beyond the end of the log", 400,
                {"size_bytes": size, "offset": start, "hint": "use an offset from 0 to size_bytes"},
            )
        handle.seek(start)
        raw = handle.read(min(limit, size - start))
    return {
        "run_id": run_id, "name": run_id + ".log", "size_bytes": size, "offset": start, "length": len(raw),
        "eof": start + len(raw) == size, "encoding": "utf-8", "text": scrub(raw.decode("utf-8", "replace")),
        "rotated": (folder / (run_id + ".log.1")).is_file(),
    }
