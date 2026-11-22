"""The schedule subcommands of odbcli: schedule-get, schedule-set and schedule-status (10.20.3)."""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

from .api import BackupClient
from .errors import ClientError


def add_parsers(cmds: Any) -> None:
    """Add the three schedule subcommands to the subparsers of odbcli.

    Args:
        cmds: The subparsers action of the odbcli parser.

    Returns:
        None.
    """
    sub = cmds.add_parser("schedule-get", help="read the backup schedule: text, entries and the next runs")
    sub.add_argument("--next", type=int, dest="next_count", help="number of next runs 0..20")
    sub.add_argument("--json", action="store_true", help="print the raw JSON result")
    sub = cmds.add_parser("schedule-set", help="check or store the backup schedule text")
    source = sub.add_mutually_exclusive_group(required=True)
    source.add_argument("--file", help="file with the whole schedule text; - reads standard input")
    source.add_argument("--text", help="the whole schedule text")
    sub.add_argument("--expected-revision", dest="expected_revision", help="revision read before the edit")
    sub.add_argument("--dry-run", action="store_true", dest="dry_run", help="validate only, write nothing")
    sub.add_argument("--next", type=int, dest="next_count", help="number of next runs 0..20")
    sub = cmds.add_parser("schedule-status", help="read the scheduler state, the runs and the next run")
    sub.add_argument("--history", type=int, dest="history_limit", help="finished runs in the history 0..50")
    sub.add_argument("--json", action="store_true", help="print the raw JSON result")


def _text(args: Any) -> str:
    """Read the schedule text of schedule-set.

    Args:
        args: The parsed arguments.

    Returns:
        The text of --text, of standard input or of the --file.

    Raises:
        ClientError: The file cannot be read.
    """
    if args.text is not None:
        return str(args.text)
    if args.file == "-":
        return sys.stdin.read()
    try:
        return Path(args.file).expanduser().read_text(encoding="utf-8")
    except OSError as exc:
        raise ClientError("cannot read the schedule file: %s" % exc) from exc


def execute(client: BackupClient, args: Any) -> Any:
    """Run one schedule subcommand through the client; the actor of a write is odbcli.

    Args:
        client: The client.
        args: The parsed arguments.

    Returns:
        The result of the server command.
    """
    if args.command == "schedule-get":
        return client.schedule_get(args.next_count)
    if args.command == "schedule-set":
        return client.schedule_set(_text(args), args.expected_revision, args.dry_run, args.next_count, "odbcli")
    return client.schedule_status(args.history_limit)


def _plans(items: list) -> list[str]:
    """Format run plans one per line.

    Args:
        items: The run plans.

    Returns:
        The lines.
    """
    return ["  %s (slot %s)" % (item["start_local"], item["slot_local"]) for item in items]


def render(args: Any, result: Any) -> str:
    """Format the result: JSON, or readable text for schedule-get and schedule-status without --json.

    Args:
        args: The parsed arguments.
        result: The result of the server command.

    Returns:
        The text to print.
    """
    if args.command == "schedule-set" or getattr(args, "json", False) or not isinstance(result, dict):
        return json.dumps(result, indent=2, ensure_ascii=False)
    if args.command == "schedule-get":
        head = "revision %s, source %s, valid %s" % (result["revision"], result["source"], result["valid"])
        lines = [result["text"].rstrip("\n"), "", head]
        lines += ["entry line %d: %s" % (item["line"], item["expression"]) for item in result["entries"]]
        return "\n".join(lines + ["next runs:"] + _plans(result["next_runs"]))
    state = result["scheduler"]
    lines = ["state %s, thread alive %s, leader %s" % (state["state"], state["thread_alive"], state["leader"])]
    lines.append("current run: %s" % (result["current_run"] or "none"))
    lines.append("last run: %s" % (result["last_run"] or "none"))
    return "\n".join(lines + ["next run:"] + _plans([result["next_run"]] if result["next_run"] else []))


def problem_lines(data: Any) -> list[str]:
    """Format the problems of a refused schedule, one per line as line:column code severity message.

    Args:
        data: The error data of the server answer.

    Returns:
        The lines; empty when the data holds no problems.
    """
    items = data.get("problems") if isinstance(data, dict) else None
    return [
        "%s:%s %s %s %s" % (item.get("line"), item.get("column"), item.get("code"), item.get("severity"), item.get("message"))
        for item in items or []
        if isinstance(item, dict)
    ]
