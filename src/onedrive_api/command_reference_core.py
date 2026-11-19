"""Canonical descriptions of the help and info commands."""
from __future__ import annotations

from typing import Any


CORE_REFERENCE: dict[str, dict[str, Any]] = {
    "help": {
        "detailed_description": (
            "Discover all live registered MCP commands, or inspect the "
            "complete schema and canonical metadata of one named command. "
            "This command is read-only and does not expose credentials."
        ),
        "parameters": {
            "cmdname": (
                "Optional registered command name; omit to list all commands."
            ),
        },
        "return_value": {
            "success": {
                "description": "The current command listing or detail.",
                "data": {
                    "commands": "Registered command names and summaries.",
                    "metadata": "Named command schema and full metadata.",
                },
                "example": {"commands": {}},
            },
            "error": {
                "description": "The named command does not exist.",
                "code": "COMMAND_NOT_FOUND | VALIDATION_ERROR",
                "message": "Explanation of the missing or invalid command.",
            },
        },
        "usage_examples": [
            {
                "description": "List registered commands",
                "command": {},
                "explanation": "Find command names from the live registry.",
            },
            {
                "description": "Inspect info",
                "command": {"cmdname": "info"},
                "explanation": "Obtain the info schema and detailed metadata.",
            },
        ],
        "error_cases": {
            "COMMAND_NOT_FOUND": {
                "description": "Unknown command name.",
                "solution": "Read the current help listing.",
            },
        },
        "best_practices": [
            "Discover command names before making an API call.",
            "Read info for the installation and operational chapters.",
        ],
    },
    "info": {
        "detailed_description": (
            "Paginated reference for installation, security, configuration, "
            "backup operation, the UI, the download interfaces and every live MCP command. "
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
