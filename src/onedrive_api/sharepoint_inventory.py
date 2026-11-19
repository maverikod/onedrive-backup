"""Atomic private storage of the last complete SharePoint inventory."""

from __future__ import annotations

import json
import os
from pathlib import Path
import stat
import tempfile
from typing import Any

from .sharepoint_base import DiscoveryError, IDENTIFIER, MAX_ITEMS


class SharePointInventory:
    """Atomic private storage of the last complete Graph inventory."""

    def __init__(self, directory: str | Path) -> None:
        """Configure private inventory paths without creating directories."""
        self.directory = Path(directory)
        self.inventory_path = self.directory / "inventory.json"
        self.status_path = self.directory / "discovery-status.json"

    @staticmethod
    def _read(path: Path) -> dict[str, Any] | None:
        """Read only bounded regular private files.

        Args:
            path: Inventory or status file.

        Returns:
            Parsed JSON or None when not present.
        """
        try:
            meta = path.lstat()
            if not stat.S_ISREG(meta.st_mode):
                raise DiscoveryError("INVENTORY_FILE_UNSAFE")
            if stat.S_IMODE(meta.st_mode) & 0o077:
                raise DiscoveryError("INVENTORY_PERMISSIONS_UNSAFE")
            if meta.st_size > 16 * 1024 * 1024:
                raise DiscoveryError("INVENTORY_TOO_LARGE")
            data = json.loads(path.read_text(encoding="utf-8"))
        except FileNotFoundError:
            return None
        except (OSError, ValueError) as exc:
            raise DiscoveryError("INVENTORY_INVALID") from exc
        if not isinstance(data, dict):
            raise DiscoveryError("INVENTORY_INVALID")
        return data

    def _write(self, path: Path, value: dict[str, Any]) -> None:
        """Write through a private temporary file and atomic replace."""
        if self.directory.is_symlink() or path.is_symlink():
            raise DiscoveryError("INVENTORY_PATH_UNSAFE")
        self.directory.mkdir(mode=0o700, parents=True, exist_ok=True)
        self.directory.chmod(0o700)
        name = ""
        try:
            with tempfile.NamedTemporaryFile(
                mode="w", encoding="utf-8", dir=self.directory,
                prefix=".discovery-", delete=False
            ) as handle:
                name = handle.name
                os.fchmod(handle.fileno(), 0o600)
                json.dump(value, handle, ensure_ascii=False)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(name, path)
        except OSError as exc:
            raise DiscoveryError("INVENTORY_WRITE_FAILED") from exc
        finally:
            if name:
                Path(name).unlink(missing_ok=True)

    def record(self, report: dict[str, Any]) -> None:
        """Persist coverage on every scan, inventory only on full success."""
        status = {
            "complete": report["complete"],
            "checked_at": report["checked_at"],
            "coverage": report["coverage"],
            "errors": report["errors"],
        }
        if report["complete"]:
            self._write(self.inventory_path, report)
        self._write(self.status_path, status)

    def status(self) -> dict[str, Any]:
        """Return explicit readiness without exposing saved library names."""
        status = self._read(self.status_path)
        if status is None:
            return {
                "complete": False, "ready": False,
                "state": "NOT_DISCOVERED",
            }
        has_inventory = self._read(self.inventory_path) is not None
        return {
            **status,
            "ready": bool(status.get("complete") and has_inventory),
            "state": (
                "READY" if status.get("complete") and has_inventory
                else "DISCOVERY_INCOMPLETE"
            ),
        }

    @staticmethod
    def _page(
        rows: list[dict[str, Any]], limit: int, offset: int
    ) -> dict[str, Any]:
        """Return validated stable-offset inventory pagination."""
        if type(limit) is not int or not 1 <= limit <= 1000:
            raise DiscoveryError("INVALID_LIMIT", 400)
        if type(offset) is not int or not 0 <= offset <= MAX_ITEMS:
            raise DiscoveryError("INVALID_OFFSET", 400)
        return {
            "items": rows[offset:offset + limit],
            "total": len(rows),
            "offset": offset,
            "limit": limit,
        }

    def _ready_inventory(self) -> dict[str, Any]:
        """Reject cached inventory after a failed or incomplete attempt."""
        if not self.status()["ready"]:
            raise DiscoveryError("SOURCE_NOT_READY")
        data = self._read(self.inventory_path)
        if data is None or not data.get("complete"):
            raise DiscoveryError("SOURCE_NOT_READY")
        return data

    @staticmethod
    def check_query(query: Any) -> None:
        """Refuse a malformed site filter before any readiness decision."""
        if not isinstance(query, str) or len(query) > 128:
            raise DiscoveryError("INVALID_QUERY", 400)

    @staticmethod
    def check_site_id(site_id: Any) -> None:
        """Refuse a malformed site identifier before any readiness decision."""
        if not isinstance(site_id, str) or not IDENTIFIER.fullmatch(site_id):
            raise DiscoveryError("INVALID_SITE_ID", 400)

    def sites(
        self, limit: int = 100, offset: int = 0, query: str = ""
    ) -> dict[str, Any]:
        """List verified sites from the last complete scan."""
        self.check_query(query)
        data = self._ready_inventory()
        rows = data["sites"]
        if query:
            value = query.casefold()
            rows = [
                row for row in rows
                if value in row["display_name"].casefold()
                or value in row["web_url"].casefold()
            ]
        return self._page(rows, limit, offset)

    def libraries(
        self, site_id: str, limit: int = 100, offset: int = 0
    ) -> dict[str, Any]:
        """List document libraries for a stable SharePoint site ID."""
        self.check_site_id(site_id)
        data = self._ready_inventory()
        if site_id not in {
            site["site_id"] for site in data["sites"]
        }:
            raise DiscoveryError("SITE_NOT_FOUND", 404)
        rows = [
            row for row in data["libraries"]
            if row["site_id"] == site_id
        ]
        return self._page(rows, limit, offset)
