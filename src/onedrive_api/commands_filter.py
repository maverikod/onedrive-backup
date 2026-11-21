"""MCP commands of the single filter page: backup_filter_options, backup_search_files, backup_suggest_names (10.19.5)."""

from __future__ import annotations

import os
from typing import Any
from mcp_proxy_adapter.commands.result import CommandResult

from .commands_base import CatalogCommand, _catalog
from .filter_service import FilterService

SITE_IDS_SCHEMA = {"type": "array", "items": {"type": "string"}, "maxItems": 100, "default": []}
DATES_SCHEMA = {"type": "array", "items": {"type": "string"}, "maxItems": 366, "default": []}


def _service() -> FilterService:
    """Build the filter service over the data directory of the running server.

    Returns:
        The service.
    """
    return FilterService(_catalog, os.environ.get("ONEDRIVE_BACKUP_DATA", "/data"))


class BackupFilterOptions(CatalogCommand):
    """The sites that have indexed snapshots and the backup dates of the ticked sites.

    Attributes:
        name: The command name.
        descr: The one-line description.
    """

    name = "backup_filter_options"
    descr = "List the sites and backup dates available to the file filter."

    async def execute(self, site_ids: list[str] | None = None, **kwargs: Any) -> CommandResult:
        """Read the filter options from the file name index.

        Args:
            site_ids: The ticked site ids; none means all sites.
            kwargs: Ignored extra keyword arguments of the adapter.

        Returns:
            The sites, the dates, the time zone and the index state.
        """
        return await self.apply(_service().filter_options, site_ids=site_ids)

    @classmethod
    def get_schema(cls) -> dict:
        """Describe the optional site filter.

        Returns:
            The JSON schema.
        """
        return cls._schema_with_descriptions({
            "type": "object", "properties": {"site_ids": dict(SITE_IDS_SCHEMA)}, "additionalProperties": False,
        })


class BackupSearchFiles(CatalogCommand):
    """One page of the files of the ticked sites and dates whose name matches.

    Attributes:
        name: The command name.
        descr: The one-line description.
    """

    name = "backup_search_files"
    descr = "Search the files of the backups by site, backup date and name part."

    async def execute(
        self, site_ids: list[str] | None = None, dates: list[str] | None = None, name_part: str = "",
        limit: int = 100, offset: int = 0, **kwargs: Any,
    ) -> CommandResult:
        """Search the file name index.

        Args:
            site_ids: The ticked site ids.
            dates: The ticked backup dates.
            name_part: The name part, star is a wildcard.
            limit: Page size.
            offset: Rows to skip.
            kwargs: Ignored extra keyword arguments of the adapter.

        Returns:
            The page, the total and the index state.
        """
        return await self.apply(
            _service().search_files, site_ids=site_ids, dates=dates, name_part=name_part, limit=limit, offset=offset
        )

    @classmethod
    def get_schema(cls) -> dict:
        """Describe the filters and the paging.

        Returns:
            The JSON schema.
        """
        return cls._schema_with_descriptions({
            "type": "object",
            "properties": {
                "site_ids": dict(SITE_IDS_SCHEMA),
                "dates": dict(DATES_SCHEMA),
                "name_part": {"type": "string", "default": ""},
                "limit": {"type": "integer", "minimum": 1, "maximum": 500, "default": 100},
                "offset": {"type": "integer", "minimum": 0, "maximum": 1000000, "default": 0},
            },
            "additionalProperties": False,
        })


class BackupSuggestNames(CatalogCommand):
    """Distinct file names for the autocomplete list of the name field.

    Attributes:
        name: The command name.
        descr: The one-line description.
    """

    name = "backup_suggest_names"
    descr = "Suggest file names for the typed text."

    async def execute(
        self, text: str = "", site_ids: list[str] | None = None, dates: list[str] | None = None,
        limit: int = 10, **kwargs: Any,
    ) -> CommandResult:
        """Suggest names from the file name index.

        Args:
            text: The typed text.
            site_ids: The ticked site ids.
            dates: The ticked backup dates.
            limit: Maximum names.
            kwargs: Ignored extra keyword arguments of the adapter.

        Returns:
            The names, the trimmed text and the truncation flag.
        """
        return await self.apply(_service().suggest_names, text=text, site_ids=site_ids, dates=dates, limit=limit)

    @classmethod
    def get_schema(cls) -> dict:
        """Describe the required text and the filters.

        Returns:
            The JSON schema.
        """
        return cls._schema_with_descriptions({
            "type": "object",
            "properties": {
                "text": {"type": "string"},
                "site_ids": dict(SITE_IDS_SCHEMA),
                "dates": dict(DATES_SCHEMA),
                "limit": {"type": "integer", "minimum": 1, "maximum": 20, "default": 10},
            },
            "required": ["text"],
            "additionalProperties": False,
        })
