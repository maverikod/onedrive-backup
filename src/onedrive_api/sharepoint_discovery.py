"""Fail-closed, read-only Microsoft SharePoint Online discovery.

Enumerate site collections and document libraries with app-only Graph access.
Incomplete scans never replace the last known complete inventory.
"""

from __future__ import annotations

import configparser
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import re
import stat
import tempfile
import time
from typing import Any, Callable
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlencode, urlsplit
from urllib.request import Request, urlopen

GRAPH_ROOT = "https://graph.microsoft.com/v1.0"
IDENTIFIER = re.compile(r"^[A-Za-z0-9_,.!@-]{1,300}$")
GUID = re.compile(r"^[0-9a-fA-F-]{36}$")
MAX_PAGES = 2000
MAX_ITEMS = 200000
MAX_RESPONSE_BYTES = 4 * 1024 * 1024


class DiscoveryError(Exception):
    """Non-sensitive discovery failure for REST and MCP clients."""

    def __init__(self, code: str, status: int = 503) -> None:
        """Record a stable error code without logging Graph response bodies."""
        super().__init__(code)
        self.code = code
        self.status = status


class EntraCredentials:
    """App-only Microsoft Entra credentials held only in process memory."""

    def __init__(self, tenant: str, client_id: str, secret: str) -> None:
        """Validate the identifiers and secret without echoing their values."""
        if not GUID.fullmatch(tenant) or not GUID.fullmatch(client_id):
            raise DiscoveryError("ENTRA_IDENTIFIERS_INVALID")
        if not secret or len(secret) > 8192:
            raise DiscoveryError("ENTRA_SECRET_INVALID")
        self.tenant = tenant
        self.client_id = client_id
        self.secret = secret

    @classmethod
    def from_rclone(cls, path: str | Path) -> EntraCredentials:
        """Read protected rclone remote settings.

        Args:
            path: Absolute path to a private rclone configuration.

        Returns:
            Validated app-only credentials.
        """
        file = Path(path)
        try:
            meta = file.lstat()
            if not stat.S_ISREG(meta.st_mode):
                raise DiscoveryError("CREDENTIALS_FILE_UNSAFE")
            if stat.S_IMODE(meta.st_mode) & 0o077:
                raise DiscoveryError("CREDENTIALS_PERMISSIONS_UNSAFE")
            config = configparser.ConfigParser(interpolation=None)
            with file.open("r", encoding="utf-8") as stream:
                config.read_file(stream)
            if config.get("onedrive", "type") != "onedrive":
                raise DiscoveryError("RCLONE_REMOTE_INVALID")
            if not config.getboolean("onedrive", "client_credentials"):
                raise DiscoveryError("APP_ONLY_REQUIRED")
            return cls(
                config.get("onedrive", "tenant"),
                config.get("onedrive", "client_id"),
                config.get("onedrive", "client_secret"),
            )
        except (OSError, configparser.Error, ValueError) as exc:
            raise DiscoveryError("CREDENTIALS_NOT_CONFIGURED") from exc


def _http_request(
    method: str, url: str, headers: dict[str, str], body: bytes | None
) -> tuple[int, dict[str, Any], dict[str, str]]:
    """Perform a bounded HTTPS request and discard unsafe error bodies.

    Args:
        method: HTTP request method.
        url: Validated Microsoft endpoint.
        headers: Request headers, including private authorization.
        body: Optional encoded OAuth payload.

    Returns:
        HTTP status, JSON object and response headers.
    """
    request = Request(url, data=body, headers=headers, method=method)
    try:
        with urlopen(request, timeout=20) as response:
            raw = response.read(MAX_RESPONSE_BYTES + 1)
            status = response.status
            metadata = dict(response.headers.items())
    except HTTPError as exc:
        return exc.code, {}, dict(exc.headers.items())
    except (OSError, URLError) as exc:
        raise DiscoveryError("GRAPH_NETWORK_UNAVAILABLE") from exc
    if len(raw) > MAX_RESPONSE_BYTES:
        raise DiscoveryError("GRAPH_RESPONSE_TOO_LARGE")
    try:
        result = json.loads(raw)
    except (ValueError, UnicodeError) as exc:
        raise DiscoveryError("GRAPH_INVALID_JSON") from exc
    if not isinstance(result, dict):
        raise DiscoveryError("GRAPH_INVALID_JSON")
    return status, result, metadata


class GraphClient:
    """Bounded Graph API reader supporting app-only auth and paging."""

    def __init__(
        self,
        credentials: EntraCredentials,
        request: Callable[..., Any] | None = None,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        """Keep injectable HTTP and sleep functions for deterministic tests."""
        self.credentials = credentials
        self.request = request or _http_request
        self.sleep = sleep
        self._token = ""
        self._expires = 0.0

    def _send(
        self, method: str, url: str, headers: dict[str, str],
        body: bytes | None = None,
    ) -> dict[str, Any]:
        """Retry bounded transient responses without leaking tokens."""
        for attempt in range(4):
            try:
                status, data, response_headers = self.request(
                    method, url, headers, body
                )
            except DiscoveryError:
                raise
            except Exception as exc:
                raise DiscoveryError("GRAPH_NETWORK_UNAVAILABLE") from exc
            if status == 200:
                if not isinstance(data, dict):
                    raise DiscoveryError("GRAPH_INVALID_JSON")
                return data
            if status in (429, 500, 502, 503, 504) and attempt < 3:
                values = {
                    str(k).lower(): str(v)
                    for k, v in response_headers.items()
                }
                delay = values.get("retry-after", "")
                try:
                    pause = float(delay)
                except ValueError:
                    pause = float(2 ** attempt)
                self.sleep(min(30.0, max(0.0, pause)))
                continue
            raise DiscoveryError("GRAPH_HTTP_" + str(status))
        raise DiscoveryError("GRAPH_RETRY_EXHAUSTED")

    def _access_token(self) -> str:
        """Acquire and cache only an in-memory client credentials token."""
        if self._token and time.monotonic() < self._expires:
            return self._token
        url = (
            "https://login.microsoftonline.com/"
            + self.credentials.tenant + "/oauth2/v2.0/token"
        )
        body = urlencode({
            "client_id": self.credentials.client_id,
            "client_secret": self.credentials.secret,
            "scope": "https://graph.microsoft.com/.default",
            "grant_type": "client_credentials",
        }).encode("utf-8")
        data = self._send(
            "POST", url,
            {"Content-Type": "application/x-www-form-urlencoded"}, body
        )
        token = data.get("access_token")
        if not isinstance(token, str) or not token:
            raise DiscoveryError("GRAPH_TOKEN_MISSING")
        expires = data.get("expires_in", 3600)
        if type(expires) is not int or expires < 60:
            raise DiscoveryError("GRAPH_TOKEN_EXPIRY_INVALID")
        self._token = token
        self._expires = time.monotonic() + max(1, expires - 60)
        return token

    @staticmethod
    def _validated_link(url: str) -> str:
        """Accept only HTTPS Graph v1.0 site enumeration URLs.

        Args:
            url: A Graph nextLink or the initial endpoint.

        Returns:
            An unchanged validated URL.
        """
        parts = urlsplit(url)
        if (
            parts.scheme != "https"
            or parts.netloc != "graph.microsoft.com"
            or not parts.path.startswith("/v1.0/sites")
            or parts.fragment
            or parts.username
            or parts.password
        ):
            raise DiscoveryError("GRAPH_NEXTLINK_UNSAFE")
        return url

    def pages(self, endpoint: str) -> list[dict[str, Any]]:
        """Follow every Graph page with cycle and size protection.

        Args:
            endpoint: A site or site-drives Graph v1.0 endpoint.

        Returns:
            All objects collected from a complete endpoint walk.
        """
        items: list[dict[str, Any]] = []
        visited: set[str] = set()
        url = endpoint
        while url:
            self._validated_link(url)
            if url in visited:
                raise DiscoveryError("GRAPH_PAGINATION_CYCLE")
            if len(visited) >= MAX_PAGES:
                raise DiscoveryError("GRAPH_PAGE_LIMIT")
            visited.add(url)
            data = self._send(
                "GET", url,
                {"Authorization": "Bearer " + self._access_token()},
            )
            page = data.get("value")
            if not isinstance(page, list):
                raise DiscoveryError("GRAPH_PAGE_MALFORMED")
            if len(items) + len(page) > MAX_ITEMS:
                raise DiscoveryError("GRAPH_ITEM_LIMIT")
            if any(not isinstance(row, dict) for row in page):
                raise DiscoveryError("GRAPH_PAGE_MALFORMED")
            items.extend(page)
            next_url = data.get("@odata.nextLink")
            if next_url is not None and not isinstance(next_url, str):
                raise DiscoveryError("GRAPH_NEXTLINK_UNSAFE")
            url = next_url or ""
        return items


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
