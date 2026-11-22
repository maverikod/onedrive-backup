"""Canonical descriptions of the schedule commands: get, set and status (10.20.3)."""
from __future__ import annotations

from typing import Any

NEXT_COUNT = "Number of next run plans, integer 0..20; default 5."
PLAN = "Array of {slot_local, slot_utc, start_utc, start_local, entry_lines} ordered by start_utc."
SHARED = {
    "timezone": "The IANA zone of the slots.",
    "jitter_minutes": "JITTER directive.",
    "catchup_hours": "CATCHUP directive.",
    "enabled": "ENABLED directive.",
    "entries": "Array of {line, expression, next_start_utc}.",
    "next_runs": PLAN,
    "server_time_utc": "The instant of the call.",
}
ERROR_NOTE = {
    "description": "Invalid parameter, conflict or unavailable storage.",
    "code": "400 | 409 | 500 | 503 | VALIDATION_ERROR",
    "message": "The string code and an explanation; error.data carries the details.",
}
GRAMMAR = (
    "Text: UTF-8, at most 16384 bytes, 200 lines, 20 entries. Lines starting with # are comments. "
    "Directives, once each: TZ=<IANA zone>, JITTER=<0..60>m, CATCHUP=<0..168>h, ENABLED=yes|no. "
    "An entry is five cron fields (minute hour day-of-month month day-of-week); no macros; day-of-month "
    "and day-of-week are combined by OR when both are restricted. Consecutive slots are at least 30 minutes apart."
)
GET_DETAIL = (
    "Read the backup schedule file (/data/schedule/schedule.cron): the stored text, its revision, whether it is "
    "valid, the parsed entries and the next planned runs. Nothing is written; a missing file answers the default."
)
STATUS_DETAIL = (
    "Read the scheduler thread and the runs: its state, the effective schedule, the running backup, the last runs "
    "and the next planned run. Nothing is written."
)
SET_PARAMETERS = {
    "text": "The whole new schedule text, 0..16384 UTF-8 bytes.",
    "expected_revision": "Revision read before the edit, 64 lowercase hex; another current one is 409 SCHEDULE_CONFLICT.",
    "dry_run": "Validate only; nothing is written; default false.",
    "next_count": NEXT_COUNT,
    "actor": "Label for the change log, [A-Za-z0-9._@:-]{1,64}; default unknown.",
}
SET_ERRORS = {
    "400 INVALID_SCHEDULE": {
        "description": "The text breaks the grammar; error.data.problems lists every problem.",
        "solution": "Fix the lines named.",
    },
    "400 SCHEDULE_TOO_LARGE | INVALID_REVISION | INVALID_ACTOR": {
        "description": "A bad size, revision or actor.",
        "solution": "Correct the parameter.",
    },
    "409 SCHEDULE_CONFLICT": {
        "description": "The schedule changed; error.data has current_revision and current_text.",
        "solution": "Merge and send again.",
    },
    "503 SCAFFOLD_ONLY | SCHEDULE_STORAGE_UNAVAILABLE": {
        "description": "Scaffold mode, or the archive storage is not usable.",
        "solution": "Fix the deployment.",
    },
}
GET_DATA = dict(
    SHARED,
    text="The stored text as it is.",
    revision="sha256 hex of the text; send it as expected_revision.",
    exists="False when the file is missing.",
    source="file | default | memory | history of the effective schedule.",
    valid="False when the stored text breaks the grammar.",
    problems="Array of {line, column, code, severity, message}.",
    path="The schedule file path.",
)
SET_DATA = dict(
    SHARED,
    written="True when the file was written.",
    changed="True when the text differs from the stored one.",
    dry_run="Echo.",
    revision="Revision of the text after the call.",
    previous_revision="Revision before the call, or null.",
    backup_file="The history file made, or null.",
    text="The normalised text.",
    valid="Always true.",
    problems="The warnings.",
)
STATUS_DATA = {
    "scheduler": "{state, thread_alive, started_at, last_tick_at, leader, message}.",
    "schedule": "{revision, valid, source, timezone, enabled, entries, baseline_utc}.",
    "current_run": "{run_id, started_at, trigger, slot_utc, pid, elapsed_seconds} or null.",
    "last_run": "{run_id, started_at, finished_at, exit_code, status, trigger, slot_utc} or null.",
    "next_run": "One run plan or null.",
    "missed": "{pending, slot_utc, will_start_after_utc}.",
    "history": "Finished runs, newest first.",
    "server_time_utc": "The instant of the call.",
}

SCHEDULE_REFERENCE: dict[str, dict[str, Any]] = {
    "backup_schedule_get": {
        "detailed_description": GET_DETAIL,
        "parameters": {"next_count": NEXT_COUNT},
        "return_value": {
            "success": {
                "description": "The schedule.",
                "data": GET_DATA,
                "example": {"valid": True, "source": "file", "timezone": "Europe/Kyiv"},
            },
            "error": ERROR_NOTE,
        },
        "usage_examples": [{"description": "Read the schedule", "command": {}, "explanation": "Five next runs."}],
        "error_cases": {},
        "best_practices": ["Read before you write and send the revision back as expected_revision."],
    },
    "backup_schedule_set": {
        "detailed_description": "Check or store the whole schedule text. " + GRAMMAR + " The actor is only a label.",
        "parameters": SET_PARAMETERS,
        "return_value": {
            "success": {
                "description": "The stored or checked schedule; problems holds warnings only.",
                "data": SET_DATA,
                "example": {"written": False, "dry_run": True, "valid": True},
            },
            "error": ERROR_NOTE,
        },
        "usage_examples": [
            {"description": "Check a text", "command": {"text": "30 2 * * *\n", "dry_run": True}, "explanation": "No write."},
        ],
        "error_cases": SET_ERRORS,
        "best_practices": ["Always send expected_revision; an AI must label itself in actor."],
    },
    "backup_schedule_status": {
        "detailed_description": STATUS_DETAIL,
        "parameters": {"history_limit": "Finished runs in history, integer 0..50; default 10."},
        "return_value": {
            "success": {
                "description": "The status.",
                "data": STATUS_DATA,
                "example": {"scheduler": {"state": "waiting", "thread_alive": True}},
            },
            "error": ERROR_NOTE,
        },
        "usage_examples": [{"description": "Read the status", "command": {}, "explanation": "Ten runs of history."}],
        "error_cases": {},
        "best_practices": ["Poll it every 15 seconds at most."],
    },
}
