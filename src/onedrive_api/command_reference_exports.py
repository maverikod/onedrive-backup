"""Canonical descriptions of the staged export commands."""
from __future__ import annotations

from typing import Any


EXPORT_REFERENCE: dict[str, dict[str, Any]] = {
    "backup_download_status": {
        "detailed_description": (
            "Return metadata of a previously staged export, with its temporary "
            "download link in the field url. This MCP command does not transfer "
            "bytes; GET the url, or use backup_download_begin and the adapter "
            "transfer service for the payload."
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
                    "url": "Temporary download link /downloads/<export_id>/<filename>.",
                },
                "example": {
                    "export_id": "b" * 32,
                    "url": "/downloads/" + "b" * 32 + "/example.txt",
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
    "backup_download_begin": {
        "detailed_description": (
            "Register an adapter transfer download session for one staged "
            "export. The session is confined to the exports directory "
            "(transfer.allowed_directories) and lives 86400 seconds; read the "
            "bytes with GET /api/transfer/downloads/{transfer_id}/chunks and "
            "verify the size and the SHA-256 in checksum_value."
        ),
        "parameters": {
            "export_id": "Required opaque 32-character hexadecimal export "
            + "id returned by backup_prepare_download."
        },
        "return_value": {
            "success": {
                "description": "A transfer session was registered.",
                "data": {
                    "transfer_id": "Transfer session id.",
                    "filename": "Suggested downloaded filename.",
                    "size_bytes": "Wire size in bytes.",
                    "checksum_algorithm": "sha256.",
                    "checksum_value": "SHA-256 of the staged payload.",
                    "compression": "identity.",
                    "expires_at": "Session expiry timestamp.",
                    "transport": "Chunk method and path template.",
                },
                "example": {
                    "transfer_id": "tr_" + "b" * 32,
                    "filename": "example.txt",
                    "checksum_algorithm": "sha256",
                },
            },
            "error": {
                "description": "Export absent, expired or invalid.",
                "code": "400 | 404 | 410 | 413 | 503 | VALIDATION_ERROR",
                "message": "Export or transfer error.",
            },
        },
        "usage_examples": [
            {
                "description": "Start a transfer download",
                "command": {"export_id": "b" * 32},
                "explanation": "Use an id returned by backup_prepare_download.",
            },
        ],
        "error_cases": {
            "404": {
                "description": "No staged export.",
                "solution": "Prepare a fresh export.",
            },
            "410": {
                "description": "Export expired.",
                "solution": "Prepare a fresh export.",
            },
        },
        "best_practices": [
            "Verify the byte count and SHA-256 after the transfer.",
            "Delete the export with backup_delete_export afterwards.",
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
}
