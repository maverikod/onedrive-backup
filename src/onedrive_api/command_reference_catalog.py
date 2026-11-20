"""Canonical descriptions of the snapshot listing and export preparation commands."""
from __future__ import annotations

from typing import Any


CATALOG_REFERENCE: dict[str, dict[str, Any]] = {
    "backup_snapshots": {
        "detailed_description": (
            "List real, encrypted restic snapshots tagged onedrive from the "
            "configured repository, most recent first. This operation reads "
            "only local backup data; it never queries or modifies OneDrive."
        ),
        "parameters": {
            "limit": "Maximum snapshots in items (integer 1..1000; "
            + "default 100).",
        },
        "return_value": {
            "success": {
                "description": "Real restic snapshots were read and sorted.",
                "data": {
                    "items": "Array of restic snapshot objects (up to limit).",
                    "count": "Total snapshots before limit was applied.",
                },
                "example": {"items": [], "count": 0},
            },
            "error": {
                "description": "Local restic catalogue unavailable or "
                + "invalid.",
                "code": "400 | 503 | VALIDATION_ERROR",
                "message": "Explanation of the unavailable repository or "
                + "bad limit.",
            },
        },
        "usage_examples": [
            {
                "description": "Show recent snapshots",
                "command": {"limit": 20},
                "explanation": "Returns at most 20 snapshots and the "
                + "complete count.",
            },
            {
                "description": "Use the default",
                "command": {},
                "explanation": "Returns at most 100 snapshots.",
            },
        ],
        "error_cases": {
            "400": {
                "description": "Invalid limit.",
                "solution": "Use integer 1..1000.",
            },
            "503": {
                "description": "No mounted repository or server is "
                + "scaffold-only.",
                "solution": "Mount the backup disk, initialize "
                + "restic, and leave scaffold mode.",
            },
        },
        "best_practices": [
            "Use the returned snapshot id for backup_list_files.",
            "Do not treat health=200 as evidence that snapshots exist.",
        ],
    },
    "backup_list_files": {
        "detailed_description": (
            "Read file and directory nodes from one existing restic snapshot. "
            "Supports an optional relative prefix and offset-based "
            + "pagination. "
            "Paths are validated; filesystem traversal and shell "
            + "injection are refused."
        ),
        "parameters": {
            "snapshot_id": "Required hexadecimal snapshot identifier "
            + "(8..64 characters).",
            "prefix": "Optional relative POSIX path to select a subtree; "
            + "default empty.",
            "offset": "Zero-based item offset, integer 0..500000; default 0.",
            "limit": "Page size, integer 1..5000; default 1000.",
        },
        "return_value": {
            "success": {
                "description": "The requested snapshot listing is available.",
                "data": {
                    "snapshot_id": "Requested snapshot identifier.",
                    "items": "Page of file/directory nodes with path, "
                    + "type, size, mtime.",
                    "total": "Total matching nodes before pagination.",
                    "offset": "Effective offset.",
                    "limit": "Effective page limit.",
                },
                "example": {
                    "snapshot_id": "a" * 64,
                    "items": [],
                    "total": 0,
                    "offset": 0,
                    "limit": 100,
                },
            },
            "error": {
                "description": "Invalid snapshot/path or inaccessible "
                + "repository.",
                "code": "400 | 404 | 503 | VALIDATION_ERROR",
                "message": "Specific validation or storage failure.",
            },
        },
        "usage_examples": [
            {
                "description": "First page of Documents",
                "command": {
                    "snapshot_id": "a" * 64,
                    "prefix": "Documents",
                    "offset": 0,
                    "limit": 100,
                },
                "explanation": "Use a real snapshot id from backup_snapshots.",
            },
            {
                "description": "Next page",
                "command": {
                    "snapshot_id": "a" * 64,
                    "offset": 100,
                    "limit": 100,
                },
                "explanation": "Advance offset until it reaches total.",
            },
        ],
        "error_cases": {
            "400": {
                "description": "Malformed id, prefix or pagination value.",
                "solution": "Use a returned snapshot id and a "
                + "relative POSIX path.",
            },
            "503": {
                "description": "Restic repository unavailable or "
                + "scaffold mode.",
                "solution": "Check the mounted volume and service "
                + "configuration.",
            },
        },
        "best_practices": [
            "Never build paths from untrusted absolute filesystem locations.",
            "Use total, offset and limit to detect the last page.",
        ],
    },
    "backup_prepare_download": {
        "detailed_description": (
            "Stage one selected file, or a complete snapshot as a compressed "
            "tar.gz archive, outside the encrypted restic repository. A "
            + "generated "
            "opaque export_id refers only to the staged export; it never "
            + "grants "
            "arbitrary host-file access. Temporary output contains plaintext."
        ),
        "parameters": {
            "snapshot_id": "Required snapshot id obtained from "
            + "backup_snapshots.",
            "file_path": "Optional relative snapshot file path; null "
            + "means full archive.",
        },
        "return_value": {
            "success": {
                "description": "An export was staged and its integrity "
                + "metadata stored.",
                "data": {
                    "export_id": "Opaque 32-character hexadecimal id.",
                    "snapshot_id": "Source snapshot.",
                    "path": "File path, or null for a complete snapshot "
                    + "archive.",
                    "filename": "Suggested downloaded filename.",
                    "size_bytes": "Staged payload size in bytes.",
                    "sha256": "SHA-256 of staged plaintext payload.",
                    "created_at": "ISO timestamp of staging.",
                    "expires_at": "ISO timestamp of expiry (normally +24 h).",
                    "url": "Temporary download link /downloads/<export_id>/<filename>; "
                    + "GET it (with the X-API-Key header once the password mode is on).",
                },
                "example": {
                    "export_id": "b" * 32,
                    "filename": "example.txt",
                    "url": "/downloads/" + "b" * 32 + "/example.txt",
                    "size_bytes": 0,
                    "sha256": "0" * 64,
                },
            },
            "error": {
                "description": "Export failed or the input is invalid.",
                "code": "400 | 404 | 413 | 503 | VALIDATION_ERROR",
                "message": "Validation, size or restic failure.",
            },
        },
        "usage_examples": [
            {
                "description": "Stage one file",
                "command": {
                    "snapshot_id": "a" * 64,
                    "file_path": "Documents/example.txt",
                },
                "explanation": "Download from the returned url, or call "
                + "backup_download_begin with the returned export_id.",
            },
            {
                "description": "Stage an archive",
                "command": {
                    "snapshot_id": "a" * 64,
                    "file_path": None,
                },
                "explanation": "May require substantial disk space; max "
                + "size defaults to 10 GiB.",
            },
        ],
        "error_cases": {
            "400": {
                "description": "Invalid snapshot or file path.",
                "solution": "Use a real hex snapshot id and relative "
                + "file path.",
            },
            "404": {
                "description": "Requested file is absent.",
                "solution": "List the snapshot first.",
            },
            "413": {
                "description": "Export exceeds ONEDRIVE_MAX_EXPORT_BYTES.",
                "solution": "Export a smaller file or adjust the "
                + "guarded limit.",
            },
            "503": {
                "description": "Restic unavailable or scaffold mode.",
                "solution": "Finish configuring and mounting backup "
                + "storage.",
            },
        },
        "best_practices": [
            "Delete an export as soon as its SHA-256 and size have been "
            + "verified.",
            "Remember exports are plaintext; protect /data/exports "
            + "accordingly.",
        ],
    },
}
