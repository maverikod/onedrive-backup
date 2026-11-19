"""Bounded Microsoft Graph HTTPS reader of the SharePoint discovery."""

from __future__ import annotations

import json
import time
from typing import Any, Callable
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode, urlsplit
from urllib.request import Request, urlopen

from .sharepoint_base import DiscoveryError, EntraCredentials, MAX_ITEMS, MAX_PAGES, MAX_RESPONSE_BYTES


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
