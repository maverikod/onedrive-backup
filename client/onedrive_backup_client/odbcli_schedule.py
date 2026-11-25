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
    sub = cmds.add_parser("run-log", help="read the log of one backup run (the cause of a failed run)")
    sub.add_argument("--run-id", required=True, dest="run_id", help="run id from schedule-status")
    sub.add_argument("--offset", type=int, help="first byte of the slice")
    sub.add_argument("--limit", type=int, help="largest number of bytes 1..65536")
    sub.add_argument("--tail", action="store_true", help="read the last bytes of the log")
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
    """Run one schedule or run-log subcommand through the client; the actor of a write is odbcli.

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
    if args.command == "run-log":
        return client.run_log(args.run_id, args.offset, args.limit, True if args.tail else None)
    return client.schedule_status(args.history_limit)


def _plans(items: list) -> list[str]:
    """Format run plans one per line.

    Args:
        items: The run plans.

    Returns:
        The lines.
    """
    return ["  %s (slot %s)" % (item["start_local"], item["slot_local"]) for item in items]


def _run_line(label: str, run: Any) -> str:
    """Format one run on one line; a run that is not ok also shows its reason and the name of its log.

    Args:
        label: The text before the colon.
        run: A run object of the status, or None.

    Returns:
        The line.
    """
    if not isinstance(run, dict):
        return "%s: none" % label
    line = "%s: %s %s (exit %s) finished %s" % (
        label, str(run.get("run_id"))[:8], run.get("status"), run.get("exit_code"), run.get("finished_at")
    )
    if run.get("status") != "ok":
        log = run.get("log")
        name = log["name"] if isinstance(log, dict) and log.get("available") else "none"
        line += "; reason: %s; log: %s" % (run.get("reason") or "none recorded", name)
    return line


def render(args: Any, result: Any) -> str:
    """Format the result: JSON, the text of a run log, or readable text for schedule-get and schedule-status.

    Args:
        args: The parsed arguments.
        result: The result of the server command.

    Returns:
        The text to print.
    """
    if args.command == "schedule-set" or getattr(args, "json", False) or not isinstance(result, dict):
        return json.dumps(result, indent=2, ensure_ascii=False)
    if args.command == "run-log":
        return str(result.get("text", "")).rstrip("\n")
    if args.command == "schedule-get":
        head = "revision %s, source %s, valid %s" % (result["revision"], result["source"], result["valid"])
        lines = [result["text"].rstrip("\n"), "", head]
        lines += ["entry line %d: %s" % (item["line"], item["expression"]) for item in result["entries"]]
        return "\n".join(lines + ["next runs:"] + _plans(result["next_runs"]))
    state = result["scheduler"]
    lines = ["state %s, thread alive %s, leader %s" % (state["state"], state["thread_alive"], state["leader"])]
    lines.append("current run: %s" % (result["current_run"] or "none"))
    last = result["last_run"]
    lines.append(_run_line("last run", last))
    others = [item for item in result.get("history") or [] if isinstance(item, dict) and item.get("status") != "ok"]
    lines += [_run_line("failed run", item) for item in others if item.get("run_id") != (last or {}).get("run_id")]
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
