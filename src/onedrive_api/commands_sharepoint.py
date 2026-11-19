"""SharePoint discovery MCP commands."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any
from mcp_proxy_adapter.commands.result import CommandResult

from .sharepoint_discovery import DiscoveryError, SharePointInventory
from .commands_base import CatalogCommand


def _sharepoint_store() -> SharePointInventory:
    """Access the private inventory within the mounted backup volume."""
    base = Path(os.environ.get("ONEDRIVE_BACKUP_DATA", "/data"))
    return SharePointInventory(base / "sharepoint")


def _sharepoint_sites(**params: Any) -> dict:
    """Read only a complete, non-scaffold site inventory."""
    SharePointInventory.check_query(params.get("query", ""))
    if os.environ.get("ONEDRIVE_SCAFFOLD_MODE") == "1":
        raise DiscoveryError("SCAFFOLD_ONLY")
    return _sharepoint_store().sites(**params)


def _sharepoint_libraries(**params: Any) -> dict:
    """Read libraries of one verified site, never personal drives."""
    SharePointInventory.check_site_id(params.get("site_id"))
    if os.environ.get("ONEDRIVE_SCAFFOLD_MODE") == "1":
        raise DiscoveryError("SCAFFOLD_ONLY")
    return _sharepoint_store().libraries(**params)


def _sharepoint_status() -> dict:
    """Report source discovery coverage without making Graph requests."""
    if os.environ.get("ONEDRIVE_SCAFFOLD_MODE") == "1":
        return {"ready": False, "complete": False,
                "state": "SCAFFOLD_ONLY"}
    return _sharepoint_store().status()


class BackupSitesList(CatalogCommand):
    """List verified SharePoint Online sites from the last full scan."""

    name = "backup_sites_list"
    descr = "List discovered SharePoint sites."
    category = "sharepoint"

    async def execute(
        self, limit: int = 100, offset: int = 0,
        query: str = "", **kwargs: Any,
    ) -> CommandResult:
        """Read one bounded site page from persisted inventory."""
        return await self.apply(
            _sharepoint_sites, limit=limit, offset=offset, query=query
        )

    @classmethod
    def get_schema(cls) -> dict:
        """Describe bounded read-only site enumeration."""
        return cls._schema_with_descriptions({
            "type": "object",
            "properties": {
                "limit": {"type": "integer", "default": 100,
                          "minimum": 1, "maximum": 1000},
                "offset": {"type": "integer", "default": 0,
                           "minimum": 0, "maximum": 200000},
                "query": {"type": "string", "default": "",
                          "maxLength": 128},
            },
            "additionalProperties": False,
        })


class BackupLibrariesList(CatalogCommand):
    """List document libraries belonging to a verified site."""

    name = "backup_libraries_list"
    descr = "List discovered libraries of a SharePoint site."
    category = "sharepoint"

    async def execute(
        self, site_id: str = "", limit: int = 100,
        offset: int = 0, **kwargs: Any,
    ) -> CommandResult:
        """Return a page of libraries for a stable site identifier."""
        return await self.apply(
            _sharepoint_libraries, site_id=site_id,
            limit=limit, offset=offset
        )

    @classmethod
    def get_schema(cls) -> dict:
        """Describe required site ID and pagination restrictions."""
        return cls._schema_with_descriptions({
            "type": "object",
            "properties": {
                # No maxLength: an overlong or malformed site_id is refused by the command with
                # the error 400 INVALID_SITE_ID (R5), before the readiness gate.
                "site_id": {"type": "string", "minLength": 1},
                "limit": {"type": "integer", "default": 100,
                          "minimum": 1, "maximum": 1000},
                "offset": {"type": "integer", "default": 0,
                           "minimum": 0, "maximum": 200000},
            },
            "required": ["site_id"],
            "additionalProperties": False,
        })


class BackupDiscoveryStatus(CatalogCommand):
    """Report verified inventory coverage and readiness."""

    name = "backup_discovery_status"
    descr = "Report SharePoint discovery readiness and coverage."
    category = "sharepoint"

    async def execute(self, **kwargs: Any) -> CommandResult:
        """Read status without requesting credentials or source data."""
        return await self.apply(_sharepoint_status)

    @classmethod
    def get_schema(cls) -> dict:
        """Declare that discovery status has no input parameters."""
        return {
            "type": "object", "properties": {},
            "additionalProperties": False,
        }
