"""Canonical descriptions of the SharePoint discovery commands."""
from __future__ import annotations

from typing import Any


SHAREPOINT_REFERENCE: dict[str, dict[str, Any]] = {
    "backup_sites_list": {
        "detailed_description": (
            "List SharePoint Online sites from the latest COMPLETE "
            "Microsoft Graph discovery. Incomplete, stale or missing "
            "inventory refuses listing instead of returning fake data."
        ),
        "parameters": {
            "limit": "Maximum sites in a page; integer 1..1000.",
            "offset": "Zero-based offset; integer 0..200000.",
            "query": "Optional case-insensitive name or URL filter.",
        },
        "return_value": {
            "success": {
                "description": "Pages of verified SharePoint site records.",
                "data": {
                    "items": "Sites with stable site_id, name and URL.",
                    "total": "Total sites matching the query.",
                    "limit": "Page limit.",
                    "offset": "Page offset.",
                },
                "example": {"items": [], "total": 0,
                            "limit": 100, "offset": 0},
            },
            "error": {
                "description": "Discovery was not complete or inputs invalid.",
                "code": "400 | 503",
                "message": "INVALID_LIMIT, INVALID_QUERY or SOURCE_NOT_READY.",
            },
        },
        "usage_examples": [{
            "description": "Browse verified sites",
            "command": {"limit": 100, "offset": 0},
            "explanation": "Only returns data from a complete inventory.",
        }],
        "error_cases": {
            "SOURCE_NOT_READY": {
                "description": "No current verified source inventory.",
                "solution": "Perform a complete read-only Graph scan.",
            },
        },
        "best_practices": [
            "Page through all sites using total and offset.",
            "Use stable site_id for subsequent library requests.",
        ],
    },
    "backup_libraries_list": {
        "detailed_description": (
            "List document libraries for one SharePoint site from a "
            "completed Microsoft Graph inventory; names are not stable IDs."
        ),
        "parameters": {
            "site_id": "Required stable site identifier from sites list.",
            "limit": "Maximum libraries on this page; integer 1..1000.",
            "offset": "Zero-based offset; integer 0..200000.",
        },
        "return_value": {
            "success": {
                "description": "Verified document libraries for a site.",
                "data": {
                    "items": "Libraries with site_id, drive_id, name and URL.",
                    "total": "Total matching document libraries.",
                },
                "example": {"items": [], "total": 0},
            },
            "error": {
                "description": "Unknown site, invalid ID, or missing scan.",
                "code": "400 | 404 | 503",
                "message": "Stable failure code; never an access token.",
            },
        },
        "usage_examples": [{
            "description": "Browse site libraries",
            "command": {"site_id": "example.sharepoint.com,1,2"},
            "explanation": "Use the site_id returned by backup_sites_list.",
        }],
        "error_cases": {
            "SITE_NOT_FOUND": {
                "description": "Unknown site identifier.",
                "solution": "List sites from the complete inventory.",
            },
        },
        "best_practices": [
            "Do not construct library paths from display names.",
            "Use stable drive_id alongside the site_id.",
        ],
    },
    "backup_discovery_status": {
        "detailed_description": (
            "Report the latest SharePoint discovery coverage and readiness. "
            "Does not trigger authentication or enumerate sites itself."
        ),
        "parameters": {},
        "return_value": {
            "success": {
                "description": "Nonsecret discovery readiness and coverage.",
                "data": {
                    "ready": "True only with a successful complete inventory.",
                    "state": "READY, NOT_DISCOVERED or DISCOVERY_INCOMPLETE.",
                },
                "example": {"ready": False, "state": "NOT_DISCOVERED"},
            },
            "error": {
                "description": "Stored inventory cannot be read safely.",
                "code": "503",
                "message": "Unsafe or malformed local discovery state.",
            },
        },
        "usage_examples": [{
            "description": "Inspect discovery readiness",
            "command": {},
            "explanation": "Check before listing sites and libraries.",
        }],
        "error_cases": {
            "INVENTORY_INVALID": {
                "description": "Unreadable persisted metadata.",
                "solution": "Inspect protected discovery state on the host.",
            },
        },
        "best_practices": [
            "Do not confuse /health with source readiness.",
            "Check coverage and errors after each complete scan.",
        ],
    },
}
