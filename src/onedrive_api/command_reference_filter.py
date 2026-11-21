"""Canonical descriptions of the filter commands: options, search by name and the autocomplete names."""
from __future__ import annotations

from typing import Any

SITE_IDS = "Ticked site ids (array of strings, at most 100, no duplicates); omit or [] for every site."
DATES = "Ticked backup dates YYYY-MM-DD in the service time zone (at most 366, no duplicates); omit or [] for every date."
NAME_RULES = (
    "Name part: without a star it is a contains match, with at least one unescaped star ('*' is any sequence) it is a "
    "pattern anchored at both ends; backslash-star is a literal star; other characters are literal; case and Unicode "
    "normalisation are ignored; at most 8 stars, at most 128 characters, no control characters."
)
ERROR_NOTE = {
    "description": "Invalid parameter or unavailable source.",
    "code": "400 | 503 | VALIDATION_ERROR",
    "message": "Explanation.",
}
BAD_PARAMS = {
    "400 INVALID_SITE_ID | INVALID_DATE | INVALID_NAME_PART": {
        "description": "A malformed or duplicate site id or date, or a name part that breaks the grammar.",
        "solution": "Send well-formed values; the error names the parameter.",
    },
    "503 SCAFFOLD_ONLY | SOURCE_NOT_READY": {
        "description": "The service is a scaffold or the SharePoint inventory is not ready.",
        "solution": "Run the discovery and leave scaffold mode.",
    },
}
INDEX = "{complete, snapshots_total, snapshots_indexed}."
ITEMS = (
    "Array of {site_id, site_name, library_name, name, dir, size, mtime, snapshot_id, snapshot_time, file_path, "
    "is_copy, copy_index}; file_path and snapshot_id feed backup_prepare_download."
)
SUGGEST = (
    "Distinct file names (case and Unicode insensitive) of the ticked sites and dates that match the typed text, "
    "names that start with the text first. At least two characters that are not stars are required. "
)

FILTER_REFERENCE: dict[str, dict[str, Any]] = {
    "backup_filter_options": {
        "detailed_description": (
            "List the sites that have at least one indexed snapshot and the backup dates (calendar days of the snapshot "
            "time in the service time zone, Europe/Kyiv by default) of the ticked sites, newest first. Reads only the "
            "persistent file name index; index.complete is false while snapshots are still being indexed."
        ),
        "parameters": {"site_ids": SITE_IDS},
        "return_value": {
            "success": {
                "description": "The options of the filter.",
                "data": {
                    "sites": "Array of {site_id, name, snapshot_count, last_snapshot_time}.",
                    "dates": "Array of {date, snapshot_count}, newest first.",
                    "timezone": "The time zone of the dates.",
                    "index": INDEX,
                },
                "example": {"sites": [], "dates": [], "timezone": "Europe/Kyiv", "index": {"complete": True}},
            },
            "error": ERROR_NOTE,
        },
        "usage_examples": [
            {"description": "All options", "command": {}, "explanation": "Every site and every date."},
            {"description": "Dates of one site", "command": {"site_ids": ["site-1"]}, "explanation": "Only that site."},
        ],
        "error_cases": BAD_PARAMS,
        "best_practices": ["Call it when the page loads and again after a site is ticked."],
    },
    "backup_search_files": {
        "detailed_description": (
            "Search the files of all indexed snapshots of the ticked sites and dates by name. Every file in every "
            "matching snapshot is a row (all versions), ordered by name key, then snapshot time newest first. " + NAME_RULES
        ),
        "parameters": {
            "site_ids": SITE_IDS,
            "dates": DATES,
            "name_part": NAME_RULES,
            "limit": "Page size, integer 1..500; default 100.",
            "offset": "Rows to skip, integer 0..1000000; default 0.",
        },
        "return_value": {
            "success": {
                "description": "One page of rows and the exact total.",
                "data": {
                    "items": ITEMS,
                    "total": "Number of matching rows.",
                    "offset": "Echo.",
                    "limit": "Echo.",
                    "timezone": "The time zone of the dates.",
                    "index": INDEX,
                },
                "example": {"items": [], "total": 0, "offset": 0, "limit": 100},
            },
            "error": ERROR_NOTE,
        },
        "usage_examples": [
            {"description": "Names that start with akt", "command": {"name_part": "akt*"}, "explanation": "Anchored."},
            {"description": "One day", "command": {"dates": ["2026-11-21"], "limit": 100}, "explanation": "All files."},
        ],
        "error_cases": BAD_PARAMS,
        "best_practices": ["Page with offset; the order is the same on every page."],
    },
    "backup_suggest_names": {
        "detailed_description": SUGGEST + NAME_RULES,
        "parameters": {
            "text": NAME_RULES,
            "site_ids": SITE_IDS,
            "dates": DATES,
            "limit": "Maximum names, integer 1..20; default 10.",
        },
        "return_value": {
            "success": {
                "description": "The suggested names.",
                "data": {
                    "items": "Array of {name}.",
                    "text": "The trimmed text.",
                    "truncated": "More names exist than limit.",
                },
                "example": {"items": [], "text": "akt", "truncated": False},
            },
            "error": ERROR_NOTE,
        },
        "usage_examples": [
            {"description": "Suggestions for akt", "command": {"text": "akt"}, "explanation": "At most 10 names."},
        ],
        "error_cases": BAD_PARAMS,
        "best_practices": ["Ask after a pause of the typing, not on every key."],
    },
}
