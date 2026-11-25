"""The date-aware reads of the filter commands (matrix 10.22.2, 10.22.6.4 to 10.22.6.6).

backup_search_files, backup_suggest_names, backup_filter_options and backup_folder_children choose their snapshots by the
one selection function of date_scope, so the same (site_ids, dates, dates_mode) reads the same snapshots everywhere.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import TYPE_CHECKING, Any

from .date_scope import check_date_scope, check_dates, check_site_ids, select
from .file_address import make_file_id
from .file_collapse import search_rows
from .folder_tree import Scope, build_children, digest, drive_keys, parse_scope, path_chain
from .name_match import MIN_SUGGEST_CHARS, Pattern, PatternError, key, parse_pattern
from .sharepoint_base import DiscoveryError

if TYPE_CHECKING:
    from .filter_service import FilterService

FIELDS = (
    "site_id", "site_name", "library_name", "drive_id", "name", "ext", "dir", "size", "mtime", "snapshot_id",
    "snapshot_time", "snapshot_time_local", "snapshot_date", "file_path", "file_id", "is_copy", "copy_index",
    "backup_type", "trigger", "run_id", "snapshot_count", "first_date", "last_date", "version_count",
)
FIELDS_HINT = "Name each item key once; the allowed keys are listed in error.data.allowed."
STAMP = "%Y-%m-%dT%H:%M:%S.%fZ"


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


def check_fields(value: object) -> list[str] | None:
    """Validate the fields parameter against the item keys.

    Args:
        value: The parameter value, None when absent.

    Returns:
        The requested keys in the requested order, or None for every key.

    Raises:
        DiscoveryError: INVALID_FIELDS (400) for an unknown or repeated key; error.data.allowed lists the keys.
    """
    if not isinstance(value, list):
        return None
    for index, name in enumerate(value):
        if name not in FIELDS or value.index(name) != index:
            data = {
                "field": "fields", "index": index, "value": str(name)[:64], "expected": "an item key, once",
                "hint": FIELDS_HINT, "allowed": list(FIELDS),
            }
            raise DiscoveryError("INVALID_FIELDS", 400, data)
    return list(value)


def extension(name: str) -> str:
    """Return the lower-case extension of a file name, '' when it has none.

    Args:
        name: The shown file name.

    Returns:
        The extension without the dot.
    """
    return name.rsplit(".", 1)[1].lower() if "." in name.lstrip(".") else ""


def _item(service: FilterService, row: dict[str, Any], names: dict[str, Any], libraries: dict[Any, Any]) -> dict[str, Any]:
    """Build one result item of backup_search_files (10.22.6.5).

    Args:
        service: The filter service.
        row: One row of the collapsed search.
        names: Site key to (site id, label).
        libraries: (site key, library key) to (drive id, label).

    Returns:
        The item with the 0.3.27 keys and the keys of revision 14.
    """
    sk, dk, where = row["site_key"], row["drive_key"], row["dir"]
    drive, library = libraries.get((sk, dk), (dk, ""))
    path = "sharepoint/%s/%s/%s%s" % (sk, dk, where + "/" if where else "", row["stored"])
    moment = datetime.strptime(row["time_utc"], STAMP).replace(tzinfo=timezone.utc).astimezone(service.zone)
    day = moment.date().isoformat()
    return {
        "site_id": names.get(sk, (sk, ""))[0], "site_name": names.get(sk, ("", ""))[1], "library_name": library,
        "drive_id": drive, "name": row["name"], "ext": extension(row["name"]), "dir": where, "size": row["size"],
        "mtime": row["mtime"], "snapshot_id": row["snapshot_id"], "snapshot_time": row["time_utc"],
        "snapshot_time_local": moment.isoformat(timespec="seconds"), "snapshot_date": day, "file_path": path,
        "file_id": make_file_id(row["snapshot_id"], path), "is_copy": row["copy_index"] > 0,
        "copy_index": row["copy_index"], "backup_type": row["backup_type"] or "full",
        "trigger": row["trigger"] or "unknown", "run_id": row["run_id"] or "", "snapshot_count": row["snapshot_count"],
        "first_date": service._day(row["first_time"]), "last_date": service._day(row["last_time"]),
        "version_count": row["version_count"],
    }


def search_files(service: FilterService, params: dict[str, Any]) -> dict[str, Any]:
    """One page of the files of the chosen snapshots whose name matches, collapsed and ordered as asked.

    Args:
        service: The filter service.
        params: site_ids, dates, name_part, limit, offset, the folder scope (site_id, drive_id, folder, recursive),
            dates_mode, collapse, order_by and fields as the command received them.

    Returns:
        The result of backup_search_files.
    """
    scope = parse_scope(params.get("site_id"), params.get("drive_id"), params.get("folder"), params.get("recursive"))
    check_date_scope(params.get("dates"), params.get("dates_mode"))
    ids, days = check_site_ids(params.get("site_ids")), check_dates(params.get("dates"))
    pattern = check_pattern(params.get("name_part"))
    wanted = check_fields(params.get("fields"))
    service._gate()
    names, libraries = service._names()
    state = service._state()
    chosen = select(service.index.snapshots(), scope, ids, days, params.get("dates_mode"), service._day)
    order = sorted({row["site_key"] for row in chosen.rows}, key=lambda k: key(names.get(k, ("", ""))[1]))
    total, rows = search_rows(
        service.index, [row["snapshot_id"] for row in chosen.rows], pattern, order, params["limit"], params["offset"],
        scope.rows(), params.get("collapse") or "none", params.get("order_by") or "name",
    )
    items = [_item(service, row, names, libraries) for row in rows]
    if wanted:
        items = [{name: item[name] for name in wanted} for item in items]
    return {
        "items": items, "total": total, "offset": params["offset"], "limit": params["limit"],
        "timezone": service.zone.key, "index": state, "date_scope": chosen.date_scope, "warnings": chosen.warnings,
    }


def suggest_names(service: FilterService, params: dict[str, Any]) -> dict[str, Any]:
    """Distinct file names for the autocomplete list, prefix matches first, inside the chosen snapshots.

    Args:
        service: The filter service.
        params: text, site_ids, dates, limit, the folder scope and dates_mode as the command received them.

    Returns:
        The result of backup_suggest_names.
    """
    scope = parse_scope(params.get("site_id"), params.get("drive_id"), params.get("folder"), params.get("recursive"))
    check_date_scope(params.get("dates"), params.get("dates_mode"))
    pattern = check_pattern(params.get("text"), suggest=True)
    ids, days = check_site_ids(params.get("site_ids")), check_dates(params.get("dates"))
    service._gate()
    chosen = select(service.index.snapshots(), scope, ids, days, params.get("dates_mode"), service._day)
    snapshots = [row["snapshot_id"] for row in chosen.rows]
    found, more = service.index.suggest(snapshots, pattern, params["limit"], scope.rows())
    return {"items": [{"name": name} for name in found], "text": pattern.text, "truncated": more, "warnings": chosen.warnings}


def filter_options(service: FilterService, site_ids: object) -> dict[str, Any]:
    """The sites with indexed snapshots, the dates of the ticked sites with their attributes and the latest selection.

    Args:
        service: The filter service.
        site_ids: The ticked site ids; none means all sites.

    Returns:
        The result of backup_filter_options.
    """
    ids = check_site_ids(site_ids)
    service._gate()
    names, _ = service._names()
    state = service._state()
    every = service.index.snapshots()
    per_site: dict[str, list[str]] = {}
    for row in every:
        per_site.setdefault(row["site_key"], []).append(row["time_utc"])
    sites: list[dict[str, Any]] = [
        {"site_id": names[k][0], "name": names[k][1], "snapshot_count": len(times), "last_snapshot_time": max(times)}
        for k, times in per_site.items() if k in names
    ]
    sites.sort(key=lambda item: (key(item["name"]), item["name"]))
    wanted = {digest(item) for item in ids}
    days: dict[str, list[dict[str, Any]]] = {}
    for row in every:
        if not wanted or row["site_key"] in wanted:
            days.setdefault(service._day(row["time_utc"]), []).append(row)
    dates = [
        {
            "date": day, "snapshot_count": len(group),
            "backup_types": sorted({row["backup_type"] or "full" for row in group}),
            "triggers": sorted({row["trigger"] or "unknown" for row in group}),
            "run_count": len({row["run_id"] for row in group}),
            "library_count": len({row["drive_key"] for row in group}),
            "last_snapshot_time": max(row["time_utc"] for row in group),
        }
        for day, group in sorted(days.items(), reverse=True)
    ]
    chosen = select(every, Scope(), ids, [], None, service._day)
    latest = {"dates": chosen.date_scope["dates"], "snapshot_count": chosen.date_scope["snapshot_count"]}
    return {
        "sites": sites, "dates": dates, "timezone": service.zone.key, "index": state, "latest": latest,
        "warnings": chosen.warnings,
    }


def folder_children(service: FilterService, params: dict[str, Any]) -> dict[str, Any]:
    """One page of the children of a node of the folder tree site -> library -> folders, with their file counts.

    Args:
        service: The filter service.
        params: site_ids, dates, name_part, site_id, drive_id, folder, limit, offset, dates_mode and collapse as the
            command received them.

    Returns:
        The result of backup_folder_children.
    """
    scope = parse_scope(params.get("site_id"), params.get("drive_id"), params.get("folder"), None)
    check_date_scope(params.get("dates"), params.get("dates_mode"))
    ids, days = check_site_ids(params.get("site_ids")), check_dates(params.get("dates"))
    pattern = check_pattern(params.get("name_part"))
    service._gate()
    names, libraries = service._names()
    state = service._state()
    chosen = select(service.index.snapshots(), scope, ids, days, params.get("dates_mode"), service._day)
    collapse = params.get("collapse") or "none"
    nodes = build_children(service.index, chosen.rows, pattern, scope, names, libraries, collapse)
    site_name, library_name = "", ""
    if scope.site_id is not None:
        owner = digest(scope.site_id)
        site_name = names.get(owner, ("", ""))[1]
        for wanted in drive_keys(scope.drive_id or ""):
            library_name = library_name or libraries.get((owner, wanted), ("", ""))[1]
    offset, limit = params["offset"], params["limit"]
    return {
        "nodes": nodes[offset: offset + limit], "total": len(nodes), "offset": offset, "limit": limit,
        "path": path_chain(scope, site_name, library_name), "timezone": service.zone.key, "index": state,
        "date_scope": chosen.date_scope, "warnings": chosen.warnings,
    }
