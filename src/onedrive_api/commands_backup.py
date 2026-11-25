"""Catalogue and staged export MCP commands."""

from __future__ import annotations

import asyncio
from typing import Any
from mcp_proxy_adapter.commands.result import CommandResult, ErrorResult
from mcp_proxy_adapter.core.errors import ValidationError

from .catalog import CatalogError
from .catalog_bytes import prepare_request, read_chunk
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
        snapshot_id: str | None = None,
        file_path: str | None = None,
        file_id: str | None = None,
        site_id: str | None = None,
        drive_id: str | None = None,
        dir: str | None = None,
        name: str | None = None,
        copy_index: int | None = None,
        inline_max_bytes: int | None = None,
        **kwargs: Any,
    ) -> CommandResult:
        if snapshot_id is None and file_id is None:
            # snapshot_id is required unless file_id is given: the same adapter error as a schema-required parameter.
            raise ValidationError(
                "Missing required parameters: snapshot_id",
                data={"missing_parameters": ["snapshot_id"], "violation": "missing"},
            )
        params = {
            "snapshot_id": snapshot_id, "file_path": file_path, "file_id": file_id, "site_id": site_id,
            "drive_id": drive_id, "dir": dir, "name": name, "copy_index": copy_index,
            "inline_max_bytes": inline_max_bytes,
        }
        return await self.apply(prepare_request, cat=_catalog(), params=params)

    @classmethod
    def get_schema(cls) -> dict:
        schema = {
            "type": "object",
            "properties": {
                "snapshot_id": {"type": "string"},
                "file_path": {"type": ["string", "null"], "default": None},
                "file_id": {"type": "string", "description": "FORM A: the file_id of a search row or a list node, alone."},
                "site_id": {"type": "string", "description": "FORM C: the site of the file, with drive_id, dir and name."},
                "drive_id": {"type": "string", "description": "FORM C: the library of the file."},
                "dir": {"type": "string", "description": "FORM C: the folder of the file, '' for the library root."},
                "name": {"type": "string", "description": "FORM C: the shown name of the file."},
                "copy_index": {
                    "type": "integer", "minimum": 0, "maximum": 99,
                    "description": "FORM C: the stored-copy index, 0 for the first copy.",
                },
                "inline_max_bytes": {
                    "type": "integer", "minimum": 0, "maximum": 65536,
                    "description": "A file of at most this many bytes comes back as content_b64 and stages no export.",
                },
            },
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


class BackupDownloadChunk(ExportCommand):
    name = "backup_download_chunk"
    descr = "Read one base64 slice of a staged export."

    async def execute(
        self,
        export_id: str = "",
        offset: int = 0,
        limit: int = 65536,
        **kwargs: Any,
    ) -> CommandResult:
        return await self.apply(read_chunk, cat=_catalog(), export_id=export_id, offset=offset, limit=limit)

    @classmethod
    def get_schema(cls) -> dict:
        schema = {
            "type": "object",
            "properties": {
                "export_id": {"type": "string", "pattern": "^[0-9a-f]{32}$", "minLength": 32, "maxLength": 32},
                "offset": {"type": "integer", "minimum": 0, "maximum": 1099511627776, "default": 0},
                "limit": {"type": "integer", "minimum": 1, "maximum": 262144, "default": 65536},
            },
            "required": ["export_id"],
            "additionalProperties": False,
        }
        return cls._schema_with_descriptions(schema)


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
