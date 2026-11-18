"""mTLS-only MCP Proxy Adapter and REST download API."""

from __future__ import annotations

import argparse
import asyncio
import json
import os
from pathlib import Path
import ssl
from typing import Any

from .catalog import Catalog, CatalogError


def _catalog() -> Catalog:
    return Catalog(
        os.environ.get("ONEDRIVE_BACKUP_CONFIG", "/config/backup.json"),
        os.environ.get("ONEDRIVE_BACKUP_DATA", "/data"),
        max_export_bytes=int(
            os.environ.get("ONEDRIVE_MAX_EXPORT_BYTES", str(10 * 1024**3))
        ),
    )


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
        if os.environ.get("ONEDRIVE_SCAFFOLD_MODE") == "1":
            raise DiscoveryError("SCAFFOLD_ONLY")
        return _sharepoint_store().sites(**params)

    def _sharepoint_libraries(**params: Any) -> dict:
        """Read libraries of one verified site, never personal drives."""
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
        version = "0.3.6"
        author = "OneDrive Backup maintainers"
        email = "maintainers@example.org"

        @classmethod
        def metadata(cls) -> dict[str, Any]:
            """Return the full help command reference metadata."""
            return command_metadata_for(cls)

    class CatalogCommand(Command):
        category = "backup"
        version = "0.3.6"
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
                    "site_id": {"type": "string", "minLength": 1,
                                "maxLength": 300},
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
    os.environ["CONFIG_FILE"] = str(config_path)
    os.environ["MCP_CONFIG_FILE"] = str(config_path)

    from fastapi import HTTPException, Request
    from fastapi.responses import FileResponse
    from mcp_proxy_adapter.api.app import create_app

    app = create_app(
        title="OneDrive Backup API",
        description="Read-only backup browse/export over mTLS",
        version="0.3.6",
        app_config=config,
        config_path=str(config_path),
    )
    _register_commands()

    # Framework also registers privileged administration/transfer endpoints.
    # Never publish local-file transfer, reload, or admin endpoints.
    # config editors or command loading on the backup server, even over mTLS.
    # MCP Proxy registration queries GET /commands (get_methods).
    # Registry was already reduced to help and backup_* in _register_commands.
    allowed = {
        "/api/jsonrpc",
        "/api/jsonrpc/batch",
        "/health",
        "/commands",
        "/openapi.json",
        "/docs",
        "/redoc",
    }
    routes = app.router.routes
    app.router.routes = [
        route for route in routes if getattr(route, "path", None) in allowed
    ]

    from .ui import install_ui
    from .sharepoint_discovery import DiscoveryError, SharePointInventory

    install_ui(app, _catalog)

    def fail(exc: CatalogError | DiscoveryError) -> HTTPException:
        return HTTPException(status_code=exc.status, detail=str(exc))

    @app.get("/api/v1/health")
    async def backup_health():
        return {
            "status": "ok",
            "protocol": "mtls",
            "service": "onedrive-backup",
        }

    def sharepoint_store() -> SharePointInventory:
        """Resolve the private source inventory on the backup volume."""
        base = Path(os.environ.get("ONEDRIVE_BACKUP_DATA", "/data"))
        return SharePointInventory(base / "sharepoint")

    @app.get("/api/v1/discovery/status")
    async def sharepoint_discovery_status():
        """Return nonsecret completeness and readiness information."""
        if os.environ.get("ONEDRIVE_SCAFFOLD_MODE") == "1":
            return {
                "ready": False, "complete": False,
                "state": "SCAFFOLD_ONLY",
            }
        try:
            return await asyncio.to_thread(sharepoint_store().status)
        except DiscoveryError as exc:
            raise fail(exc) from exc

    @app.get("/api/v1/sites")
    async def sharepoint_sites(
        limit: int = 100, offset: int = 0, query: str = "",
    ):
        """Browse completed SharePoint site discovery results."""
        if os.environ.get("ONEDRIVE_SCAFFOLD_MODE") == "1":
            raise HTTPException(503, detail="SCAFFOLD_ONLY")
        try:
            return await asyncio.to_thread(
                sharepoint_store().sites, limit, offset, query
            )
        except DiscoveryError as exc:
            raise fail(exc) from exc

    @app.get("/api/v1/sites/{site_id}/libraries")
    async def sharepoint_libraries(
        site_id: str, limit: int = 100, offset: int = 0,
    ):
        """Browse libraries within one stable site identifier."""
        if os.environ.get("ONEDRIVE_SCAFFOLD_MODE") == "1":
            raise HTTPException(503, detail="SCAFFOLD_ONLY")
        try:
            return await asyncio.to_thread(
                sharepoint_store().libraries, site_id, limit, offset
            )
        except DiscoveryError as exc:
            raise fail(exc) from exc

    @app.get("/api/v1/snapshots")
    async def backup_snapshots(limit: int = 100):
        try:
            return await asyncio.to_thread(_catalog().snapshots, limit)
        except CatalogError as exc:
            raise fail(exc) from exc

    @app.get("/api/v1/snapshots/{snapshot_id}/files")
    async def backup_files(
        snapshot_id: str, prefix: str = "", offset: int = 0, limit: int = 1000
    ):
        try:
            return await asyncio.to_thread(
                _catalog().files, snapshot_id, prefix, limit, offset
            )
        except CatalogError as exc:
            raise fail(exc) from exc

    @app.post("/api/v1/exports")
    async def prepare_export(request: Request):
        try:
            body = await request.json()
            if not isinstance(body, dict):
                raise CatalogError("JSON object expected")
            if set(body) - {"snapshot_id", "file_path"}:
                raise CatalogError("Unknown export parameters")
            snapshot_id = body.get("snapshot_id")
            if not isinstance(snapshot_id, str):
                raise CatalogError("snapshot_id must be a string")
            return await asyncio.to_thread(
                _catalog().prepare,
                snapshot_id,
                body.get("file_path"),
            )
        except CatalogError as exc:
            raise fail(exc) from exc
        except ValueError as exc:
            raise HTTPException(400, detail="Invalid JSON") from exc

    @app.get("/api/v1/exports/{export_id}")
    async def download_export(export_id: str):
        try:
            archive = _catalog()
            get_export = archive.get_export
            meta, filename = await asyncio.to_thread(get_export, export_id)
            return FileResponse(
                filename,
                media_type="application/octet-stream",
                filename=meta["filename"],
                headers={
                    "X-Content-SHA256": meta["sha256"],
                    "Cache-Control": "no-store",
                },
            )
        except CatalogError as exc:
            raise fail(exc) from exc

    @app.get("/api/v1/exports/{export_id}/status")
    async def export_status(export_id: str):
        try:
            return await asyncio.to_thread(_catalog().export_status, export_id)
        except CatalogError as exc:
            raise fail(exc) from exc

    @app.delete("/api/v1/exports/{export_id}")
    async def delete_export(export_id: str):
        try:
            return await asyncio.to_thread(_catalog().delete_export, export_id)
        except CatalogError as exc:
            raise fail(exc) from exc

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
