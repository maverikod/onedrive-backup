"""Read-only download of the extra copies of colliding SharePoint files.

The only Graph request of this module is ``GET /drives/{drive}/items/{item}/content``
with the app-only token of the discovery. The pre-authenticated redirect target
is followed WITHOUT the Authorization header (the header is added as an
unredirected one). Nothing is ever written to SharePoint.
"""

from __future__ import annotations

import logging
import os
import re
import time
from pathlib import Path
from typing import Any, Callable
from urllib.error import URLError
from urllib.parse import quote
from urllib.request import Request, urlopen

from onedrive_backup import BackupError, rclone_base

from .sharepoint_base import DiscoveryError, EntraCredentials, GRAPH_ROOT
from .sharepoint_graph import GraphClient

LOG = logging.getLogger("onedrive_backup")
ATTEMPTS = 3
CHUNK = 1024 * 1024
HEX_DIGEST = re.compile(r"^[0-9a-f]{40}$")


def local_quickxor(
    cfg: dict[str, Any], runner: Callable[..., str], path: Path
) -> str | None:
    """Compute the quickXorHash of a local file with rclone itself.

    Args:
        cfg: Validated backup configuration.
        runner: Command runner of the backup module (run_command).
        path: Local file.

    Returns:
        Lowercase hex digest, or None when rclone cannot hash the file.
    """
    command = rclone_base(cfg) + ["hashsum", "quickxor", str(path)]
    try:
        words = runner(command, capture=True).split()
    except BackupError as exc:
        LOG.warning("quickXorHash of %s failed: %s", path.name, exc)
        return None
    digest = words[0].lower() if words else ""
    return digest if HEX_DIGEST.fullmatch(digest) else None


class ContentFetcher:
    """Download item contents of one drive with one lazily acquired token."""

    def __init__(self, cfg: dict[str, Any], drive_id: str) -> None:
        """Remember the configuration; no network access happens here.

        Args:
            cfg: Validated backup configuration (rclone_config path).
            drive_id: Graph drive identifier of the library.
        """
        self.cfg = cfg
        self.drive_id = drive_id
        self.client: GraphClient | None = None

    def _token(self) -> str:
        """Return a valid app-only token, acquiring it on first use.

        Returns:
            The bearer token.
        """
        if self.client is None:
            credentials = EntraCredentials.from_rclone(
                self.cfg["rclone_config"]
            )
            self.client = GraphClient(credentials)
        return self.client._access_token()

    def _download(self, item_id: str, tmp: Path) -> None:
        """Stream one item to a temporary file (one attempt).

        Args:
            item_id: Graph item id.
            tmp: Temporary file, created or truncated.

        Returns:
            None. Raises OSError, URLError or DiscoveryError on failure.
        """
        url = (
            GRAPH_ROOT + "/drives/" + quote(self.drive_id, safe="!")
            + "/items/" + quote(item_id, safe="") + "/content"
        )
        request = Request(url, method="GET")
        request.add_unredirected_header(
            "Authorization", "Bearer " + self._token()
        )
        received = 0
        with urlopen(request, timeout=60) as response:
            headers = {
                str(k).lower(): str(v) for k, v in response.headers.items()
            }
            with tmp.open("wb") as stream:
                while True:
                    chunk = response.read(CHUNK)
                    if not chunk:
                        break
                    stream.write(chunk)
                    received += len(chunk)
        expected = headers.get("content-length", "")
        if expected.isdigit() and int(expected) != received:
            raise OSError("short body: %d of %s bytes" % (received, expected))

    def fetch(self, item_id: str, tmp: Path) -> bool:
        """Download one item with the retry discipline (3 attempts).

        Args:
            item_id: Graph item id.
            tmp: Temporary file; removed again after a failed fetch.

        Returns:
            True when a complete body was written to tmp.
        """
        for attempt in range(ATTEMPTS):
            try:
                self._download(item_id, tmp)
                return True
            except (OSError, URLError, DiscoveryError) as exc:
                LOG.warning("Fetch of item %s failed (attempt %d/%d): %s",
                            item_id, attempt + 1, ATTEMPTS,
                            exc.__class__.__name__)
                if attempt + 1 < ATTEMPTS:
                    time.sleep(2 ** attempt)
        tmp.unlink(missing_ok=True)
        return False


def new_file_mode() -> int:
    """Return the mode rclone gives a new file (0666 under the umask).

    Returns:
        The permission bits.
    """
    mask = os.umask(0)
    os.umask(mask)
    return 0o666 & ~mask
