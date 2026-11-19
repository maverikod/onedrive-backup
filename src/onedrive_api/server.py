"""mTLS-only MCP Proxy Adapter: JSON-RPC commands, the temporary download link and the adapter transfer."""

from __future__ import annotations

import argparse
import asyncio
import base64
import json
import logging
import os
import secrets
import socket
import time
from pathlib import Path
import ssl

from .catalog import EXPORT_RE, Catalog, CatalogError
from .version import read_version

LOG = logging.getLogger(__name__)


def _catalog() -> Catalog:
    return Catalog(
        os.environ.get("ONEDRIVE_BACKUP_CONFIG", "/config/backup.json"),
        os.environ.get("ONEDRIVE_BACKUP_DATA", "/data"),
        max_export_bytes=int(
            os.environ.get("ONEDRIVE_MAX_EXPORT_BYTES", str(10 * 1024**3))
        ),
    )


CREDENTIALS_FILE_ENV = "ONEDRIVE_API_CREDENTIALS_FILE"
DEFAULT_CREDENTIALS_FILE = "/secrets/api-credentials"
# Routes of the adapter that stay served: JSON-RPC, health, the command listing, the schema pages, the
# temporary download link and the adapter transfer download (confined by transfer.allowed_directories).
# Everything else, /ws and the upload routes included, is removed.
ALLOWED_ROUTES = frozenset({
    "/api/jsonrpc",
    "/api/jsonrpc/batch",
    "/health",
    "/commands",
    "/openapi.json",
    "/docs",
    "/redoc",
    "/downloads/{file_id}/{filename}",
    "/api/transfer/downloads",
    "/api/transfer/downloads/{transfer_id}",
    "/api/transfer/downloads/{transfer_id}/chunks",
})


def api_token() -> str | None:
    """Return the interim API token T = base64(login:password), or None when no valid one is provisioned.

    The credentials are one line login:password in a private file of the host secrets directory
    (mode 0600, owner of the service), never in the committed configuration. An absent, empty or
    malformed file yields None: no direct peer can then authenticate (every request without a token
    answers 401), while the service still starts and serves the MCP Proxy peer (AU5, R18).
    """
    path = Path(os.environ.get(CREDENTIALS_FILE_ENV, DEFAULT_CREDENTIALS_FILE))
    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return None
    lines = text.splitlines()
    login, sep, password = (lines[0] if lines else "").partition(":")
    if not (sep and login and password):
        LOG.warning("API credentials file holds no line login:password: no direct peer can authenticate")
        return None
    return base64.b64encode((login + ":" + password).encode("utf-8")).decode("ascii")


def secure_auth(config: dict) -> str:
    """Enforce the adapter token gate and return the internal proxy token.

    auth.use_token must be on. The framework refuses to start without a token, so the accepted tokens are
    always the internal token, a random per-process secret that only ProxyTrustMiddleware presents (it
    exists whether or not the credentials file does), plus T of the credentials file when one is provisioned.
    A direct peer needs T; the MCP Proxy peer is admitted by the middleware on its transport identity alone.
    """
    auth = config.get("auth")
    if not isinstance(auth, dict) or auth.get("use_token") is not True:
        raise ValueError("Production server MUST set auth.use_token=true")
    internal = secrets.token_urlsafe(32)
    tokens = {internal: ["other"]}
    token = api_token()
    if token:
        tokens[token] = ["other"]
    auth["tokens"] = tokens
    return internal


class ProxyTrustMiddleware:
    """ASGI middleware: the MCP Proxy peer is admitted on its transport identity, with no token from it.

    Every connection is already mutual TLS (a trusted client certificate is mandatory). MCP Proxy forwards
    commands without a token; its callers are authorized by the proxy itself (OAuth and access lists). A request
    whose transport peer address is one of the addresses of the configured proxy host names carries the internal
    token, which no other peer knows, so it passes the token gate on every route whether or not the
    api-credentials secret exists. Every other peer must present T. Without configured hosts nobody is admitted
    without a token (fail closed), and request headers (X-Forwarded-For, Forwarded, X-Real-IP, Host) grant nothing.
    """

    CACHE_SECONDS = 30.0

    def __init__(self, app, hosts: list[str], token: str | None) -> None:
        self.app = app
        self.hosts = [item for item in hosts if isinstance(item, str) and item]
        self.token = token
        self._addresses: set[str] = set()
        self._resolved_at = 0.0

    async def _proxy_addresses(self) -> set[str]:
        """Resolve the trusted host names, cached for a short time; a failed lookup trusts nothing."""
        now = time.monotonic()
        if now - self._resolved_at < self.CACHE_SECONDS:
            return self._addresses
        found: set[str] = set()
        loop = asyncio.get_running_loop()
        for host in self.hosts:
            try:
                for info in await loop.getaddrinfo(host, None, type=socket.SOCK_STREAM):
                    found.add(info[4][0])
            except OSError:
                continue
        self._addresses, self._resolved_at = found, now
        return found

    async def __call__(self, scope, receive, send) -> None:
        if scope["type"] == "http" and self.token and self.hosts:
            # The transport peer of the mTLS connection only; no request header is ever read for identity.
            peer = (scope.get("client") or (None,))[0]
            if peer and peer in await self._proxy_addresses():
                headers = [(k, v) for k, v in scope["headers"] if k.lower() != b"x-api-key"]
                headers.append((b"x-api-key", self.token.encode("ascii")))
                scope = {**scope, "headers": headers}
        await self.app(scope, receive, send)


def validate_transfer(config: dict) -> dict:
    """Require a transfer section confined to the exports directory; the adapter denies all otherwise."""
    transfer = config.get("transfer")
    dirs = transfer.get("allowed_directories") if isinstance(transfer, dict) else None
    if not (isinstance(dirs, list) and dirs and all(isinstance(item, str) and item.strip() for item in dirs)):
        raise ValueError("Production server MUST confine transfer.allowed_directories to the exports directory")
    return transfer


def _resolve_download(file_id: str, filename: str):
    """Resolve one temporary link /downloads/<export_id>/<filename> to its staged export file."""
    if not EXPORT_RE.fullmatch(file_id):
        raise ValueError("Unknown download")
    try:
        meta, path = _catalog().get_export(file_id)
    except CatalogError as exc:
        raise FileNotFoundError(str(exc)) from exc
    if filename != meta["filename"]:
        raise FileNotFoundError("Unknown download")
    return {"name": meta["filename"]}, path


def _register_commands() -> None:
    """Register only safe catalogue commands and their help metadata."""
    from mcp_proxy_adapter.commands.command_registry import registry
    from .commands_backup import (
        BackupDeleteExport,
        BackupDownloadBegin,
        BackupDownloadStatus,
        BackupListFiles,
        BackupPrepareDownload,
        BackupSnapshots,
    )
    from .commands_base import BackupHelpCommand
    from .commands_sharepoint import (
        BackupDiscoveryStatus,
        BackupLibrariesList,
        BackupSitesList,
    )
    from .info_command import InfoCommand

    registry.clear()
    for cls in (
        BackupHelpCommand,
        InfoCommand,
        BackupSnapshots,
        BackupListFiles,
        BackupPrepareDownload,
        BackupDownloadStatus,
        BackupDownloadBegin,
        BackupDeleteExport,
        BackupSitesList,
        BackupLibrariesList,
        BackupDiscoveryStatus,
    ):
        registry.register(cls, "custom")


def _validate_mtls_config(config: dict) -> None:
    server = config.get("server", {})
    if server.get("protocol") != "mtls":
        raise ValueError("Production server MUST use protocol=mtls")
    for key in ("cert", "key", "ca"):
        filename = server.get("ssl", {}).get(key)
        if not isinstance(filename, str) or not Path(filename).is_file():
            raise ValueError("Missing mTLS certificate: server.ssl." + key)


def make_app(config_path: str | Path):
    """Create the secure adapter application with read-only endpoints."""
    config_path = Path(config_path).resolve()
    config = json.loads(config_path.read_text(encoding="utf-8"))
    _validate_mtls_config(config)
    proxy_token = secure_auth(config)
    transfer = validate_transfer(config)
    os.environ["CONFIG_FILE"] = str(config_path)
    os.environ["MCP_CONFIG_FILE"] = str(config_path)

    from mcp_proxy_adapter.api.app import create_app
    from mcp_proxy_adapter.api.public_downloads import set_public_download_resolver
    from mcp_proxy_adapter.config import get_config

    app = create_app(
        title="OneDrive Backup API",
        description="Read-only backup browse/export over mTLS",
        version=read_version(),
        app_config=config,
        config_path=str(config_path),
    )
    # The adapter reads the transfer section from its global configuration, which does not load
    # this server's configuration file on its own: without this call every transfer is denied.
    get_config().set("transfer", transfer)
    _register_commands()
    set_public_download_resolver(app, _resolve_download)

    # The framework also registers privileged administration, upload and WebSocket endpoints.
    # Only the routes of ALLOWED_ROUTES stay; every other route answers the framework 404.
    # MCP Proxy registration queries GET /commands (get_methods); the registry was already
    # reduced to help, info and backup_* in _register_commands.
    app.router.routes = [
        route for route in app.router.routes
        if getattr(route, "path", None) in ALLOWED_ROUTES
    ]

    # Added last, so it runs first: it must put the internal token on a proxy peer request before the token gate.
    trust = config.get("proxy_trust")
    hosts = trust.get("hosts", []) if isinstance(trust, dict) else []
    app.add_middleware(ProxyTrustMiddleware, hosts=hosts, token=proxy_token)

    return app


def tls_server_settings(config: dict, config_path: str) -> dict:
    """Build verified mTLS context using proxy-managed revocation."""
    from mcp_proxy_adapter.core.app_factory.ssl_config import (
        build_server_ssl_config,
    )

    _validate_mtls_config(config)
    settings = build_server_ssl_config(config, config_path=config_path)
    context = settings.get("ssl_context")
    if not isinstance(context, ssl.SSLContext):
        raise RuntimeError("mTLS SSLContext missing from adapter")
    # The proxy owns CRL validation; enforce client certificate trust.
    crl_flags = ssl.VERIFY_CRL_CHECK_LEAF | ssl.VERIFY_CRL_CHECK_CHAIN
    context.verify_flags &= ~crl_flags
    context.verify_mode = ssl.CERT_REQUIRED
    settings["ssl_context"] = context
    settings["verify_client"] = True
    return settings


def main() -> None:
    parser = argparse.ArgumentParser(description="OneDrive Backup mTLS server")
    parser.add_argument("--config", default="/config/server.json")
    parser.add_argument("--backup-config", default="/config/backup.json")
    parser.add_argument("--data", default="/data")
    args = parser.parse_args()
    backup_config = Path(args.backup_config).resolve()
    os.environ["ONEDRIVE_BACKUP_CONFIG"] = str(backup_config)
    os.environ["ONEDRIVE_BACKUP_DATA"] = str(Path(args.data).resolve())
    path = str(Path(args.config).resolve())
    config = json.loads(Path(path).read_text(encoding="utf-8"))
    _validate_mtls_config(config)
    app = make_app(path)

    from mcp_proxy_adapter.core.server_engine import ServerEngineFactory
    from mcp_proxy_adapter.core.logging import setup_logging

    settings = tls_server_settings(config, path)
    server = config["server"]
    setup_logging(level=server.get("log_level", "INFO"))
    engine = ServerEngineFactory.get_engine("hypercorn")
    if engine is None:
        raise RuntimeError("Hypercorn is unavailable")
    engine.run_server(
        app,
        {
            "host": server.get("host", "0.0.0.0"),
            "port": int(server.get("port", 8050)),
            "log_level": server.get("log_level", "INFO"),
            "reload": False,
            **settings,
        },
    )


if __name__ == "__main__":
    main()
