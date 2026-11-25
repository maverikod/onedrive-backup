"""The three filter commands over the file name index: backup_filter_options, backup_search_files, backup_suggest_names.

Matrix 10.19.3 to 10.19.6. The commands read only the index, the discovery inventory (names are joined at query time, the
index stores keys) and one cached list of the restic snapshots that tells how many snapshots are not indexed yet.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime, timezone
import hashlib
import os
from pathlib import Path
import time
from typing import Any
from zoneinfo import ZoneInfo

from .catalog import Catalog
from .file_index import FileIndex
from .file_index_build import ensure_catchup, sharepoint_snapshots
from . import search_query
from .sharepoint_base import DiscoveryError
from .sharepoint_discovery import SharePointInventory

TZ_ENV = "ONEDRIVE_UI_TIMEZONE"
DEFAULT_TZ = "Europe/Kyiv"
LISTING_TTL = 20.0
_LISTING: dict[str, Any] = {"at": -1e9, "ids": []}


def site_key(site_id: str) -> str:
    """Return the stable key of a site id, as the backup writes it into the snapshot tags.

    Args:
        site_id: The Graph site id.

    Returns:
        The lowercase hex SHA-256 of the id.
    """
    return hashlib.sha256(site_id.encode("utf-8")).hexdigest()


class FilterService:
    """Reads of the file name index for the four filter commands.

    Attributes:
        make_catalog: Factory of the restic catalogue.
        data_dir: The service data directory.
        index: The name index.
        zone: The time zone of the backup dates.
    """

    def __init__(self, make_catalog: Callable[[], Catalog], data_dir: str | Path) -> None:
        """Bind the service to its catalogue factory and data directory.

        Args:
            make_catalog: Callable that returns a Catalog.
            data_dir: The service data directory.
        """
        self.make_catalog = make_catalog
        self.data_dir = Path(data_dir)
        self.index = FileIndex(self.data_dir)
        self.zone = ZoneInfo(os.environ.get(TZ_ENV) or DEFAULT_TZ)

    def _gate(self) -> None:
        """Refuse in scaffold mode.

        Returns:
            None.

        Raises:
            DiscoveryError: SCAFFOLD_ONLY (503).
        """
        if os.environ.get("ONEDRIVE_SCAFFOLD_MODE") == "1":
            raise DiscoveryError("SCAFFOLD_ONLY", 503)

    def _names(self) -> tuple[dict[str, tuple[str, str]], dict[tuple[str, str], tuple[str, str]]]:
        """Read the display names of the discovery inventory, keyed like the snapshot tags.

        Returns:
            Site key to (site id, label) and (site key, library key) to (library id, library name).

        Raises:
            DiscoveryError: SOURCE_NOT_READY (503) when the inventory is not ready.
        """
        data = SharePointInventory(self.data_dir / "sharepoint")._ready_inventory()
        sites = {}
        for row in data["sites"]:
            sites[site_key(row["site_id"])] = (row["site_id"], row["display_name"] or row["web_url"] or row["site_id"])
        libraries: dict[tuple[str, str], tuple[str, str]] = {}
        for row in data["libraries"]:
            pair = (site_key(row["site_id"]), site_key(row["drive_id"]))
            libraries[pair] = (str(row["drive_id"]), str(row.get("display_name", "")))
        return sites, libraries

    def _state(self) -> dict[str, Any]:
        """Compare the snapshots of restic (cached for 20 s) with the indexed ones and start the catch-up when needed.

        Returns:
            The index object of the results: complete, snapshots_total, snapshots_indexed.
        """
        if time.monotonic() - _LISTING["at"] > LISTING_TTL:
            _LISTING["ids"] = [row["id"] for row in sharepoint_snapshots(self.make_catalog())]
            _LISTING["at"] = time.monotonic()
        wanted = set(_LISTING["ids"])
        have = len(wanted & {row["snapshot_id"] for row in self.index.snapshots()})
        if have < len(wanted):
            ensure_catchup(self.make_catalog, self.index)
        return {"complete": have == len(wanted), "snapshots_total": len(wanted), "snapshots_indexed": have}

    def _day(self, time_utc: str) -> str:
        """Return the calendar date of a snapshot time in the service time zone.

        Args:
            time_utc: A normalised UTC time stamp.

        Returns:
            The ISO date.
        """
        moment = datetime.strptime(time_utc, "%Y-%m-%dT%H:%M:%S.%fZ").replace(tzinfo=timezone.utc)
        return moment.astimezone(self.zone).date().isoformat()

    def filter_options(self, site_ids: object = None) -> dict[str, Any]:
        """The sites that have indexed snapshots, the dates of the ticked sites and the latest selection.

        Args:
            site_ids: The ticked site ids; none means all sites.

        Returns:
            The result of backup_filter_options.
        """
        return search_query.filter_options(self, site_ids)

    def search_files(self, **params: Any) -> dict[str, Any]:
        """One page of the files of the chosen snapshots whose name matches.

        Args:
            params: The parameters of backup_search_files, the folder as folder.

        Returns:
            The result of backup_search_files.
        """
        return search_query.search_files(self, params)

    def suggest_names(self, **params: Any) -> dict[str, Any]:
        """Distinct file names for the autocomplete list.

        Args:
            params: The parameters of backup_suggest_names, the folder as folder.

        Returns:
            The result of backup_suggest_names.
        """
        return search_query.suggest_names(self, params)

    def folder_children(self, **params: Any) -> dict[str, Any]:
        """One page of the children of a node of the folder tree.

        Args:
            params: The parameters of backup_folder_children, the folder as folder.

        Returns:
            The result of backup_folder_children.
        """
        return search_query.folder_children(self, params)
