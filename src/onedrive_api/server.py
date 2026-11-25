"""Adapter-only OneDrive Backup server: JSON-RPC commands, the temporary download link and the adapter transfer.

The listener, TLS, authentication and routes are the mcp-proxy-adapter's own, driven by its configuration file
(server.protocol, ssl, auth). This module owns no transport, TLS, route-filter, middleware or authentication code.
"""

from __future__ import annotations

import argparse
import json
import logging
import os
from pathlib import Path

from .catalog import EXPORT_RE, Catalog, CatalogError
from .version import read_version

LOG = logging.getLogger(__name__)
WEB_DIR_ENV = "ONEDRIVE_BACKUP_WEB"
DEFAULT_WEB_DIR = "/app/web"


def _catalog() -> Catalog:
    return Catalog(
        os.environ.get("ONEDRIVE_BACKUP_CONFIG", "/config/backup.json"),
        os.environ.get("ONEDRIVE_BACKUP_DATA", "/data"),
        max_export_bytes=int(
            os.environ.get("ONEDRIVE_MAX_EXPORT_BYTES", str(10 * 1024**3))
        ),
    )


def validate_transfer(config: dict) -> dict:
    """Require a transfer section confined to the exports directory; the adapter denies all otherwise."""
    message = "Production server MUST confine transfer.allowed_directories to the exports directory"
    transfer = config.get("transfer")
    if not isinstance(transfer, dict):
        raise ValueError(message)
    dirs = transfer.get("allowed_directories")
    if not (isinstance(dirs, list) and dirs and all(isinstance(item, str) and item.strip() for item in dirs)):
        raise ValueError(message)
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
        BackupDownloadChunk,
        BackupDownloadStatus,
        BackupListFiles,
        BackupPrepareDownload,
        BackupSnapshots,
    )
    from .commands_base import BackupHelpCommand
    from .commands_filter import BackupFilterOptions, BackupFolderChildren, BackupSearchFiles, BackupSuggestNames
    from .commands_schedule import BackupScheduleGet, BackupScheduleSet, BackupScheduleStatus
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
        BackupDownloadChunk,
        BackupDownloadBegin,
        BackupDeleteExport,
        BackupSitesList,
        BackupLibrariesList,
        BackupDiscoveryStatus,
        BackupFilterOptions,
        BackupSearchFiles,
        BackupSuggestNames,
        BackupFolderChildren,
        BackupScheduleGet,
        BackupScheduleSet,
        BackupScheduleStatus,
    ):
        registry.register(cls, "custom")


def _start_index_catchup() -> None:
    """Index in the background every snapshot that the file name index does not know yet (matrix 10.19.6)."""
    import logging
    import sqlite3
    from .file_index import FileIndex
    from .file_index_build import ensure_catchup

    index = FileIndex(os.environ.get("ONEDRIVE_BACKUP_DATA", "/data"))
    try:
        index.connect().close()  # creates the index file_dir of matrix 10.21.2 when the data directory lacks it
    except (OSError, sqlite3.Error):
        logging.getLogger(__name__).warning("File index: not opened at start (read-only data directory?)")
    ensure_catchup(_catalog, index)


def make_app(config_path: str | Path):
    """Create the adapter application with its read-only commands and the one static mount."""
    config_path = Path(config_path).resolve()
    config = json.loads(config_path.read_text(encoding="utf-8"))
    transfer = validate_transfer(config)
    os.environ["CONFIG_FILE"] = str(config_path)
    os.environ["MCP_CONFIG_FILE"] = str(config_path)

    from mcp_proxy_adapter.api.app import create_app
    from mcp_proxy_adapter.api.public_downloads import set_public_download_resolver
    from mcp_proxy_adapter.config import get_config
    from starlette.staticfiles import StaticFiles

    app = create_app(
        title="OneDrive Backup API",
        description="Read-only backup browse/export over HTTPS",
        version=read_version(),
        app_config=config,
        config_path=str(config_path),
    )
    # The adapter reads the transfer section from its global configuration, which does not load
    # this server's configuration file on its own: without this call every transfer is denied.
    get_config().set("transfer", transfer)
    _register_commands()
    _start_index_catchup()
    set_public_download_resolver(app, _resolve_download)
    # The built SPA is served by the service itself on the same origin as the last route, so it never shadows an adapter
    # route; it answers GET and HEAD only and 404 for an absent file.
    web_dir = os.environ.get(WEB_DIR_ENV, DEFAULT_WEB_DIR)
    # html=True serves the index page at / (hash routing: no history fallback, an unknown path stays 404).
    app.mount("/", StaticFiles(directory=web_dir, html=True, check_dir=False), name="web")
    return app


def main() -> None:
    parser = argparse.ArgumentParser(description="OneDrive Backup server (mcp-proxy-adapter, HTTPS from its configuration)")
    parser.add_argument("--config", default="/config/server.json")
    parser.add_argument("--backup-config", default="/config/backup.json")
    parser.add_argument("--data", default="/data")
    args = parser.parse_args()
    backup_config = Path(args.backup_config).resolve()
    os.environ["ONEDRIVE_BACKUP_CONFIG"] = str(backup_config)
    os.environ["ONEDRIVE_BACKUP_DATA"] = str(Path(args.data).resolve())
    path = str(Path(args.config).resolve())
    config = json.loads(Path(path).read_text(encoding="utf-8"))
    app = make_app(path)
    # The backup scheduler thread starts with the process, before the listener (matrix 10.20.5).
    from .scheduler import start_scheduler
    from .run_log import ensure_logs_dir

    scheduler = start_scheduler(os.environ["ONEDRIVE_BACKUP_DATA"])
    if scheduler.storage_guard():
        # The run log directory exists before the first run, so that RL5 holds right after a deploy (matrix PL20).
        ensure_logs_dir(os.environ["ONEDRIVE_BACKUP_DATA"])

    from mcp_proxy_adapter.core.app_factory.ssl_config import build_server_ssl_config
    from mcp_proxy_adapter.core.logging import setup_logging
    from mcp_proxy_adapter.core.server_engine import ServerEngineFactory

    # The adapter derives the TLS mode from server.protocol alone (https: server authentication only).
    settings = build_server_ssl_config(config, config_path=path)
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
