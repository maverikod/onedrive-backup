"""The three filter commands over the file name index: backup_filter_options, backup_search_files, backup_suggest_names.

Matrix 10.19.3 to 10.19.6. The commands read only the index, the discovery inventory (names are joined at query time, the
index stores keys) and one cached list of the restic snapshots that tells how many snapshots are not indexed yet.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import date, datetime, timezone
import hashlib
import os
from pathlib import Path
import re
import time
from typing import Any
from zoneinfo import ZoneInfo

from .catalog import Catalog
from .file_index import FileIndex
from .file_index_build import ensure_catchup, sharepoint_snapshots
from .folder_tree import Scope, build_children, drive_keys, parse_scope, path_chain
from .name_match import MIN_SUGGEST_CHARS, Pattern, PatternError, key, parse_pattern
from .sharepoint_base import DiscoveryError
from .sharepoint_discovery import SharePointInventory

TZ_ENV = "ONEDRIVE_UI_TIMEZONE"
DEFAULT_TZ = "Europe/Kyiv"
SITE_ID = re.compile(r"^[A-Za-z0-9_,.!@-]{1,300}$")
DAY = re.compile(r"^[0-9]{4}-[0-9]{2}-[0-9]{2}$")
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


def check_site_ids(value: object) -> list[str]:
    """Validate the site_ids parameter.

    Args:
        value: The parameter value.

    Returns:
        The ids.

    Raises:
        DiscoveryError: INVALID_SITE_ID (400) for a malformed or duplicate id.
    """
    ids = value if isinstance(value, list) else []
    good = all(isinstance(item, str) and SITE_ID.fullmatch(item) for item in ids)
    if len(ids) > 100 or len(set(map(str, ids))) != len(ids) or not good:
        raise DiscoveryError("INVALID_SITE_ID", 400)
    return list(ids)


def check_dates(value: object) -> list[str]:
    """Validate the dates parameter.

    Args:
        value: The parameter value.

    Returns:
        The ISO dates.

    Raises:
        DiscoveryError: INVALID_DATE (400) for a malformed, impossible or duplicate date.
    """
    days = value if isinstance(value, list) else []
    try:
        for item in days:
            if not isinstance(item, str) or not DAY.fullmatch(item):
                raise ValueError(item)
            date.fromisoformat(item)
    except ValueError as exc:
        raise DiscoveryError("INVALID_DATE", 400) from exc
    if len(days) > 366 or len(set(days)) != len(days):
        raise DiscoveryError("INVALID_DATE", 400)
    return list(days)


def check_pattern(value: object, suggest: bool = False) -> Pattern:
    """Parse a name part and apply the suggestion minimum when asked.

    Args:
        value: The name_part or text parameter.
        suggest: True for backup_suggest_names, which needs two characters that are not stars.

    Returns:
        The parsed pattern.

    Raises:
        DiscoveryError: INVALID_NAME_PART (400).
    """
    try:
        pattern = parse_pattern(value)
    except PatternError as exc:
        raise DiscoveryError("INVALID_NAME_PART", 400) from exc
    if suggest and pattern.literal < MIN_SUGGEST_CHARS:
        raise DiscoveryError("INVALID_NAME_PART", 400)
    return pattern


class FilterService:
    """Reads of the file name index for the three filter commands.

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

    def _chosen(self, site_ids: list[str], dates: list[str]) -> list[dict[str, Any]]:
        """Select the indexed snapshots: any ticked site AND any ticked date, an empty group restricts nothing.

        Args:
            site_ids: The ticked site ids.
            dates: The ticked dates.

        Returns:
            The matching index rows.
        """
        keys = {site_key(item) for item in site_ids}
        return [
            row for row in self.index.snapshots()
            if (not keys or row["site_key"] in keys) and (not dates or self._day(row["time_utc"]) in dates)
        ]

    def filter_options(self, site_ids: object = None) -> dict[str, Any]:
        """The sites that have indexed snapshots and the dates of the ticked sites.

        Args:
            site_ids: The ticked site ids; none means all sites.

        Returns:
            The result of backup_filter_options.
        """
        ids = check_site_ids(site_ids)
        self._gate()
        names, _ = self._names()
        state = self._state()
        per_site: dict[str, list[str]] = {}
        for row in self.index.snapshots():
            per_site.setdefault(row["site_key"], []).append(row["time_utc"])
        sites: list[dict[str, Any]] = [
            {"site_id": names[k][0], "name": names[k][1], "snapshot_count": len(times), "last_snapshot_time": max(times)}
            for k, times in per_site.items() if k in names
        ]
        sites.sort(key=lambda item: (key(item["name"]), item["name"]))
        days: dict[str, int] = {}
        for row in self._chosen(ids, []):
            day = self._day(row["time_utc"])
            days[day] = days.get(day, 0) + 1
        dates = [{"date": day, "snapshot_count": days[day]} for day in sorted(days, reverse=True)]
        return {"sites": sites, "dates": dates, "timezone": self.zone.key, "index": state}

    def search_files(
        self, site_ids: object, dates: object, name_part: object, limit: int, offset: int,
        site_id: object = None, drive_id: object = None, folder: object = None, recursive: object = None,
    ) -> dict[str, Any]:
        """One page of the files of the ticked sites and dates whose name matches, inside the folder scope when given.

        Args:
            site_ids: The ticked site ids.
            dates: The ticked dates.
            name_part: The name part with the star wildcard.
            limit: Page size, 1..500.
            offset: Rows to skip, 0..1000000.
            site_id: The scope site, or None.
            drive_id: The scope library (needs site_id), or None.
            folder: The scope folder (needs drive_id), or None.
            recursive: True takes the whole subtree of the folder (needs drive_id), or None.

        Returns:
            The result of backup_search_files.
        """
        scope = parse_scope(site_id, drive_id, folder, recursive)
        ids, days, pattern = check_site_ids(site_ids), check_dates(dates), check_pattern(name_part)
        self._gate()
        names, libraries = self._names()
        state = self._state()
        chosen = scoped_snapshots(self, ids, days, scope)
        order = sorted({row["site_key"] for row in chosen}, key=lambda k: key(names.get(k, ("", ""))[1]))
        snapshots = [row["snapshot_id"] for row in chosen]
        total, rows = self.index.search(snapshots, pattern, order, limit, offset, scope.rows())
        items = []
        for row in rows:
            sk, dk, where = row["site_key"], row["drive_key"], row["dir"]
            drive, library = libraries.get((sk, dk), (dk, ""))
            items.append({
                "site_id": names.get(sk, (sk, ""))[0], "site_name": names.get(sk, ("", ""))[1],
                "library_name": library, "drive_id": drive, "name": row["name"], "dir": where, "size": row["size"],
                "mtime": row["mtime"], "snapshot_id": row["snapshot_id"], "snapshot_time": row["time_utc"],
                "file_path": "sharepoint/%s/%s/%s%s" % (sk, dk, where + "/" if where else "", row["stored"]),
                "is_copy": row["copy_index"] > 0, "copy_index": row["copy_index"],
            })
        return {"items": items, "total": total, "offset": offset, "limit": limit, "timezone": self.zone.key, "index": state}

    def suggest_names(
        self, text: object, site_ids: object, dates: object, limit: int,
        site_id: object = None, drive_id: object = None, folder: object = None, recursive: object = None,
    ) -> dict[str, Any]:
        """Distinct file names for the autocomplete list, prefix matches first, inside the folder scope when given.

        Args:
            text: The typed text, at least two characters that are not stars.
            site_ids: The ticked site ids.
            dates: The ticked dates.
            limit: Maximum names, 1..20.
            site_id: The scope site, or None.
            drive_id: The scope library (needs site_id), or None.
            folder: The scope folder (needs drive_id), or None.
            recursive: True takes the whole subtree of the folder (needs drive_id), or None.

        Returns:
            The result of backup_suggest_names.
        """
        scope = parse_scope(site_id, drive_id, folder, recursive)
        pattern = check_pattern(text, suggest=True)
        ids, days = check_site_ids(site_ids), check_dates(dates)
        self._gate()
        chosen = scoped_snapshots(self, ids, days, scope)
        names, more = self.index.suggest([row["snapshot_id"] for row in chosen], pattern, limit, scope.rows())
        return {"items": [{"name": name} for name in names], "text": pattern.text, "truncated": more}


def scoped_snapshots(service: FilterService, ids: list[str], days: list[str], scope: Scope) -> list[dict[str, Any]]:
    """Select the indexed snapshots of the filters, narrowed to the site and the library of the scope.

    Args:
        service: The filter service.
        ids: The ticked site ids.
        days: The ticked dates.
        scope: The folder scope.

    Returns:
        The matching index rows.
    """
    rows = service._chosen(ids, days)
    if scope.site_id is not None:
        wanted = site_key(scope.site_id)
        rows = [row for row in rows if row["site_key"] == wanted]
    if scope.drive_id is not None:
        keys = drive_keys(scope.drive_id)
        rows = [row for row in rows if row["drive_key"] in keys]
    return rows


def folder_children(
    service: FilterService, site_ids: object, dates: object, name_part: object, site_id: object, drive_id: object,
    folder: object, limit: int, offset: int,
) -> dict[str, Any]:
    """One page of the children of a node of the folder tree site -> library -> folders, with their file counts.

    Args:
        service: The filter service.
        site_ids: The ticked site ids.
        dates: The ticked dates.
        name_part: The name part with the star wildcard.
        site_id: The site of the parent, or None for the roots.
        drive_id: The library of the parent (needs site_id), or None.
        folder: The folder of the parent (needs drive_id), '' for the library root, or None.
        limit: Page size, 1..500.
        offset: Children to skip, 0..100000.

    Returns:
        The result of backup_folder_children.
    """
    scope = parse_scope(site_id, drive_id, folder, None)
    ids, days, pattern = check_site_ids(site_ids), check_dates(dates), check_pattern(name_part)
    service._gate()
    names, libraries = service._names()
    state = service._state()
    chosen = scoped_snapshots(service, ids, days, scope)
    nodes = build_children(service.index, chosen, pattern, scope, names, libraries)
    site_name, library_name = "", ""
    if scope.site_id is not None:
        owner = site_key(scope.site_id)
        site_name = names.get(owner, ("", ""))[1]
        for wanted in drive_keys(scope.drive_id or ""):
            library_name = library_name or libraries.get((owner, wanted), ("", ""))[1]
    return {
        "nodes": nodes[offset: offset + limit], "total": len(nodes), "offset": offset, "limit": limit,
        "path": path_chain(scope, site_name, library_name), "timezone": service.zone.key, "index": state,
    }
