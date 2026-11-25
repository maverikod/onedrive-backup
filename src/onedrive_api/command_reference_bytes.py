"""Canonical description of backup_download_chunk (matrix 10.22.4.3)."""
from __future__ import annotations

from typing import Any

BYTES_REFERENCE: dict[str, dict[str, Any]] = {
    "backup_download_chunk": {
        "detailed_description": (
            "Read one slice of a staged export as base64 through the MCP Proxy, so that a model can fetch the bytes "
            "of a file without an HTTP call. Take export_id from backup_prepare_download (staged true); read from "
            "offset 0 with the default limit until eof is true, concatenate the decoded slices and compare the "
            "result with size_bytes and sha256. The command changes nothing: it does not extend the expiry of the "
            "export and creates no file. Exports above 4194304 bytes are refused; use backup_download_begin."
        ),
        "parameters": {
            "export_id": "Required opaque 32-character hexadecimal export id of a staged export.",
            "offset": "First byte of the slice, 0..total_size; default 0. An offset above total_size is refused.",
            "limit": "Largest number of bytes of the slice, 1..262144; default 65536.",
        },
        "return_value": {
            "success": {
                "description": "One slice of the export.",
                "data": {
                    "export_id": "The export.",
                    "offset": "First byte of this slice.",
                    "length": "Decoded bytes of this slice.",
                    "eof": "True when offset + length reaches total_size.",
                    "total_size": "Size of the whole export in bytes.",
                    "sha256": "SHA-256 of the whole export, the same as backup_prepare_download.",
                    "chunk_sha256": "SHA-256 of this decoded slice.",
                    "encoding": "base64.",
                    "data_b64": "The slice, base64; empty at the end of the export.",
                },
                "example": {"export_id": "b" * 32, "offset": 0, "length": 0, "eof": True, "total_size": 0},
            },
            "error": {
                "description": "Export absent, expired, too large for slices, or the offset is beyond the end.",
                "code": "400 | 404 | 410 | 413 | 503 | VALIDATION_ERROR",
                "message": "INVALID_OFFSET, EXPORT_TOO_LARGE_FOR_CHUNKS or the export error of backup_download_status.",
            },
        },
        "usage_examples": [
            {
                "description": "Read the first slice",
                "command": {"export_id": "b" * 32},
                "explanation": "Repeat with offset advanced by length until eof is true.",
            },
        ],
        "error_cases": {
            "400": {
                "description": "INVALID_OFFSET: the offset is above total_size (error.data.total_size).",
                "solution": "Use an offset from 0 to total_size.",
            },
            "404": {"description": "Unknown export.", "solution": "Stage the file with backup_prepare_download."},
            "410": {"description": "Export expired.", "solution": "Stage the file again."},
            "413": {
                "description": "EXPORT_TOO_LARGE_FOR_CHUNKS: the export is above 4194304 bytes.",
                "solution": "Use backup_download_begin or the url of backup_download_status.",
            },
        },
        "best_practices": [
            "Verify the decoded size and the SHA-256 of the whole export.",
            "Delete the export with backup_delete_export when the bytes are read.",
        ],
    },
}
