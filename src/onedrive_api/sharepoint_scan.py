"""Complete or explicitly incomplete SharePoint site and library scan."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any
from urllib.parse import quote

from .sharepoint_base import DiscoveryError, GRAPH_ROOT, IDENTIFIER
from .sharepoint_graph import GraphClient


class SharePointDiscovery:
    """Inventory all accessible SharePoint sites and document libraries."""

    def __init__(self, graph: GraphClient) -> None:
        """Use a Graph client with no SharePoint write privileges."""
        self.graph = graph

    @staticmethod
    def _text(value: Any) -> str:
        """Normalize an untrusted public display name to a bounded string.

        Args:
            value: Graph JSON scalar.

        Returns:
            Safe printable text for a catalogue field.
        """
        return value[:512] if isinstance(value, str) else ""

    def scan(self) -> dict[str, Any]:
        """Construct a complete or explicitly incomplete inventory.

        Returns:
            Inventory with stable IDs, coverage and diagnostic codes.
        """
        scanned_at = datetime.now(timezone.utc).isoformat()
        sites: list[dict[str, Any]] = []
        libraries: list[dict[str, Any]] = []
        errors: list[dict[str, str]] = []
        excluded = 0
        try:
            remote_sites = self.graph.pages(
                GRAPH_ROOT + "/sites/getAllSites"
            )
        except DiscoveryError as exc:
            remote_sites = []
            errors.append({"source": "sites", "code": exc.code})
        found_sites: set[str] = set()
        found_libraries: set[tuple[str, str]] = set()
        for site in remote_sites:
            site_id = site.get("id")
            if not isinstance(site_id, str) or not IDENTIFIER.fullmatch(
                site_id
            ):
                errors.append({
                    "source": "sites", "code": "SITE_ID_INVALID"
                })
                continue
            if site_id in found_sites:
                continue
            found_sites.add(site_id)
            url = self._text(site.get("webUrl"))
            if "-my.sharepoint." in url.lower() or "/personal/" in url.lower():
                excluded += 1
                continue
            site_record: dict[str, Any] = {
                "site_id": site_id,
                "display_name": self._text(
                    site.get("displayName") or site.get("name")
                ),
                "web_url": url,
                "library_count": 0,
                "source_status": "ok",
            }
            sites.append(site_record)
            try:
                drive_list = self.graph.pages(
                    GRAPH_ROOT + "/sites/"
                    + quote(site_id, safe=",") + "/drives"
                )
            except DiscoveryError as exc:
                site_record["source_status"] = "failed"
                errors.append({"source": site_id, "code": exc.code})
                continue
            for drive in drive_list:
                drive_id = drive.get("id")
                if (
                    not isinstance(drive_id, str)
                    or not IDENTIFIER.fullmatch(drive_id)
                ):
                    errors.append({
                        "source": site_id, "code": "DRIVE_ID_INVALID"
                    })
                    continue
                if drive.get("driveType") not in (
                    "documentLibrary", None
                ):
                    continue
                key = (site_id, drive_id)
                if key in found_libraries:
                    continue
                found_libraries.add(key)
                libraries.append({
                    "site_id": site_id,
                    "drive_id": drive_id,
                    "display_name": self._text(drive.get("name")),
                    "web_url": self._text(drive.get("webUrl")),
                    "status": "ok",
                })
                site_record["library_count"] += 1
        sites.sort(key=lambda row: row["site_id"])
        libraries.sort(key=lambda row: (
            row["site_id"], row["drive_id"]
        ))
        return {
            "complete": not errors,
            "checked_at": scanned_at,
            "sites": sites,
            "libraries": libraries,
            "errors": errors,
            "coverage": {
                "sites": len(sites),
                "libraries": len(libraries),
                "excluded_personal_sites": excluded,
                "failed_sources": len(errors),
            },
        }
