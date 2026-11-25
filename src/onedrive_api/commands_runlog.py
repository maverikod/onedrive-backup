"""MCP command backup_run_log: a bounded, read-only slice of the log of one backup run (matrix row M24)."""

from __future__ import annotations

from typing import Any

from mcp_proxy_adapter.commands.result import CommandResult

from .commands_base import CatalogCommand
from .run_diag import DEFAULT_LIMIT, read_run_log
from .schedule_service import data_dir


class BackupRunLog(CatalogCommand):
    """Read a slice of the log file of one recorded backup run.

    Attributes:
        name: The command name.
        descr: The one-line description.
    """

    name = "backup_run_log"
    descr = "Read a bounded slice of the log of one backup run: the cause of a failed run, secrets removed."

    async def execute(
        self, run_id: str = "", offset: int | None = None, limit: int = DEFAULT_LIMIT, tail: bool = False, **kwargs: Any
    ) -> CommandResult:
        """Read the slice; nothing is written and no backup lock is taken.

        Args:
            run_id: The run id from backup_schedule_status.history.
            offset: First byte of the slice, 0 when omitted; not together with tail.
            limit: Largest number of bytes, 1..65536.
            tail: True to read the last limit bytes.
            kwargs: Ignored extra keyword arguments of the adapter.

        Returns:
            The slice with its position, size and eof flag.
        """
        return await self.apply(read_run_log, data_dir=data_dir(), run_id=run_id, offset=offset, limit=limit, tail=tail)

    @classmethod
    def get_schema(cls) -> dict:
        """Describe the run id and the slice bounds.

        Returns:
            The JSON schema.
        """
        return cls._schema_with_descriptions({
            "type": "object",
            "properties": {
                "run_id": {"type": "string", "pattern": "^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$"},
                "offset": {"type": "integer", "minimum": 0, "maximum": 10485760},
                "limit": {"type": "integer", "minimum": 1, "maximum": 65536, "default": DEFAULT_LIMIT},
                "tail": {"type": "boolean", "default": False},
            },
            "required": ["run_id"],
            "additionalProperties": False,
        })
