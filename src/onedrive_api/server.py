"""mTLS-only MCP Proxy Adapter: JSON-RPC commands, the temporary download link and the adapter transfer."""

from __future__ import annotations

import argparse
import asyncio
import base64
import json
import os
import socket
import time
from pathlib import Path
import ssl
from typing import Any

from .catalog import EXPORT_RE, Catalog, CatalogError
from .version import read_version


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
    """Return the interim API token T = base64(login:password), or None when none is provisioned.

    The credentials are one line login:password in a private file of the host secrets directory
    (mode 0600, owner of the service), never in the committed configuration. A malformed file is
    refused; an absent file leaves the server locked because every request then fails the token gate.
    """
    path = Path(os.environ.get(CREDENTIALS_FILE_ENV, DEFAULT_CREDENTIALS_FILE))
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return None
    lines = text.splitlines()
    login, sep, password = (lines[0] if lines else "").partition(":")
    if not (sep and login and password):
        raise ValueError("API credentials file must hold one line login:password")
    return base64.b64encode((login + ":" + password).encode("utf-8")).decode("ascii")


def secure_auth(config: dict) -> None:
    """Enforce the adapter token gate: use_token must be on and the only token is T of the credentials file."""
    auth = config.get("auth")
    if not isinstance(auth, dict) or auth.get("use_token") is not True:
        raise ValueError("Production server MUST set auth.use_token=true")
    token = api_token()
    auth["tokens"] = {token: ["other"]} if token else {}


class ProxyTrustMiddleware:
    """ASGI middleware: a request whose peer is the MCP Proxy host carries the API token.

    MCP Proxy forwards commands without a token. Its callers are authorized by the proxy itself (OAuth
    and access lists) and the connection is already mutual TLS, so a request from the proxy host is
    admitted by adding the token header; every other peer must present the token. Without configured
    hosts or without a provisioned token nothing is added and the gate stays closed.
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
    from mcp_proxy_adapter.commands.base import Command
    from mcp_proxy_adapter.commands.command_registry import registry
    from mcp_proxy_adapter.commands.help_command import HelpCommand
    from mcp_proxy_adapter.commands.result import CommandResult, ErrorResult
    from .command_reference import REFERENCE, command_metadata_for
    from .info_command import InfoCommand
    from .sharepoint_discovery import DiscoveryError, SharePointInventory

    def _sharepoint_store() -> SharePointInventory:
        """Access the private inventory within the mounted backup volume."""
        base = Path(os.environ.get("ONEDRIVE_BACKUP_DATA", "/data"))
        return SharePointInventory(base / "sharepoint")

    def _sharepoint_sites(**params: Any) -> dict:
        """Read only a complete, non-scaffold site inventory."""
        SharePointInventory.check_query(params.get("query", ""))
        if os.environ.get("ONEDRIVE_SCAFFOLD_MODE") == "1":
            raise DiscoveryError("SCAFFOLD_ONLY")
        return _sharepoint_store().sites(**params)

    def _sharepoint_libraries(**params: Any) -> dict:
        """Read libraries of one verified site, never personal drives."""
        SharePointInventory.check_site_id(params.get("site_id"))
        if os.environ.get("ONEDRIVE_SCAFFOLD_MODE") == "1":
            raise DiscoveryError("SCAFFOLD_ONLY")
        return _sharepoint_store().libraries(**params)

    def _sharepoint_status() -> dict:
        """Report source discovery coverage without making Graph requests."""
        if os.environ.get("ONEDRIVE_SCAFFOLD_MODE") == "1":
            return {"ready": False, "complete": False,
                    "state": "SCAFFOLD_ONLY"}
        return _sharepoint_store().status()

    class BackupHelpCommand(HelpCommand):
        """Describe registered commands with the canonical metadata."""

        category = "documentation"
        version = read_version()
        author = "OneDrive Backup maintainers"
        email = "maintainers@example.org"

        @classmethod
        def metadata(cls) -> dict[str, Any]:
            """Return the full help command reference metadata."""
            return command_metadata_for(cls)

    class CatalogCommand(Command):
        category = "backup"
        version = read_version()
        author = "OneDrive Backup"
        email = "maintainers@example.org"

        @classmethod
        def metadata(cls) -> dict[str, Any]:
            """Return detailed descriptions shared by help and info."""
            return command_metadata_for(cls)

        @classmethod
        def _schema_with_descriptions(cls, schema: dict) -> dict:
            """Populate schema descriptions using the canonical reference."""
            descriptions = REFERENCE.get(cls.name, {}).get("parameters", {})
            for name, spec in schema.get("properties", {}).items():
                if isinstance(spec, dict):
                    spec["description"] = descriptions.get(
                        name, spec.get("description", "")
                    )
            return schema

        @staticmethod
        async def apply(call, **kwargs: Any):
            try:
                data = await asyncio.to_thread(call, **kwargs)
                return CommandResult(success=True, data=data)
            except CatalogError as exc:
                return ErrorResult(message=str(exc), code=exc.status)
            except DiscoveryError as exc:
                return ErrorResult(message=exc.code, code=exc.status)

    class BackupSnapshots(CatalogCommand):
        name = "backup_snapshots"
        descr = "List available OneDrive restic snapshots."

        async def execute(
            self,
            limit: int = 100,
            **kwargs: Any,
        ) -> CommandResult:
            return await self.apply(_catalog().snapshots, limit=limit)

        @classmethod
        def get_schema(cls) -> dict:
            schema = {
                "type": "object",
                "properties": {
                    "limit": {
                        "type": "integer",
                        "minimum": 1,
                        "maximum": 1000,
                        "default": 100,
                    }
                },
                "additionalProperties": False,
            }
            return cls._schema_with_descriptions(schema)

    class BackupListFiles(CatalogCommand):
        name = "backup_list_files"
        descr = "List backup snapshot files with pagination."

        async def execute(
            self,
            snapshot_id: str = "",
            prefix: str = "",
            offset: int = 0,
            limit: int = 1000,
            **kwargs: Any,
        ) -> CommandResult:
            return await self.apply(
                _catalog().files,
                snapshot_id=snapshot_id,
                prefix=prefix,
                offset=offset,
                limit=limit,
            )

        @classmethod
        def get_schema(cls) -> dict:
            schema = {
                "type": "object",
                "properties": {
                    "snapshot_id": {"type": "string"},
                    "prefix": {"type": "string", "default": ""},
                    "offset": {"type": "integer", "minimum": 0, "default": 0},
                    "limit": {
                        "type": "integer",
                        "minimum": 1,
                        "maximum": 5000,
                        "default": 1000,
                    },
                },
                "required": ["snapshot_id"],
                "additionalProperties": False,
            }
            return cls._schema_with_descriptions(schema)

    class BackupPrepareDownload(CatalogCommand):
        name = "backup_prepare_download"
        descr = "Stage one file or a complete snapshot archive."

        async def execute(
            self,
            snapshot_id: str = "",
            file_path: str | None = None,
            **kwargs: Any,
        ) -> CommandResult:
            return await self.apply(
                _catalog().prepare,
                snapshot_id=snapshot_id,
                file_path=file_path,
            )

        @classmethod
        def get_schema(cls) -> dict:
            schema = {
                "type": "object",
                "properties": {
                    "snapshot_id": {"type": "string"},
                    "file_path": {"type": ["string", "null"], "default": None},
                },
                "required": ["snapshot_id"],
                "additionalProperties": False,
            }
            return cls._schema_with_descriptions(schema)

    class BackupDownloadStatus(CatalogCommand):
        name = "backup_download_status"
        descr = "Inspect staged export metadata and SHA256."

        async def execute(
            self,
            export_id: str = "",
            **kwargs: Any,
        ) -> CommandResult:
            archive = _catalog()
            return await self.apply(archive.export_status, export_id=export_id)

        @classmethod
        def get_schema(cls) -> dict:
            schema = {
                "type": "object",
                "properties": {"export_id": {"type": "string"}},
                "required": ["export_id"],
                "additionalProperties": False,
            }
            return cls._schema_with_descriptions(schema)

    class BackupDownloadBegin(CatalogCommand):
        name = "backup_download_begin"
        descr = "Register the adapter transfer download session of one staged export."

        async def execute(
            self,
            export_id: str = "",
            **kwargs: Any,
        ) -> CommandResult:
            from mcp_proxy_adapter.api.transfer_session_service import (
                TransferPayloadValidationError,
                build_transfer_chunk_transport,
                run_create_download_session,
            )
            from mcp_proxy_adapter.transfer import TransferError, TransferTooLargeError

            try:
                meta, source = await asyncio.to_thread(_catalog().get_export, export_id)
                data = await run_create_download_session({
                    "source_path": str(source),
                    "filename": meta["filename"],
                    "compression": "identity",
                })
            except CatalogError as exc:
                return ErrorResult(message=str(exc), code=exc.status)
            except TransferPayloadValidationError as exc:
                return ErrorResult(message="Invalid transfer request: " + ", ".join(exc.missing_fields), code=400)
            except TransferTooLargeError as exc:
                return ErrorResult(message=str(exc), code=413)
            except TransferError as exc:
                return ErrorResult(message=str(exc), code=503)
            transport = build_transfer_chunk_transport(
                direction="download", transfer_id=str(data["transfer_id"])
            )
            return CommandResult(success=True, data={**data, "transport": transport})

        @classmethod
        def get_schema(cls) -> dict:
            schema = {
                "type": "object",
                "properties": {"export_id": {"type": "string"}},
                "required": ["export_id"],
                "additionalProperties": False,
            }
            return cls._schema_with_descriptions(schema)

    class BackupDeleteExport(CatalogCommand):
        name = "backup_delete_export"
        descr = "Delete staged plaintext export after a verified download."

        async def execute(
            self,
            export_id: str = "",
            **kwargs: Any,
        ) -> CommandResult:
            archive = _catalog()
            return await self.apply(archive.delete_export, export_id=export_id)

        @classmethod
        def get_schema(cls) -> dict:
            schema = {
                "type": "object",
                "properties": {"export_id": {"type": "string"}},
                "required": ["export_id"],
                "additionalProperties": False,
            }
            return cls._schema_with_descriptions(schema)

    class BackupSitesList(CatalogCommand):
        """List verified SharePoint Online sites from the last full scan."""

        name = "backup_sites_list"
        descr = "List discovered SharePoint sites."
        category = "sharepoint"

        async def execute(
            self, limit: int = 100, offset: int = 0,
            query: str = "", **kwargs: Any,
        ) -> CommandResult:
            """Read one bounded site page from persisted inventory."""
            return await self.apply(
                _sharepoint_sites, limit=limit, offset=offset, query=query
            )

        @classmethod
        def get_schema(cls) -> dict:
            """Describe bounded read-only site enumeration."""
            return cls._schema_with_descriptions({
                "type": "object",
                "properties": {
                    "limit": {"type": "integer", "default": 100,
                              "minimum": 1, "maximum": 1000},
                    "offset": {"type": "integer", "default": 0,
                               "minimum": 0, "maximum": 200000},
                    "query": {"type": "string", "default": "",
                              "maxLength": 128},
                },
                "additionalProperties": False,
            })

    class BackupLibrariesList(CatalogCommand):
        """List document libraries belonging to a verified site."""

        name = "backup_libraries_list"
        descr = "List discovered libraries of a SharePoint site."
        category = "sharepoint"

        async def execute(
            self, site_id: str = "", limit: int = 100,
            offset: int = 0, **kwargs: Any,
        ) -> CommandResult:
            """Return a page of libraries for a stable site identifier."""
            return await self.apply(
                _sharepoint_libraries, site_id=site_id,
                limit=limit, offset=offset
            )

        @classmethod
        def get_schema(cls) -> dict:
            """Describe required site ID and pagination restrictions."""
            return cls._schema_with_descriptions({
                "type": "object",
                "properties": {
                    # No maxLength: an overlong or malformed site_id is refused by the command with
                    # the error 400 INVALID_SITE_ID (R5), before the readiness gate.
                    "site_id": {"type": "string", "minLength": 1},
                    "limit": {"type": "integer", "default": 100,
                              "minimum": 1, "maximum": 1000},
                    "offset": {"type": "integer", "default": 0,
                               "minimum": 0, "maximum": 200000},
                },
                "required": ["site_id"],
                "additionalProperties": False,
            })

    class BackupDiscoveryStatus(CatalogCommand):
        """Report verified inventory coverage and readiness."""

        name = "backup_discovery_status"
        descr = "Report SharePoint discovery readiness and coverage."
        category = "sharepoint"

        async def execute(self, **kwargs: Any) -> CommandResult:
            """Read status without requesting credentials or source data."""
            return await self.apply(_sharepoint_status)

        @classmethod
        def get_schema(cls) -> dict:
            """Declare that discovery status has no input parameters."""
            return {
                "type": "object", "properties": {},
                "additionalProperties": False,
            }

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
    # A safe, restricted scaffold may register before the operator sets a
    # password or mounts backup storage. All browser actions stay locked.
    if os.environ.get("ONEDRIVE_SCAFFOLD_MODE") != "1":
        from .admin_password import AuthError, load_record

        try:
            load_record(
                Path(
                    os.environ.get(
                        "ONEDRIVE_ADMIN_HASH_FILE",
                        "/config/admin-password.hash",
                    )
                )
            )
        except AuthError as exc:
            raise ValueError("Admin password not set: " + str(exc)) from exc
    secure_auth(config)
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

    from .ui import install_ui

    install_ui(app, _catalog)
    # Added last, so it runs first: it must put the token on a proxy request before the token gate.
    trust = config.get("proxy_trust")
    hosts = trust.get("hosts", []) if isinstance(trust, dict) else []
    app.add_middleware(ProxyTrustMiddleware, hosts=hosts, token=next(iter(config["auth"]["tokens"]), None))

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
