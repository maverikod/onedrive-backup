"""The logic of the schedule commands M15-M17: read, write and status of the backup schedule (10.20.3)."""

from __future__ import annotations

import os
import re
from datetime import UTC, datetime, timedelta
from functools import partial
from pathlib import Path
from typing import Any

from . import scheduler
from .run_records import load_runs, runs_path
from . import run_diag
from .schedule_cron import iso_utc, parse_iso
from .schedule_parse import MAX_BYTES, ScheduleError, entry_views, next_runs, parse
from .schedule_store import ScheduleStore
from .scheduler_decide import GRACE_SECONDS
from .scheduler_support import probe_lock, storage_guard

REVISION = re.compile("[0-9a-f]{64}")
ACTOR = re.compile("[A-Za-z0-9._@:-]{1,64}")
RUN_KEYS = ("run_id", "started_at", "finished_at", "exit_code", "status", "trigger", "slot_utc")
WRITE_KEYS = ("written", "changed", "dry_run", "revision", "previous_revision", "backup_file", "text")


def data_dir() -> Path:
    """Return the data directory of the running service.

    Returns:
        The directory from ONEDRIVE_BACKUP_DATA, /data by default.
    """
    return Path(os.environ.get("ONEDRIVE_BACKUP_DATA", "/data"))


def is_scaffold() -> bool:
    """Tell whether the service runs in scaffold mode.

    Returns:
        True when ONEDRIVE_SCAFFOLD_MODE is 1.
    """
    return os.environ.get("ONEDRIVE_SCAFFOLD_MODE") == "1"


def get_store() -> ScheduleStore:
    """Return the store of the running scheduler, or a new one over the data directory.

    Returns:
        The schedule store.
    """
    if scheduler.INSTANCE is not None:
        return scheduler.INSTANCE.store
    folder = data_dir()
    return ScheduleStore(folder / "schedule", partial(storage_guard, folder))


def describe(parsed: dict[str, Any], now: datetime, count: int) -> dict[str, Any]:
    """Describe an effective schedule with its entries and next runs.

    Args:
        parsed: The result of parse().
        now: The instant of the call.
        count: The number of run plans wanted.

    Returns:
        timezone, jitter_minutes, catchup_hours, enabled, entries, next_runs and server_time_utc.
    """
    return {
        "timezone": parsed["timezone"],
        "jitter_minutes": parsed["jitter_minutes"],
        "catchup_hours": parsed["catchup_hours"],
        "enabled": parsed["enabled"],
        "entries": entry_views(parsed, now),
        "next_runs": next_runs(parsed, now, count),
        "server_time_utc": iso_utc(now),
    }


def schedule_get(next_count: int = 5) -> dict[str, Any]:
    """Answer backup_schedule_get: the stored text, its state and the next runs; nothing is written.

    Args:
        next_count: The number of run plans, 0 to 20.

    Returns:
        The result of M15.
    """
    now = datetime.now(UTC)
    store = get_store()
    read = store.read()
    result = {
        "text": read["text"],
        "revision": read["revision"],
        "exists": read["exists"],
        "source": read["source"],
        "valid": read["valid"],
        "problems": read["problems"],
        "path": str(store.path),
    }
    result.update(describe(read["parsed"], now, next_count))
    return result


def schedule_set(
    text: str, expected_revision: str | None = None, dry_run: bool = False, next_count: int = 5, actor: str = "unknown"
) -> dict[str, Any]:
    """Answer backup_schedule_set: check in the order of 10.20.3, then store the text atomically unless dry_run.

    Args:
        text: The new schedule text.
        expected_revision: The revision the caller read, or None.
        dry_run: Validate only.
        next_count: The number of run plans, 0 to 20.
        actor: The label for the change log.

    Returns:
        The result of M16.

    Raises:
        ScheduleError: SCHEDULE_TOO_LARGE, INVALID_REVISION, INVALID_ACTOR, INVALID_SCHEDULE, SCAFFOLD_ONLY,
            SCHEDULE_STORAGE_UNAVAILABLE, SCHEDULE_CONFLICT or SCHEDULE_WRITE_FAILED.
    """
    if len(text.encode("utf-8", "replace")) > MAX_BYTES:
        raise ScheduleError("SCHEDULE_TOO_LARGE", 400, "a schedule holds at most %d bytes" % MAX_BYTES)
    if expected_revision is not None and not REVISION.fullmatch(expected_revision):
        raise ScheduleError("INVALID_REVISION", 400, "expected_revision is 64 lowercase hex characters")
    if not ACTOR.fullmatch(actor):
        raise ScheduleError("INVALID_ACTOR", 400, "actor matches [A-Za-z0-9._@:-]{1,64}")
    store = get_store()
    now = datetime.now(UTC)
    checked = parse(text, now, store.zone)
    if not checked["valid"]:
        raise ScheduleError("INVALID_SCHEDULE", 400, "invalid schedule", {"problems": checked["problems"]})
    if is_scaffold() and not dry_run:
        raise ScheduleError("SCAFFOLD_ONLY", 503, "the service runs in scaffold mode")
    done = store.write(text, expected_revision=expected_revision, dry_run=dry_run, actor=actor)
    if done["written"] and scheduler.INSTANCE is not None:
        scheduler.INSTANCE.wake.set()
    parsed = done["parsed"]
    result = {key: done[key] for key in WRITE_KEYS}
    result["valid"] = True
    result["problems"] = [item for item in parsed["problems"] if item["severity"] == "warning"]
    result.update(describe(parsed, now, next_count))
    return result


def _shape(run: dict[str, Any], reasons: dict[str, str] | None = None) -> dict[str, Any]:
    """Project a run record to the keys of the status contract.

    Args:
        run: The record of load_runs().
        reasons: The reasons of the end records (run_diag.end_reasons()), read when omitted.

    Returns:
        run_id, started_at, finished_at, exit_code, status, trigger and slot_utc, then reason, log and retried (10.23.R).
    """
    shaped = {key: run.get(key) for key in RUN_KEYS}
    known = run_diag.end_reasons(data_dir()) if reasons is None else reasons
    shaped.update(run_diag.extra(data_dir(), run, known))
    return shaped


def _current(runs: list[dict[str, Any]], now: datetime) -> dict[str, Any] | None:
    """Describe the run that holds the backup lock.

    Args:
        runs: The run records.
        now: The instant of the call.

    Returns:
        The current run with its log reference (reason is null while it runs), or None when nobody holds the lock.
    """
    if not probe_lock(data_dir()):
        return None
    live = [item for item in runs if item["status"] == "running"]
    unknown = {"run_id": "unknown", "started_at": iso_utc(now), "trigger": "manual", "slot_utc": None, "pid": None}
    found = live[-1] if live else unknown
    began = parse_iso(found["started_at"]) or now
    result = {
        "run_id": found["run_id"],
        "started_at": found["started_at"],
        "trigger": found["trigger"],
        "slot_utc": found["slot_utc"],
        "pid": found.get("pid"),
        "elapsed_seconds": max(0, int((now - began).total_seconds())),
    }
    result.update(run_diag.extra(data_dir(), found, {}, current=True))
    return result


def _missed(running: scheduler.Scheduler | None) -> dict[str, Any]:
    """Describe the slot the scheduler holds back or dropped.

    Args:
        running: The scheduler, or None.

    Returns:
        pending, slot_utc and will_start_after_utc.
    """
    none = {"pending": False, "slot_utc": None, "will_start_after_utc": None}
    if running is None:
        return none
    action = running.last_action
    if action.slot_utc is None or action.reason not in ("grace", "dropped"):
        return none
    grace = action.reason == "grace"
    after = iso_utc(running.started + timedelta(seconds=GRACE_SECONDS)) if grace else None
    return {"pending": grace, "slot_utc": iso_utc(action.slot_utc), "will_start_after_utc": after}


def schedule_status(history_limit: int = 10) -> dict[str, Any]:
    """Answer backup_schedule_status: the thread, the effective schedule, the runs and the next run.

    Args:
        history_limit: The number of finished runs in the history, 0 to 50.

    Returns:
        The result of M17; nothing is written.
    """
    now = datetime.now(UTC)
    running = scheduler.INSTANCE
    read = get_store().read()
    parsed = read["parsed"]
    stopped = {
        "state": "stopped", "thread_alive": False, "started_at": None, "last_tick_at": None, "leader": False,
        "message": "the scheduler is not running",
    }
    thread = running.snapshot() if running is not None else stopped
    if is_scaffold():
        thread["state"] = "scaffold"
    records = [item for item in load_runs(runs_path(data_dir())) if not item["dry_run"]]
    reasons = run_diag.end_reasons(data_dir())
    finished = [_shape(item, reasons) for item in reversed(records) if item["status"] != "running"]
    plans = next_runs(parsed, now, 1)
    baseline = (running.state or {}).get("baseline_utc") if running is not None else None
    schedule = {
        "revision": read["revision"],
        "valid": read["valid"],
        "source": read["source"],
        "timezone": parsed["timezone"],
        "enabled": parsed["enabled"],
        "entries": len(parsed["entries"]),
        "baseline_utc": baseline or iso_utc(now),
    }
    return {
        "scheduler": thread,
        "schedule": schedule,
        "current_run": _current(records, now),
        "last_run": finished[0] if finished else None,
        "next_run": plans[0] if plans else None,
        "missed": _missed(running),
        "history": finished[:history_limit],
        "server_time_utc": iso_utc(now),
    }
