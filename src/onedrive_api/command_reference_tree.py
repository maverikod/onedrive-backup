"""Canonical descriptions of the folder tree (matrix 10.21.4): backup_folder_children and the scope parameters."""
from __future__ import annotations

from typing import Any

from .command_reference_filter import ERROR_NOTE, INDEX

SITE_ID = "Scope: the site (Graph site id, 1..300 characters of A-Za-z0-9_,.!@-); a search is limited to its files."
DRIVE_ID = "Scope: the library of the site (Graph drive id); needs site_id."
DIR = (
    "Scope: the folder of the library as segments joined by a slash, '' is the library root; no leading or "
    "trailing slash, no empty, '.' or '..' segment, no control characters, a segment of 1..255 characters, at "
    "most 64 segments and 1024 characters; needs drive_id. Without recursive only the files directly in the "
    "folder match."
)
RECURSIVE = "Scope: true takes the whole subtree of the folder (the whole library for the root); needs drive_id."
SCOPE_PARAMETERS: dict[str, str] = {"site_id": SITE_ID, "drive_id": DRIVE_ID, "dir": DIR, "recursive": RECURSIVE}
ITEMS_13 = (
    "Array of {site_id, site_name, library_name, drive_id, name, dir, size, mtime, snapshot_id, snapshot_time, "
    "file_path, is_copy, copy_index}; file_path and snapshot_id feed backup_prepare_download."
)
SCOPE_ERRORS: dict[str, Any] = {
    "400 INVALID_FOLDER_SCOPE": {
        "description": (
            "drive_id without site_id, or dir or recursive without drive_id; error.data.fields names what is missing."
        ),
        "solution": "Send the whole chain site_id, drive_id, dir.",
    },
    "400 INVALID_DRIVE_ID | INVALID_DIR": {
        "description": "A malformed library id or folder address.",
        "solution": "Send a drive id of backup_libraries_list and a folder as listed by backup_folder_children.",
    },
}
NODE = (
    "Array of {kind (site, library or folder), site_id, drive_id, dir, name, file_count, direct_count, "
    "has_children}; file_count counts the file rows of the whole subtree, direct_count the rows directly in the "
    "node, every string is present and '' when it does not apply."
)
PATH = "Array of {kind, name, site_id, drive_id, dir}: the chain site -> library -> folders to the parent inclusive."
SAME_AS_SEARCH: dict[str, Any] = {
    "description": "As in backup_search_files.",
    "solution": "Send well-formed values.",
}

TREE_REFERENCE: dict[str, dict[str, Any]] = {
    "backup_folder_children": {
        "detailed_description": (
            "List the children of one node of the folder tree site -> library -> folders, computed at query time "
            "from the file name index: without parameters the sites, with site_id its libraries, with site_id and "
            "drive_id the top folders of the library, with dir the subfolders of that folder. Only nodes with at "
            "least one matching file are returned, ordered by name (case and Unicode insensitive); the ticked "
            "site_ids, dates and name_part restrict the rows."
        ),
        "parameters": {
            "site_id": SITE_ID, "drive_id": DRIVE_ID, "dir": DIR,
            "site_ids": "Ticked site ids (array of strings, at most 100, no duplicates); omit or [] for every site.",
            "dates": "Ticked backup dates YYYY-MM-DD (at most 366, no duplicates); omit or [] for every date.",
            "name_part": "Name part as in backup_search_files; '' restricts nothing.",
            "limit": "Page size, integer 1..500; default 200.",
            "offset": "Children to skip, integer 0..100000; default 0.",
        },
        "return_value": {
            "success": {
                "description": "One page of children and the exact number of children.",
                "data": {
                    "nodes": NODE,
                    "total": "Number of children.",
                    "offset": "Echo.",
                    "limit": "Echo.",
                    "path": PATH,
                    "timezone": "The time zone of the dates.",
                    "index": INDEX,
                },
                "example": {"nodes": [], "total": 0, "offset": 0, "limit": 200, "path": []},
            },
            "error": ERROR_NOTE,
        },
        "usage_examples": [
            {"description": "The sites", "command": {}, "explanation": "The root level of the tree."},
            {"description": "Libraries of a site", "command": {"site_id": "site-1"}, "explanation": "Second level."},
            {
                "description": "Subfolders",
                "command": {"site_id": "site-1", "drive_id": "drive-1", "dir": "a/b"},
                "explanation": "The children of the folder a/b.",
            },
        ],
        "error_cases": {**SCOPE_ERRORS, "400 INVALID_SITE_ID | INVALID_DATE | INVALID_NAME_PART | 503": SAME_AS_SEARCH},
        "best_practices": ["Load the children of a node when it is opened and page with offset."],
    },
}
