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
        max_export_bytes=int(os.environ.get("ONEDRIVE_MAX_EXPORT_BYTES", str(10 * 1024 ** 3))),
    )


def _register_commands() -> None:
    """Leave only read-only catalogue commands, never adapter filesystem/admin RPCs."""
    from mcp_proxy_adapter.commands.base import Command
    from mcp_proxy_adapter.commands.command_registry import registry
    from mcp_proxy_adapter.commands.help_command import HelpCommand
    from mcp_proxy_adapter.commands.result import CommandResult, ErrorResult

    class CatalogCommand(Command):
        category = "backup"
        version = "0.2.0"
        author = "OneDrive Backup"
        email = "maintainers@example.org"

        @staticmethod
        async def apply(call, **kwargs: Any):
            try:
                data = await asyncio.to_thread(call, **kwargs)
                return CommandResult(success=True, data=data)
            except CatalogError as exc:
                return ErrorResult(message=str(exc), code=exc.status)

    class BackupSnapshots(CatalogCommand):
        name = "backup_snapshots"
        descr = "List available OneDrive restic snapshots."

        async def execute(self, limit: int = 100, **kwargs: Any) -> CommandResult:
            return await self.apply(_catalog().snapshots, limit=limit)

        @classmethod
        def get_schema(cls) -> dict:
            return {"type": "object", "properties": {
                "limit": {"type": "integer", "minimum": 1, "maximum": 1000, "default": 100}
            }, "additionalProperties": False}

    class BackupListFiles(CatalogCommand):
        name = "backup_list_files"
        descr = "List files within an existing backup snapshot, with pagination."

        async def execute(self, snapshot_id: str, prefix: str = "",
                          offset: int = 0, limit: int = 1000,
                          **kwargs: Any) -> CommandResult:
            return await self.apply(_catalog().files, snapshot_id=snapshot_id,
                                    prefix=prefix, offset=offset, limit=limit)

        @classmethod
        def get_schema(cls) -> dict:
            return {"type": "object", "properties": {
                "snapshot_id": {"type": "string"},
                "prefix": {"type": "string", "default": ""},
                "offset": {"type": "integer", "minimum": 0, "default": 0},
                "limit": {"type": "integer", "minimum": 1, "maximum": 5000, "default": 1000}
            }, "required": ["snapshot_id"], "additionalProperties": False}

    class BackupPrepareDownload(CatalogCommand):
        name = "backup_prepare_download"
        descr = "Create a bounded export of one file or a complete snapshot archive."

        async def execute(self, snapshot_id: str,
                          file_path: str | None = None,
                          **kwargs: Any) -> CommandResult:
            return await self.apply(_catalog().prepare, snapshot_id=snapshot_id,
                                    file_path=file_path)

        @classmethod
        def get_schema(cls) -> dict:
            return {"type": "object", "properties": {
                "snapshot_id": {"type": "string"},
                "file_path": {"type": ["string", "null"], "default": None}
            }, "required": ["snapshot_id"], "additionalProperties": False}

    class BackupDownloadStatus(CatalogCommand):
        name = "backup_download_status"
        descr = "Inspect a staged export by opaque ID; includes SHA256 and size."

        async def execute(self, export_id: str, **kwargs: Any) -> CommandResult:
            return await self.apply(_catalog().export_status, export_id=export_id)

        @classmethod
        def get_schema(cls) -> dict:
            return {"type": "object", "properties": {
                "export_id": {"type": "string"}
            }, "required": ["export_id"], "additionalProperties": False}

    class BackupDeleteExport(CatalogCommand):
        name = "backup_delete_export"
        descr = "Delete staged plaintext export after a verified download."

        async def execute(self, export_id: str, **kwargs: Any) -> CommandResult:
            return await self.apply(_catalog().delete_export, export_id=export_id)

        @classmethod
        def get_schema(cls) -> dict:
            return {"type": "object", "properties": {
                "export_id": {"type": "string"}
            }, "required": ["export_id"], "additionalProperties": False}

    registry.clear()
    for cls in (HelpCommand, BackupSnapshots, BackupListFiles,
                BackupPrepareDownload, BackupDownloadStatus, BackupDeleteExport):
        registry.register(cls, "custom")


def _validate_mtls_config(config: dict) -> None:
    server = config.get("server", {})
    if server.get("protocol") != "mtls":
        raise ValueError("Production server MUST use protocol=mtls")
    for key in ("cert", "key", "ca", "crl"):
        filename = server.get("ssl", {}).get(key)
        if not isinstance(filename, str) or not Path(filename).is_file():
            raise ValueError("mTLS certificate not installed: server.ssl." + key)


def make_app(config_path: str | Path):
    """Create adapter app, strip unsafe built-ins and wire read-only endpoints."""
    config_path = Path(config_path).resolve()
    config = json.loads(config_path.read_text(encoding="utf-8"))
    _validate_mtls_config(config)
    os.environ["CONFIG_FILE"] = str(config_path)
    os.environ["MCP_CONFIG_FILE"] = str(config_path)

    from fastapi import HTTPException, Request
    from fastapi.responses import FileResponse
    from mcp_proxy_adapter.api.app import create_app

    app = create_app(
        title="OneDrive Backup API",
        description="Read-only backup browse/export over mTLS",
        version="0.2.0", app_config=config, config_path=str(config_path),
    )
    _register_commands()

    # Framework registers privileged administration/transfer endpoints by default.
    # Never publish arbitrary server-local source_path transfer operations, reload,
    # config editors or command loading on the backup server, even over mTLS.
    allowed = {"/api/jsonrpc", "/api/jsonrpc/batch", "/health",
               "/openapi.json", "/docs", "/redoc"}
    app.router.routes = [
        route for route in app.router.routes
        if getattr(route, "path", None) in allowed
    ]

    def fail(exc: CatalogError) -> HTTPException:
        return HTTPException(status_code=exc.status, detail=str(exc))

    @app.get("/api/v1/health")
    async def backup_health():
        return {"status": "ok", "protocol": "mtls", "service": "onedrive-backup"}

    @app.get("/api/v1/snapshots")
    async def backup_snapshots(limit: int = 100):
        try:
            return await asyncio.to_thread(_catalog().snapshots, limit)
        except CatalogError as exc:
            raise fail(exc) from exc

    @app.get("/api/v1/snapshots/{snapshot_id}/files")
    async def backup_files(snapshot_id: str, prefix: str = "",
                           offset: int = 0, limit: int = 1000):
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
            return await asyncio.to_thread(
                _catalog().prepare, body.get("snapshot_id"),
                body.get("file_path"),
            )
        except CatalogError as exc:
            raise fail(exc) from exc
        except ValueError as exc:
            raise HTTPException(status_code=400, detail="Invalid JSON") from exc

    @app.get("/api/v1/exports/{export_id}")
    async def download_export(export_id: str):
        try:
            meta, filename = await asyncio.to_thread(_catalog().get_export, export_id)
            return FileResponse(
                filename, media_type="application/octet-stream",
                filename=meta["filename"],
                headers={"X-Content-SHA256": meta["sha256"],
                         "Cache-Control": "no-store"},
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
    """Build verified mTLS context with mandatory CRL checking (leaf)."""
    from mcp_proxy_adapter.core.app_factory.ssl_config import build_server_ssl_config
    _validate_mtls_config(config)
    settings = build_server_ssl_config(config, config_path=config_path)
    context = settings.get("ssl_context")
    if not isinstance(context, ssl.SSLContext):
        raise RuntimeError("mTLS SSLContext missing from adapter")
    crl_file = config["server"]["ssl"]["crl"]
    # Raising on absent/invalid CRL is intentional; do not permit insecure fallback.
    context.load_verify_locations(cafile=crl_file)
    context.verify_flags |= ssl.VERIFY_CRL_CHECK_LEAF
    context.verify_mode = ssl.CERT_REQUIRED
    settings["ssl_context"] = context
    settings["verify_client"] = True
    return settings


def main() -> None:
    parser = argparse.ArgumentParser(description="OneDrive Backup mTLS API server")
    parser.add_argument("--config", default="/config/server.json")
    parser.add_argument("--backup-config", default="/config/backup.json")
    parser.add_argument("--data", default="/data")
    args = parser.parse_args()
    os.environ["ONEDRIVE_BACKUP_CONFIG"] = str(Path(args.backup_config).resolve())
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
        app, {"host": server.get("host", "0.0.0.0"),
              "port": int(server.get("port", 8050)),
              "log_level": server.get("log_level", "INFO"),
              "reload": False, **settings}
    )


if __name__ == "__main__":
    main()

