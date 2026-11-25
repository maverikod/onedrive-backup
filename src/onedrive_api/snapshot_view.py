"""backup_snapshots with the library identity and the run attributes (matrix 10.22.2.5, 10.22.6.2, O-MD5 A).

Every item keeps the restic fields except the host paths and the container hostname, and gains the site and the library the
snapshot belongs to, its local date and time, and backup_type, trigger, run_id and type_source from the file name index.
"""

from __future__ import annotations

from datetime import datetime, timezone
import os
from pathlib import Path
import sqlite3
from typing import Any
from zoneinfo import ZoneInfo

from .catalog import Catalog
from .file_index import FileIndex, utc_time
from .folder_tree import digest
from .sharepoint_base import DiscoveryError
from .sharepoint_discovery import SharePointInventory
from .snapshot_attrs import from_tags

HIDDEN = ("hostname", "paths")
STAMP = "%Y-%m-%dT%H:%M:%S.%fZ"


def _tag(tags: object, prefix: str) -> str:
    """Return the value of the first tag that starts with prefix.

    Args:
        tags: The restic tags.
        prefix: The tag prefix, for example site-.

    Returns:
        The rest of the tag, or the empty string.
    """
    for tag in tags if isinstance(tags, list) else []:
        if isinstance(tag, str) and tag.startswith(prefix):
            return tag[len(prefix):]
    return ""


def _names(data_dir: Path) -> tuple[dict[str, tuple[str, str]], dict[tuple[str, str], tuple[str, str]]]:
    """Read the sites and libraries of the discovery inventory, keyed like the snapshot tags.

    Args:
        data_dir: The service data directory.

    Returns:
        Site key to (site id, label) and (site key, library key) to (library id, label); empty when the inventory is not ready.
    """
    try:
        data = SharePointInventory(data_dir / "sharepoint")._ready_inventory()
    except DiscoveryError:
        return {}, {}
    sites = {
        digest(row["site_id"]): (row["site_id"], row["display_name"] or row["web_url"] or row["site_id"])
        for row in data["sites"]
    }
    libraries = {
        (digest(row["site_id"]), digest(row["drive_id"])): (str(row["drive_id"]), str(row.get("display_name", "")))
        for row in data["libraries"]
    }
    return sites, libraries


def _indexed(data_dir: Path) -> dict[str, dict[str, Any]]:
    """Read the attributes of the indexed snapshots; an unreadable index gives none.

    Args:
        data_dir: The service data directory.

    Returns:
        Snapshot id to its index row.
    """
    try:
        return {row["snapshot_id"]: row for row in FileIndex(data_dir).snapshots()}
    except (OSError, sqlite3.Error):
        return {}


def _moment(value: object, zone: ZoneInfo) -> datetime | None:
    """Convert a restic time stamp to the service time zone.

    Args:
        value: The restic time.
        zone: The service time zone.

    Returns:
        The local time, or None when the stamp does not parse.
    """
    try:
        return datetime.strptime(utc_time(str(value)), STAMP).replace(tzinfo=timezone.utc).astimezone(zone)
    except ValueError:
        return None


def list_snapshots(catalog: Catalog, limit: int = 100) -> dict[str, Any]:
    """List the snapshots newest first with the identity and the attributes of revision 14.

    Args:
        catalog: The restic catalogue.
        limit: Maximum items, 1..1000.

    Returns:
        {items, count} of backup_snapshots.
    """
    result = catalog.snapshots(limit)
    data_dir = Path(os.environ.get("ONEDRIVE_BACKUP_DATA", "/data"))
    zone = ZoneInfo(os.environ.get("ONEDRIVE_UI_TIMEZONE") or "Europe/Kyiv")
    sites, libraries = _names(data_dir)
    indexed = _indexed(data_dir)
    items = []
    for item in result["items"]:
        tags = item.get("tags")
        site, drive = _tag(tags, "site-"), _tag(tags, "drive-")
        local = _moment(item.get("time"), zone)
        known = indexed.get(str(item.get("id", "")).lower()) or from_tags(tags)
        if not known or not known.get("run_id"):
            stamp = utc_time(str(item.get("time", "")))
            legacy = "legacy-" + stamp[:19].translate({45: None, 58: None}) + "Z"
            known = {"backup_type": "full", "trigger": "unknown", "type_source": "derived", "run_id": legacy}
        drive_id, library_name = libraries.get((site, drive), ("", ""))
        items.append({
            **{key: value for key, value in item.items() if key not in HIDDEN},
            "site_id": sites.get(site, ("", ""))[0], "site_name": sites.get(site, ("", ""))[1],
            "library_name": library_name, "drive_id": drive_id,
            "date": local.date().isoformat() if local else "",
            "time_local": local.isoformat(timespec="seconds") if local else "",
            "backup_type": known["backup_type"] or "full", "trigger": known["trigger"] or "unknown",
            "run_id": known["run_id"], "type_source": known["type_source"],
        })
    return {"items": items, "count": result["count"]}
