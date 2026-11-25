"""Base command classes of the OneDrive Backup MCP commands."""

from __future__ import annotations

import asyncio
from typing import Any
from mcp_proxy_adapter.commands.base import Command
from mcp_proxy_adapter.commands.help_command import HelpCommand
from mcp_proxy_adapter.commands.result import CommandResult, ErrorResult

from .catalog import CatalogError
from .command_reference import REFERENCE, command_metadata_for
from .sharepoint_discovery import DiscoveryError
from .version import read_version


def _catalog():
    """Return the catalogue built by the server module factory."""
    from . import server

    return server._catalog()


class BackupHelpCommand(HelpCommand):
    """Describe registered commands with the canonical metadata."""

    category = "documentation"
    version = read_version()
    author = "OneDrive Backup maintainers"
    email = "maintainers@example.org"

    @classmethod
    def metadata(cls) -> dict[str, Any]:
        """Return the full help command reference metadata."""
        return command_metadata_for(cls)


class CatalogCommand(Command):
    category = "backup"
    version = read_version()
    author = "OneDrive Backup"
    email = "maintainers@example.org"

    @classmethod
    def metadata(cls) -> dict[str, Any]:
        """Return detailed descriptions shared by help and info."""
        return command_metadata_for(cls)

    @classmethod
    def _schema_with_descriptions(cls, schema: dict) -> dict:
        """Populate schema descriptions using the canonical reference."""
        descriptions = REFERENCE.get(cls.name, {}).get("parameters", {})
        for name, spec in schema.get("properties", {}).items():
            if isinstance(spec, dict):
                spec["description"] = descriptions.get(
                    name, spec.get("description", "")
                )
        return schema

    @staticmethod
    async def apply(call, **kwargs: Any):
        try:
            data = await asyncio.to_thread(call, **kwargs)
            return CommandResult(success=True, data=data)
        except CatalogError as exc:
            return ErrorResult(message=str(exc), code=exc.status, details=exc.details)
        except DiscoveryError as exc:
            return ErrorResult(message=exc.code, code=exc.status, details=exc.details)


class ExportCommand(CatalogCommand):
    """Command addressing one staged export by its opaque export_id."""

    @classmethod
    def get_schema(cls) -> dict:
        schema = {
            "type": "object",
            "properties": {"export_id": {"type": "string"}},
            "required": ["export_id"],
            "additionalProperties": False,
        }
        return cls._schema_with_descriptions(schema)
