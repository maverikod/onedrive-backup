"""Paginated OneDrive Backup reference derived from live command metadata.

The first page is complete contents; general chapters are read from the
installed Markdown document, followed by category and individual command pages.
"""
from __future__ import annotations

import json
from pathlib import Path
import re
from typing import Any

from mcp_proxy_adapter.commands.base import Command
from mcp_proxy_adapter.commands.command_registry import registry
from mcp_proxy_adapter.commands.result import CommandResult, ErrorResult

from .command_reference import REFERENCE, command_metadata_for


MANUAL_FILE = Path(__file__).with_name("ONEDRIVE_INFO.md")
MAX_PAGE_BYTES = 16384


def read_manual_sections() -> list[tuple[str, str]]:
    """Read the complete Markdown chapters without fallback text."""
    document = MANUAL_FILE.read_text(encoding="utf-8")
    chapters: list[tuple[str, str]] = []
    for block in re.split(r"(?=^## )", document, flags=re.MULTILINE):
        block = block.strip()
        if not block.startswith("## "):
            continue
        title = block.splitlines()[0][3:].strip()
        if not title:
            raise ValueError("Manual chapter title is empty")
        chapters.append((title, block))
    if not chapters:
        raise ValueError("No manual chapters are available")
    return chapters


def _registered() -> dict[str, type]:
    """Use the same live registry as help and proxy /commands discovery."""
    return dict(registry.get_all_commands())


def _chapter_index() -> list[dict[str, str]]:
    """Build pages for the currently registered API."""
    chapters = [
        {"kind": "general", "title": title, "content": text}
        for title, text in read_manual_sections()
    ]
    commands = _registered()
    categories: dict[str, list[str]] = {}
    for name, command_class in commands.items():
        category = str(getattr(command_class, "category", "") or "general")
        categories.setdefault(category, []).append(name)

    # Page numbering is assigned after the complete index has been assembled.
    for category in sorted(categories):
        names = sorted(categories[category])
        chapters.append(
            {
                "kind": "chapter",
                "title": f"Chapter: {category}",
                "content": category,
            }
        )
        chapters.extend(
            {"kind": "command", "title": name, "content": name}
            for name in names
        )
    return chapters


def _type_name(schema: dict[str, Any]) -> str:
    """Express string/null unions without losing JSON Schema distinctions."""
    value = schema.get("type", "any")
    if isinstance(value, list):
        return " | ".join(str(part) for part in value)
    return str(value)


def _render_command(name: str, command_class: Any) -> str:
    """Render a command page using canonical help metadata."""
    schema = command_class.get_schema()
    props = schema.get("properties", {})
    required = set(schema.get("required") or [])
    metadata = command_class.metadata() or {}
    reference = REFERENCE.get(name, {})

    description = (
        reference.get("detailed_description")
        or metadata.get("detailed_description")
        or getattr(command_class, "descr", "")
        or "Built-in command of the MCP Proxy adapter."
    )
    lines = [
        f"# {name}",
        "",
        f"**Command name:** {name}",
        f"**Class:** {command_class.__name__}",
        f"**Category:** {getattr(command_class, 'category', '') or 'general'}",
        f"**Version:** {getattr(command_class, 'version', '') or 'unknown'}",
        (
            "**Author:** "
            f"{getattr(command_class, 'author', '') or 'MCP Proxy Adapter'}"
        ),
        "",
        "## Purpose (Предназначение)",
        "",
        description,
        "",
        "## Arguments (Аргументы)",
        "",
        "| Parameter | Type | Required | Default | Description |",
        "| --- | --- | --- | --- | --- |",
    ]
    descriptions = reference.get("parameters", {})
    for param, spec in props.items():
        spec = spec if isinstance(spec, dict) else {}
        explanation = (
            descriptions.get(param)
            or spec.get("description")
            or (metadata.get("parameters") or {})
            .get(param, {})
            .get("description")
            or "See the command schema."
        )
        default = (
            json.dumps(spec["default"], ensure_ascii=False)
            if "default" in spec
            else "—"
        )
        lines.append(
            f"| {param} | {_type_name(spec)} | "
            f"{'Yes' if param in required else 'No'} | {default} | "
            f"{str(explanation).replace('|', '/')} |"
        )
    if not props:
        lines.append("| — | — | — | — | This command takes no parameters. |")
    lines += [
        "",
        (
            "**additionalProperties:** "
            f"{str(schema.get('additionalProperties', True)).lower()}"
        ),
        "",
        "## Returned data (Возвращаемые данные)",
        "",
    ]
    result = (
        reference.get("return_value") or metadata.get("return_value") or {}
    )
    success = result.get("success") or {}
    failure = result.get("error") or {}
    lines.append("### Success")
    lines.append(
        success.get("description") or "Command returns success=true and data."
    )
    for key, detail in (success.get("data") or {}).items():
        lines.append(f"- {key}: {detail}")
    if success.get("example") is not None:
        lines += [
            "",
            "Example data:",
            "",
            "~~~json",
            json.dumps(success["example"], ensure_ascii=False, indent=2),
            "~~~",
        ]
    lines += [
        "",
        "### Error",
        failure.get("description")
        or "The command returns an error on failure.",
        (
            "Possible codes: "
            f"{failure.get('code') or 'VALIDATION_ERROR, COMMAND_ERROR'}"
        ),
        "",
        "## Examples",
        "",
    ]
    examples = (
        reference.get("usage_examples") or metadata.get("usage_examples") or []
    )
    if not examples:
        examples = [
            {
                "description": "Show command metadata",
                "command": {"cmdname": name} if name != "help" else {},
                "explanation": "Call help with the target command name.",
            }
        ]
    for item in examples:
        lines += [
            f"### {item.get('description') or 'Example'}",
            "",
            "~~~json",
            json.dumps(
                {"command": name, "params": item.get("command", {})},
                ensure_ascii=False,
                indent=2,
            ),
            "~~~",
            "",
            str(item.get("explanation") or ""),
            "",
        ]
    lines += ["## Error codes summary", ""]
    errors = reference.get("error_cases") or metadata.get("error_cases") or {}
    lines += ["| Code | Description | Action |", "| --- | --- | --- |"]
    for code, detail in errors.items():
        detail = (
            detail
            if isinstance(detail, dict)
            else {"description": str(detail)}
        )
        lines.append(
            f"| {code} | {detail.get('description', '')} | "
            f"{detail.get('solution', '')} |"
        )
    lines.append(
        "| VALIDATION_ERROR | Invalid parameters or unknown fields. | "
        "Call help(cmdname=...) and correct the request. |"
    )
    lines += ["", "## Best practices", ""]
    practices = (
        reference.get("best_practices") or metadata.get("best_practices") or []
    )
    for practice in practices:
        lines.append("- " + str(practice))
    if not practices:
        lines.append(
            "- Read help for the exact command schema before "
            "using this command."
        )
    return "\n".join(lines).strip()


def _render_page(
    page: int, chapters: list[dict[str, str]], commands: dict[str, type]
) -> tuple[str, str, str]:
    """Render the exact page requested, including command group navigation."""
    if page == 1:
        rows = [
            "# Table of contents",
            "",
            f"Total pages: {len(chapters) + 1}. Call info with page=N.",
            "",
            "- 1. Table of contents (toc)",
        ]
        for n, entry in enumerate(chapters, 2):
            prefix = "  " if entry["kind"] == "command" else ""
            rows.append(f"{prefix}- {n}. {entry['title']} ({entry['kind']})")
        return "Table of contents", "toc", "\n".join(rows)

    selected = chapters[page - 2]
    title = selected["title"]
    kind = selected["kind"]
    if kind == "general":
        return title, kind, selected["content"]
    if kind == "command":
        return title, kind, _render_command(title, commands[title])

    category = selected["content"]
    rows = [
        f"# Chapter: {category}",
        "",
        "The following commands are available in this category:",
        "",
    ]
    for n, item in enumerate(chapters, 2):
        if item["kind"] == "command":
            cls = commands[item["title"]]
            if (getattr(cls, "category", "") or "general") == category:
                rows.append(
                    f"- {item['title']} (page {n}): "
                    f"{getattr(cls, 'descr', '') or 'MCP command'}"
                )
    return title, kind, "\n".join(rows)


class InfoCommand(Command):
    """Read the operations guide and the command reference."""

    name = "info"
    descr = "Paginated OneDrive Backup manual; page 1 is the full contents."
    category = "documentation"
    version = "0.3.5"
    author = "OneDrive Backup maintainers"
    email = "maintainers@example.org"

    @classmethod
    def metadata(cls) -> dict[str, Any]:
        """Use the canonical metadata and parameter schema."""
        return command_metadata_for(cls)

    @classmethod
    def get_schema(cls) -> dict[str, Any]:
        """Validate the mandatory 1-based paging contract."""
        return {
            "type": "object",
            "properties": {
                "page": {
                    "type": "integer",
                    "minimum": 1,
                    "default": 1,
                    "description": (
                        "Page 1 = all contents; "
                        "pages 2..N = full chapters."
                    ),
                },
            },
            "additionalProperties": False,
        }

    async def execute(self, page: int = 1, **kwargs: Any) -> CommandResult:
        """Return an untruncated page or a validation/manual error."""
        if type(page) is not int or page < 1:
            return ErrorResult(
                "page must be an integer in 1..total_pages", code=400
            )
        try:
            chapters = _chapter_index()
            commands = _registered()
        except (OSError, UnicodeError, ValueError) as exc:
            return ErrorResult(
                "Operations manual unavailable: " + str(exc), code=503
            )
        total_pages = len(chapters) + 1
        if page > total_pages:
            return ErrorResult(
                f"page={page} is out of range 1..{total_pages}",
                code=400,
                details={"page": page, "total_pages": total_pages},
            )
        title, kind, content = _render_page(page, chapters, commands)
        response = {
            "page": page,
            "total_pages": total_pages,
            "title": title,
            "kind": kind,
            "content": content,
            "previous_page": page - 1 if page > 1 else None,
            "next_page": page + 1 if page < total_pages else None,
            "has_previous": page > 1,
            "has_next": page < total_pages,
            "truncated": False,
        }
        encoded = json.dumps(
            response, ensure_ascii=False, separators=(",", ":")
        )
        if len(encoded.encode("utf-8")) > MAX_PAGE_BYTES:
            return ErrorResult(
                (
                    f"Page {page} exceeds {MAX_PAGE_BYTES} bytes; "
                    "manual must be divided"
                ),
                code=503,
                details={"page": page, "total_pages": total_pages},
            )
        return CommandResult(success=True, data=response)
