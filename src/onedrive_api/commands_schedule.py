"""MCP commands of the backup schedule: backup_schedule_get, backup_schedule_set, backup_schedule_status (10.20.3)."""

from __future__ import annotations

import asyncio
from typing import Any, Callable
from mcp_proxy_adapter.commands.result import CommandResult, ErrorResult

from .commands_base import CatalogCommand
from .schedule_parse import ScheduleError
from .schedule_service import schedule_get, schedule_set, schedule_status

NEXT_COUNT = {"type": "integer", "minimum": 0, "maximum": 20, "default": 5}


async def run(call: Callable[..., dict[str, Any]], **kwargs: Any) -> CommandResult:
    """Run a schedule function in a thread and turn a ScheduleError into the command error of 10.20.3.

    Args:
        call: The schedule function.
        kwargs: Its parameters.

    Returns:
        The success result, or the error result with the status, the code in the message and error.data.
    """
    try:
        return CommandResult(success=True, data=await asyncio.to_thread(call, **kwargs))
    except ScheduleError as exc:
        return ErrorResult(message="%s: %s" % (exc.code, exc), code=exc.status, details=dict(exc.data))


class BackupScheduleGet(CatalogCommand):
    """Read the backup schedule.

    Attributes:
        name: The command name.
        descr: The one-line description.
    """

    name = "backup_schedule_get"
    descr = "Read the backup schedule: the text, its revision and the next planned runs."

    async def execute(self, next_count: int = 5, **kwargs: Any) -> CommandResult:
        """Read the stored schedule; nothing is written.

        Args:
            next_count: The number of run plans, 0 to 20.
            kwargs: Ignored extra keyword arguments of the adapter.

        Returns:
            The text, revision, state, entries and next runs.
        """
        return await run(schedule_get, next_count=next_count)

    @classmethod
    def get_schema(cls) -> dict:
        """Describe the optional run count.

        Returns:
            The JSON schema.
        """
        return cls._schema_with_descriptions({
            "type": "object", "properties": {"next_count": dict(NEXT_COUNT)}, "additionalProperties": False,
        })


class BackupScheduleSet(CatalogCommand):
    """Write or check the backup schedule.

    Attributes:
        name: The command name.
        descr: The one-line description.
    """

    name = "backup_schedule_set"
    descr = "Check or store the backup schedule text; the only command that changes the schedule."

    async def execute(
        self, text: str = "", expected_revision: str | None = None, dry_run: bool = False, next_count: int = 5,
        actor: str = "unknown", **kwargs: Any,
    ) -> CommandResult:
        """Validate the text and, unless dry_run, store it atomically.

        Args:
            text: The new schedule text.
            expected_revision: The revision the caller read.
            dry_run: Validate only.
            next_count: The number of run plans, 0 to 20.
            actor: The label for the change log.
            kwargs: Ignored extra keyword arguments of the adapter.

        Returns:
            The written flag, the revision and the parsed schedule.
        """
        return await run(
            schedule_set, text=text, expected_revision=expected_revision, dry_run=dry_run, next_count=next_count, actor=actor
        )

    @classmethod
    def get_schema(cls) -> dict:
        """Describe the text and the options.

        Returns:
            The JSON schema.
        """
        return cls._schema_with_descriptions({
            "type": "object",
            "properties": {
                "text": {"type": "string"},
                "expected_revision": {"type": "string"},
                "dry_run": {"type": "boolean", "default": False},
                "next_count": dict(NEXT_COUNT),
                "actor": {"type": "string", "default": "unknown"},
            },
            "required": ["text"],
            "additionalProperties": False,
        })


class BackupScheduleStatus(CatalogCommand):
    """Read the state of the scheduler thread and the runs.

    Attributes:
        name: The command name.
        descr: The one-line description.
    """

    name = "backup_schedule_status"
    descr = "Read the scheduler state, the current and the last backup run and the next planned run."

    async def execute(self, history_limit: int = 10, **kwargs: Any) -> CommandResult:
        """Read the status; nothing is written.

        Args:
            history_limit: The number of finished runs, 0 to 50.
            kwargs: Ignored extra keyword arguments of the adapter.

        Returns:
            The scheduler, schedule, current_run, last_run, next_run, missed and history.
        """
        return await run(schedule_status, history_limit=history_limit)

    @classmethod
    def get_schema(cls) -> dict:
        """Describe the optional history length.

        Returns:
            The JSON schema.
        """
        return cls._schema_with_descriptions({
            "type": "object",
            "properties": {"history_limit": {"type": "integer", "minimum": 0, "maximum": 50, "default": 10}},
            "additionalProperties": False,
        })
