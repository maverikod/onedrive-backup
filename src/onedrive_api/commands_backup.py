"""Catalogue and staged export MCP commands."""

from __future__ import annotations

import asyncio
from typing import Any
from mcp_proxy_adapter.commands.result import CommandResult, ErrorResult

from .catalog import CatalogError
from .commands_base import CatalogCommand, ExportCommand, _catalog


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


class BackupDownloadStatus(ExportCommand):
    name = "backup_download_status"
    descr = "Inspect staged export metadata and SHA256."

    async def execute(
        self,
        export_id: str = "",
        **kwargs: Any,
    ) -> CommandResult:
        archive = _catalog()
        return await self.apply(archive.export_status, export_id=export_id)


class BackupDownloadBegin(ExportCommand):
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


class BackupDeleteExport(ExportCommand):
    name = "backup_delete_export"
    descr = "Delete staged plaintext export after a verified download."

    async def execute(
        self,
        export_id: str = "",
        **kwargs: Any,
    ) -> CommandResult:
        archive = _catalog()
        return await self.apply(archive.delete_export, export_id=export_id)
