"""MCP commands of the single filter page: backup_filter_options, backup_search_files, backup_suggest_names (10.19.5)."""

from __future__ import annotations

import os
from functools import partial
from typing import Any
from mcp_proxy_adapter.commands.result import CommandResult

from .commands_base import CatalogCommand, _catalog
from .filter_service import FilterService, folder_children
SCOPE_SCHEMA = {"site_id": {"type": "string"}, "drive_id": {"type": "string"}, "dir": {"type": "string"}}
RECURSIVE_SCHEMA = {"type": "boolean"}

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
    """One page of the files of the ticked sites and dates whose name matches, inside the folder scope when given.

    Attributes:
        name: The command name.
        descr: The one-line description.
    """

    name = "backup_search_files"
    descr = "Search the files of the backups by site, backup date, folder and name part."

    async def execute(
        self, site_ids: list[str] | None = None, dates: list[str] | None = None, name_part: str = "",
        limit: int = 100, offset: int = 0, site_id: str | None = None, drive_id: str | None = None,
        dir: str | None = None, recursive: bool | None = None, **kwargs: Any,
    ) -> CommandResult:
        """Search the file name index.

        Args:
            site_ids: The ticked site ids.
            dates: The ticked backup dates.
            name_part: The name part, star is a wildcard.
            limit: Page size.
            offset: Rows to skip.
            site_id: The scope site.
            drive_id: The scope library of the site.
            dir: The scope folder of the library, '' is the library root.
            recursive: True takes the whole subtree of the folder.
            kwargs: Ignored extra keyword arguments of the adapter.

        Returns:
            The page, the total and the index state.
        """
        return await self.apply(
            _service().search_files, site_ids=site_ids, dates=dates, name_part=name_part, limit=limit, offset=offset,
            site_id=site_id, drive_id=drive_id, folder=dir, recursive=recursive,
        )

    @classmethod
    def get_schema(cls) -> dict:
        """Describe the filters, the folder scope and the paging.

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
                **{name: dict(spec) for name, spec in SCOPE_SCHEMA.items()},
                "recursive": dict(RECURSIVE_SCHEMA),
            },
            "additionalProperties": False,
        })


class BackupSuggestNames(CatalogCommand):
    """Distinct file names for the autocomplete list of the name field, inside the folder scope when given.

    Attributes:
        name: The command name.
        descr: The one-line description.
    """

    name = "backup_suggest_names"
    descr = "Suggest file names for the typed text."

    async def execute(
        self, text: str = "", site_ids: list[str] | None = None, dates: list[str] | None = None,
        limit: int = 10, site_id: str | None = None, drive_id: str | None = None, dir: str | None = None,
        recursive: bool | None = None, **kwargs: Any,
    ) -> CommandResult:
        """Suggest names from the file name index.

        Args:
            text: The typed text.
            site_ids: The ticked site ids.
            dates: The ticked backup dates.
            limit: Maximum names.
            site_id: The scope site.
            drive_id: The scope library of the site.
            dir: The scope folder of the library, '' is the library root.
            recursive: True takes the whole subtree of the folder.
            kwargs: Ignored extra keyword arguments of the adapter.

        Returns:
            The names, the trimmed text and the truncation flag.
        """
        return await self.apply(
            _service().suggest_names, text=text, site_ids=site_ids, dates=dates, limit=limit,
            site_id=site_id, drive_id=drive_id, folder=dir, recursive=recursive,
        )

    @classmethod
    def get_schema(cls) -> dict:
        """Describe the required text, the filters and the folder scope.

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
                **{name: dict(spec) for name, spec in SCOPE_SCHEMA.items()},
                "recursive": dict(RECURSIVE_SCHEMA),
            },
            "required": ["text"],
            "additionalProperties": False,
        })


class BackupFolderChildren(CatalogCommand):
    """The children of one node of the folder tree site -> library -> folders, with their file counts.

    Attributes:
        name: The command name.
        descr: The one-line description.
    """

    name = "backup_folder_children"
    descr = "List the child nodes of a site, library or folder with the number of matching files."

    async def execute(
        self, site_id: str | None = None, drive_id: str | None = None, dir: str | None = None,
        site_ids: list[str] | None = None, dates: list[str] | None = None, name_part: str = "",
        limit: int = 200, offset: int = 0, **kwargs: Any,
    ) -> CommandResult:
        """Read the children of the addressed parent from the file name index.

        Args:
            site_id: The site of the parent; none lists the sites.
            drive_id: The library of the parent; needs site_id.
            dir: The folder of the parent, '' is the library root; needs drive_id.
            site_ids: The ticked site ids.
            dates: The ticked backup dates.
            name_part: The name part, star is a wildcard.
            limit: Page size.
            offset: Children to skip.
            kwargs: Ignored extra keyword arguments of the adapter.

        Returns:
            The nodes, the total, the path to the parent and the index state.
        """
        return await self.apply(
            partial(folder_children, _service()), site_ids=site_ids, dates=dates, name_part=name_part,
            site_id=site_id, drive_id=drive_id, folder=dir, limit=limit, offset=offset,
        )

    @classmethod
    def get_schema(cls) -> dict:
        """Describe the address of the parent, the filters and the paging.

        Returns:
            The JSON schema.
        """
        return cls._schema_with_descriptions({
            "type": "object",
            "properties": {
                **{name: dict(spec) for name, spec in SCOPE_SCHEMA.items()},
                "site_ids": dict(SITE_IDS_SCHEMA),
                "dates": dict(DATES_SCHEMA),
                "name_part": {"type": "string", "default": ""},
                "limit": {"type": "integer", "minimum": 1, "maximum": 500, "default": 200},
                "offset": {"type": "integer", "minimum": 0, "maximum": 100000, "default": 0},
            },
            "additionalProperties": False,
        })
