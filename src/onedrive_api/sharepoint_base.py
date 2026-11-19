"""Shared constants, error type and app-only credentials of the SharePoint discovery."""

from __future__ import annotations

import configparser
from pathlib import Path
import re
import stat


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
