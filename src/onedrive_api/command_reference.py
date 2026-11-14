"""Canonical detailed descriptions for the OneDrive Backup MCP commands.

The same records drive help(cmdname=...) metadata and info command pages.
"""
from __future__ import annotations

from typing import Any


REFERENCE: dict[str, dict[str, Any]] = {
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
                },
                "example": {
                    "export_id": "b" * 32,
                    "filename": "example.txt",
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
                "explanation": "Use the returned export_id with HTTPS GET "
                + "or Python client.",
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
    "backup_download_status": {
        "detailed_description": (
            "Return metadata of a previously staged export. This MCP command "
            "does not transfer bytes; use HTTPS GET "
            + "/api/v1/exports/{export_id} "
            "or the Python client for the payload."
        ),
        "parameters": {
            "export_id": "Required opaque 32-character "
            + "hexadecimal export id."
        },
        "return_value": {
            "success": {
                "description": "The staged file is present and has not "
                + "expired.",
                "data": {
                    "export_id": "Opaque id.",
                    "filename": "Suggested download filename.",
                    "size_bytes": "Expected byte count.",
                    "sha256": "Expected SHA-256 digest.",
                    "expires_at": "Expiry timestamp.",
                },
                "example": {
                    "export_id": "b" * 32,
                    "size_bytes": 0,
                    "sha256": "0" * 64,
                },
            },
            "error": {
                "description": "Export absent, expired or corrupted.",
                "code": "400 | 404 | 410 | 503 | VALIDATION_ERROR",
                "message": "Export metadata error.",
            },
        },
        "usage_examples": [
            {
                "description": "Inspect staged file",
                "command": {"export_id": "b" * 32},
                "explanation": ("Use an id returned by "
                                "backup_prepare_download."),
            },
        ],
        "error_cases": {
            "400": {
                "description": "Malformed id.",
                "solution": "Use a 32-character hex id.",
            },
            "404": {
                "description": "No staged file.",
                "solution": "Prepare a fresh export.",
            },
            "410": {
                "description": "Export expired.",
                "solution": "Prepare a fresh export.",
            },
        },
        "best_practices": [
            "Verify the downloaded byte count and SHA-256.",
            "Do not use the export id as a filesystem path.",
        ],
    },
    "backup_delete_export": {
        "detailed_description": (
            "Remove a staged plaintext payload and its metadata after a "
            "successful, verified download. This operation does not remove "
            "restic snapshots or modify the OneDrive source."
        ),
        "parameters": {
            "export_id": "Required id of a prepared export "
            + "(32-character hex)."
        },
        "return_value": {
            "success": {
                "description": "The staged export and its metadata were "
                + "deleted.",
                "data": {
                    "export_id": "Deleted id.",
                    "deleted": "True on success.",
                },
                "example": {"export_id": "b" * 32, "deleted": True},
            },
            "error": {
                "description": "Export absent, expired or invalid.",
                "code": "400 | 404 | 410 | 503 | VALIDATION_ERROR",
                "message": "Reason the staged export could not be "
                + "removed.",
            },
        },
        "usage_examples": [
            {
                "description": "Delete after SHA-256 verification",
                "command": {"export_id": "b" * 32},
                "explanation": "Deletes only the temporary export, never "
                + "the source snapshot.",
            },
        ],
        "error_cases": {
            "400": {
                "description": "Invalid export id.",
                "solution": "Use a generated id.",
            },
            "404": {
                "description": "Export not found.",
                "solution": "No action needed if already removed.",
            },
            "410": {
                "description": "Export expired.",
                "solution": "Remove expired data through supported "
                + "maintenance.",
            },
        },
        "best_practices": [
            "Remove plaintext staging promptly.",
            "Do not confuse export deletion with restic snapshot retention.",
        ],
    },
    "info": {
        "detailed_description": (
            "Paginated reference for installation, security, configuration, "
            "backup operation, UI/REST interfaces and every live MCP command. "
            "Page 1 is a complete contents list; following pages are general "
            "chapters, a command chapter, and one page per registered command."
        ),
        "parameters": {
            "page": "One-based page number, integer >= 1; " + "default 1."
        },
        "return_value": {
            "success": {
                "description": "Full contents or one untruncated chapter "
                + "was returned.",
                "data": {
                    "page": "Selected one-based page.",
                    "total_pages": "Number of pages in this deployed guide.",
                    "title": "Page title; command pages equal live "
                    + "command name.",
                    "kind": "toc | general | chapter | command.",
                    "content": "Complete Markdown page.",
                    "previous_page": "Previous page number or null.",
                    "next_page": "Next page number or null.",
                },
                "example": {
                    "page": 1,
                    "kind": "toc",
                    "title": "Table of contents",
                },
            },
            "error": {
                "description": "Invalid page or missing manual.",
                "code": "400 | 503 | VALIDATION_ERROR",
                "message": "Explanation including valid range.",
            },
        },
        "usage_examples": [
            {
                "description": "Read contents",
                "command": {},
                "explanation": "Equivalent to page=1; lists all page numbers.",
            },
            {
                "description": "Read chapter",
                "command": {"page": 2},
                "explanation": "Navigate using next_page until null.",
            },
        ],
        "error_cases": {
            "400": {
                "description": "Page not in 1..total_pages.",
                "solution": "Open page=1 and choose a valid page.",
            },
            "503": {
                "description": "Installed reference is absent or "
                + "unreadable.",
                "solution": "Reinstall the pinned production image.",
            },
        },
        "best_practices": [
            "Start with page=1; follow next_page to the end.",
            "Use help(cmdname=...) to inspect exact JSON schema.",
            "Do not treat scaffold health as backup readiness.",
        ],
    },
}


def command_metadata_for(cls: Any) -> dict[str, Any]:
    """Compose rich help metadata without altering JSON schema semantics.

    Returns:
        Detailed command metadata with parameters and examples.
    """
    record = REFERENCE.get(cls.name)
    if record is None:
        return {"parameters": cls._default_parameters_from_schema()}
    parameters = cls._default_parameters_from_schema()
    for name, description in record["parameters"].items():
        if name in parameters:
            parameters[name]["description"] = description
    return {
        "detailed_description": record["detailed_description"],
        "parameters": parameters,
        "return_value": record["return_value"],
        "usage_examples": record["usage_examples"],
        "error_cases": record["error_cases"],
        "best_practices": record["best_practices"],
    }
