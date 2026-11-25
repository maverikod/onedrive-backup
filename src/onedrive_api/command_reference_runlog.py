"""Canonical description of backup_run_log (matrix 10.23.R.2, rows M24 and M17)."""
from __future__ import annotations

from typing import Any

RUN_EXAMPLE = "b" * 8 + "-0000-4000-8000-" + "0" * 12

RUNLOG_REFERENCE: dict[str, dict[str, Any]] = {
    "backup_run_log": {
        "detailed_description": (
            "Read the log of one backup run when its status is not ok. Take run_id from backup_schedule_status (last_run or "
            "history; reason says why the run failed and log.available tells whether a log exists). Through the MCP Proxy "
            "call_server(server_id='onedrive-backup', command='backup_run_log', params={'run_id': ..., 'tail': True}); "
            "help(cmdname='backup_run_log') shows this text. Without parameters besides run_id the answer is the first "
            "16384 bytes; tail true returns the LAST limit bytes, where the cause usually is; to read the whole log send "
            "offset = the previous offset + length until eof is true. Secrets are removed from the text. The command writes "
            "nothing and takes no lock that a backup waits for. No parameter names a path."
        ),
        "parameters": {
            "run_id": "Required run id (lower-case UUID) of a run listed by backup_schedule_status.",
            "offset": "First byte of the slice, 0..10485760; default 0; not together with tail true.",
            "limit": "Largest number of bytes of the slice, 1..65536; default 16384.",
            "tail": "True returns the last limit bytes of the log; default false; not together with offset.",
        },
        "return_value": {
            "success": {
                "description": "One slice of the log.",
                "data": {
                    "run_id": "The run.",
                    "name": "The log file name, <run_id>.log; a name, never a path.",
                    "size_bytes": "Size of the whole log in bytes.",
                    "offset": "First byte of this slice.",
                    "length": "Bytes of this slice.",
                    "eof": "True when offset + length reaches size_bytes.",
                    "encoding": "utf-8.",
                    "text": "The slice decoded as UTF-8; a character cut at a slice boundary becomes a replacement character.",
                    "rotated": "True when an older rotated part of the log exists beside it (the log is rotated at 10 MiB).",
                },
                "example": {"run_id": RUN_EXAMPLE, "size_bytes": 0, "offset": 0, "length": 0, "eof": True},
            },
            "error": {
                "description": "The run is unknown, has no log, or the range is wrong.",
                "code": "400 | 404 | VALIDATION_ERROR",
                "message": "INVALID_RUN_ID, RUN_LOG_NOT_FOUND or INVALID_LOG_RANGE.",
            },
        },
        "usage_examples": [
            {
                "description": "Read the end of the log of a failed run",
                "command": {"run_id": RUN_EXAMPLE, "tail": True},
                "explanation": "The last 16384 bytes; the reason of the run is also in backup_schedule_status.",
            },
        ],
        "error_cases": {
            "400": {
                "description": (
                    "INVALID_RUN_ID (no recorded run, error.data.hint) or INVALID_LOG_RANGE (offset beyond size_bytes, "
                    "or tail true with offset, error.data.fields)."
                ),
                "solution": "Take run_id from backup_schedule_status.history; use an offset from 0 to size_bytes.",
            },
            "404": {
                "description": "RUN_LOG_NOT_FOUND: the run exists but has no log file (it ran before the run log existed).",
                "solution": "Read another run; its reason in backup_schedule_status may still tell the cause.",
            },
        },
        "best_practices": [
            "Read the reason in backup_schedule_status first, then the tail of the log; read the whole log only when needed.",
        ],
    },
}
