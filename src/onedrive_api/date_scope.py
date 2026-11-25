"""Date scope of the filter commands (matrix 10.22.2.1, 10.22.6.10, RD1, RD2): which snapshots a request reads.

One selection function serves backup_filter_options, backup_search_files, backup_suggest_names and backup_folder_children,
so the same (site_ids, dates, dates_mode) always chooses the same snapshots. An empty or absent dates selects the newest
snapshot of every library (dates_mode 'latest', the default) or every snapshot (dates_mode 'all').
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import date
import re
from typing import Any

from .folder_tree import Scope, digest, drive_keys
from .sharepoint_base import DiscoveryError

SITE_ID = re.compile(r"^[A-Za-z0-9_,.!@-]{1,300}$")
DAY = re.compile(r"^[0-9]{4}-[0-9]{2}-[0-9]{2}$")
SITE_EXPECTED = "^[A-Za-z0-9_,.!@-]{1,300}$"
SITE_HINT = "Take the site_id from backup_sites_list; letters, digits and _,.!@- only, each id once, at most 100."
DATE_HINT = "Take dates from backup_filter_options.dates: local calendar days written YYYY-MM-DD, each once, at most 366."
SCOPE_HINT = "Send either dates (explicit local days) or dates_mode ('latest' or 'all'), not both."
MAX_SITES = 100
MAX_DATES = 366


@dataclass
class Selection:
    """The snapshots a request reads.

    Attributes:
        rows: The chosen index rows.
        date_scope: mode (latest, all or dates), the local dates of the chosen snapshots and their number.
        warnings: The additive warnings of the request.
    """

    rows: list[dict[str, Any]]
    date_scope: dict[str, Any]
    warnings: list[dict[str, Any]]


def _refuse(code: str, field: str, index: int, value: object, expected: str, hint: str) -> DiscoveryError:
    """Build a 400 error whose error.data names the offending list item (RM6).

    Args:
        code: The error code, which is the message.
        field: The parameter.
        index: The position of the item.
        value: The item, cut to 64 characters.
        expected: What an item must be.
        hint: What to do next.

    Returns:
        The error to raise.
    """
    data = {"field": field, "index": index, "value": str(value)[:64], "expected": expected, "hint": hint}
    return DiscoveryError(code, 400, data)


def check_site_ids(value: object) -> list[str]:
    """Validate the site_ids parameter.

    Args:
        value: The parameter value.

    Returns:
        The ids.

    Raises:
        DiscoveryError: INVALID_SITE_ID (400) for a malformed or duplicate id, error.data names its index.
    """
    ids = list(value) if isinstance(value, list) else []
    seen: set[str] = set()
    for index, item in enumerate(ids):
        if not isinstance(item, str) or not SITE_ID.fullmatch(item) or item in seen or index >= MAX_SITES:
            raise _refuse("INVALID_SITE_ID", "site_ids", index, item, SITE_EXPECTED, SITE_HINT)
        seen.add(item)
    return ids


def check_dates(value: object) -> list[str]:
    """Validate the dates parameter.

    Args:
        value: The parameter value.

    Returns:
        The ISO dates.

    Raises:
        DiscoveryError: INVALID_DATE (400) for a malformed, impossible or duplicate date, error.data names its index.
    """
    days = list(value) if isinstance(value, list) else []
    seen: set[str] = set()
    for index, item in enumerate(days):
        problem = ""
        if not isinstance(item, str) or not DAY.fullmatch(item):
            problem = "%r is not written YYYY-MM-DD." % (item,)
        elif item in seen or index >= MAX_DATES:
            problem = "%r repeats or exceeds the 366 dates allowed." % (item,)
        else:
            try:
                date.fromisoformat(item)
            except ValueError:
                problem = "%r is not a day of the calendar." % (item,)
        if problem:
            raise _refuse("INVALID_DATE", "dates", index, item, "YYYY-MM-DD", problem + " " + DATE_HINT)
        seen.add(item)
    return days


def check_date_scope(dates: object, dates_mode: object) -> None:
    """Refuse explicit dates together with dates_mode (RD1).

    Args:
        dates: The dates parameter.
        dates_mode: The dates_mode parameter, None when absent.

    Returns:
        None.

    Raises:
        DiscoveryError: INVALID_DATE_SCOPE (400) with error.data.fields ['dates', 'dates_mode'].
    """
    if isinstance(dates, list) and dates and dates_mode is not None:
        raise DiscoveryError("INVALID_DATE_SCOPE", 400, {"fields": ["dates", "dates_mode"], "hint": SCOPE_HINT})


def narrow(rows: list[dict[str, Any]], scope: Scope) -> list[dict[str, Any]]:
    """Narrow index rows to the site and the library of a folder scope.

    Args:
        rows: The index rows.
        scope: The folder scope.

    Returns:
        The rows of the scope.
    """
    if scope.site_id is not None:
        wanted = digest(scope.site_id)
        rows = [row for row in rows if row["site_key"] == wanted]
    if scope.drive_id is not None:
        keys = drive_keys(scope.drive_id)
        rows = [row for row in rows if row["drive_key"] in keys]
    return rows


def _warning(code: str, field: str, value: str, hint: str) -> dict[str, Any]:
    """Build one warning of 10.22.6.10.

    Args:
        code: The warning code.
        field: The parameter.
        value: The value that matched nothing.
        hint: What to do next.

    Returns:
        The warning.
    """
    return {"code": code, "field": field, "value": value, "hint": hint}


def select(
    all_rows: list[dict[str, Any]], scope: Scope, ids: list[str], days: list[str], mode: str | None,
    day_of: Callable[[str], str],
) -> Selection:
    """Choose the snapshots of a request.

    Args:
        all_rows: Every indexed snapshot.
        scope: The folder scope that narrows the site and the library.
        ids: The ticked site ids.
        days: The explicit local dates, empty for the dates_mode.
        mode: latest, all or None (latest).
        day_of: Maps a UTC snapshot time to its local date.

    Returns:
        The chosen rows, the date_scope and the warnings.
    """
    known = {row["site_key"] for row in all_rows}
    unknown_hint = "No snapshot of this site is indexed; take site_id from backup_sites_list."
    warnings = [_warning("UNKNOWN_SITE_ID", "site_ids", item, unknown_hint) for item in ids if digest(item) not in known]
    keys = {digest(item) for item in ids}
    pool = [row for row in narrow(all_rows, scope) if not keys or row["site_key"] in keys]
    if days:
        label = "dates"
        chosen = [row for row in pool if day_of(row["time_utc"]) in days]
        present = {day_of(row["time_utc"]) for row in pool}
        missing_hint = "No snapshot of the chosen sites has this local day; see backup_filter_options.dates."
        warnings += [_warning("NO_SNAPSHOT_FOR_DATE", "dates", item, missing_hint) for item in days if item not in present]
    elif mode == "all":
        label, chosen = "all", pool
    else:
        label = "latest"
        newest: dict[tuple[str, str], dict[str, Any]] = {}
        for row in pool:
            pair = (row["site_key"], row["drive_key"])
            if pair not in newest or row["time_utc"] > newest[pair]["time_utc"]:
                newest[pair] = row
        chosen = list(newest.values())
    dates = sorted({day_of(row["time_utc"]) for row in chosen})
    return Selection(chosen, {"mode": label, "dates": dates, "snapshot_count": len(chosen)}, warnings)
