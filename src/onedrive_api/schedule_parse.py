"""The schedule text: directives, cron entries, problems, the revision and the run plans (10.20.2, 10.20.3)."""

from __future__ import annotations

import hashlib
import re
from datetime import UTC, datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from .schedule_cron import CronEntry, CronError, iso_utc, iter_slots, jitter_delay, make_entry

DEFAULT_TEXT = (
    "# OneDrive backup schedule (edit through the API, the client, odbcli or the UI).\n"
    "# Fields: minute hour day-of-month month day-of-week. Lines starting with # are comments.\n"
    "TZ=Europe/Kyiv\nJITTER=15m\nCATCHUP=24h\n30 2 * * *\n"
)
MAX_BYTES = 16384
MAX_LINES = 200
MAX_LINE_LENGTH = 256
MAX_ENTRIES = 20
MIN_GAP_MINUTES = 30
DIRECTIVES = ("TZ", "JITTER", "CATCHUP", "ENABLED")
COMMENT = re.compile(r"(?:^|\s)#")
DIRECTIVE = re.compile(r"[A-Za-z_][A-Za-z0-9_]*=")


class ScheduleError(Exception):
    """A schedule command failure with its status and string code.

    Attributes:
        code: The string code, for example INVALID_SCHEDULE.
        status: The numeric status, for example 400.
        data: The extra details of the answer.
    """

    def __init__(self, code: str, status: int, message: str = "", data: dict[str, Any] | None = None) -> None:
        """Keep the code, the status and the details.

        Args:
            code: The string code.
            status: The numeric status.
            message: The explanation; the code when empty.
            data: The extra details.
        """
        super().__init__(message or code)
        self.code = code
        self.status = status
        self.data = data or {}


def revision(text: str) -> str:
    """Return the lowercase hex sha256 of the UTF-8 bytes of a text.

    Args:
        text: The normalised text.

    Returns:
        The revision.
    """
    return hashlib.sha256(text.encode("utf-8", "replace")).hexdigest()


def normalise(text: str) -> str:
    """Convert line ends to LF and end a non-empty text with one LF.

    Args:
        text: The text as sent or stored.

    Returns:
        The normalised text.
    """
    result = text.replace("\r\n", "\n").replace("\r", "\n")
    if result and not result.endswith("\n"):
        result += "\n"
    return result


class _Parser:
    """The state of one parse run.

    Attributes:
        problems: The problems found.
        zone: The effective time zone name.
        jitter: The JITTER minutes.
        catchup: The CATCHUP hours.
        enabled: The ENABLED flag.
        entries: The valid entries.
        entry_lines: The number of entry lines, valid or not.
        seen: The line of each directive found.
    """

    def __init__(self, zone: str) -> None:
        """Start with the defaults.

        Args:
            zone: The default time zone name.
        """
        self.problems: list[dict[str, Any]] = []
        self.zone = zone
        self.jitter = 0
        self.catchup = 24
        self.enabled = True
        self.entries: list[CronEntry] = []
        self.entry_lines = 0
        self.seen: dict[str, int] = {}

    def add(self, line: int | None, column: int | None, code: str, severity: str, message: str) -> None:
        """Record one problem.

        Args:
            line: The line, None for a whole-file problem.
            column: The column, None when not known.
            code: The problem code.
            severity: error or warning.
            message: The explanation.

        Returns:
            None.
        """
        self.problems.append(
            {"line": line, "column": column, "code": code, "severity": severity, "message": message}
        )

    def directive(self, number: int, name: str, value: str) -> None:
        """Apply one NAME=value directive.

        Args:
            number: The line number.
            name: The directive name.
            value: The text after the equals sign.

        Returns:
            None.
        """
        if name not in DIRECTIVES:
            self.add(number, 1, "UNKNOWN_DIRECTIVE", "error", "unknown directive %s" % name)
        elif name in self.seen:
            message = "%s is set on line %d already" % (name, self.seen[name])
            self.add(number, 1, "DUPLICATE_DIRECTIVE", "error", message)
        else:
            self.seen[name] = number
            self._value(number, name, value.strip())

    def _value(self, number: int, name: str, value: str) -> None:
        """Check and store the value of a directive.

        Args:
            number: The line number.
            name: The directive name.
            value: The trimmed value.

        Returns:
            None.
        """
        column = len(name) + 2
        if name == "TZ":
            try:
                ZoneInfo(value)
                self.zone = value
            except (ZoneInfoNotFoundError, ValueError, OSError):
                self.add(number, column, "TZ_UNKNOWN", "error", "unknown time zone %s" % value)
        elif name == "JITTER":
            found = re.fullmatch("([0-9]{1,3})m", value)
            if found and int(found.group(1)) <= 60:
                self.jitter = int(found.group(1))
            else:
                self.add(number, column, "JITTER_RANGE", "error", "JITTER is <n>m with n from 0 to 60")
        elif name == "CATCHUP":
            found = re.fullmatch("([0-9]{1,4})h", value)
            if found and int(found.group(1)) <= 168:
                self.catchup = int(found.group(1))
            else:
                self.add(number, column, "CATCHUP_RANGE", "error", "CATCHUP is <n>h with n from 0 to 168")
        elif value in ("yes", "no"):
            self.enabled = value == "yes"
        else:
            self.add(number, column, "ENABLED_VALUE", "error", "ENABLED is yes or no")

    def entry(self, number: int, body: str) -> None:
        """Parse one entry line of five fields.

        Args:
            number: The line number.
            body: The line without its comment.

        Returns:
            None.
        """
        tokens = [(item.group(), item.start() + 1) for item in re.finditer(r"\S+", body)]
        self.entry_lines += 1
        if tokens[0][0].startswith("@"):
            self.add(number, 1, "CRON_SYNTAX", "error", "macros such as %s are not supported" % tokens[0][0])
        elif len(tokens) != 5:
            self.add(number, 1, "CRON_FIELD_COUNT", "error", "an entry has five fields, found %d" % len(tokens))
        else:
            try:
                self.entries.append(make_entry(number, [item[0] for item in tokens]))
            except CronError as exc:
                self.add(number, tokens[exc.index][1], exc.code, "error", str(exc))

    def line(self, number: int, raw: str) -> None:
        """Parse one line: a directive, an entry, a comment or a blank.

        Args:
            number: The line number.
            raw: The line without its end.

        Returns:
            None.
        """
        if len(raw) > MAX_LINE_LENGTH:
            message = "a line holds at most %d characters" % MAX_LINE_LENGTH
            self.add(number, MAX_LINE_LENGTH + 1, "LINE_TOO_LONG", "error", message)
        for index, char in enumerate(raw):
            if (ord(char) < 32 and char != "\t") or ord(char) == 127:
                self.add(number, index + 1, "CONTROL_CHARACTER", "error", "a control character is not allowed")
                return
        found = COMMENT.search(raw)
        body = raw[: found.start()] if found else raw
        if not body.strip():
            return
        if DIRECTIVE.match(body.strip()):
            name, _, value = body.strip().partition("=")
            self.directive(number, name, value)
        else:
            self.entry(number, body)

    def semantics(self, now: datetime) -> None:
        """Check that every entry fires and that the slots keep the minimum distance.

        Args:
            now: The instant the horizons start from.

        Returns:
            None.
        """
        zone = ZoneInfo(self.zone)
        live = []
        for entry in self.entries:
            if next(iter_slots([entry], zone, now, now + timedelta(days=8 * 366)), None) is None:
                self.add(entry.line, 1, "NEVER_FIRES", "error", "the entry does not fire within eight years")
            else:
                live.append(entry)
        previous = None
        for moment, lines in iter_slots(live, zone, now, now + timedelta(days=366)):
            if previous is not None and moment - previous < timedelta(minutes=MIN_GAP_MINUTES):
                message = "two slots are less than %d minutes apart" % MIN_GAP_MINUTES
                self.add(max(lines), 1, "TOO_FREQUENT", "error", message)
                break
            previous = moment

    def warnings(self) -> None:
        """Add the warnings: no entry, day fields combined by OR, a duplicated entry.

        Returns:
            None.
        """
        if self.entry_lines == 0:
            self.add(None, None, "NO_ENTRIES", "warning", "the schedule has no entry: no backup will start")
        expressions: dict[str, int] = {}
        for entry in self.entries:
            if not entry.day_star and not entry.weekday_star:
                self.add(entry.line, 1, "DOM_DOW_OR", "warning", "day-of-month and day-of-week are combined by OR")
            if entry.expression in expressions:
                message = "same as line %d" % expressions[entry.expression]
                self.add(entry.line, 1, "DUPLICATE_ENTRY", "warning", message)
            expressions.setdefault(entry.expression, entry.line)


def parse(text: str, now_utc: datetime | None = None, default_timezone: str = "Europe/Kyiv") -> dict[str, Any]:
    """Parse and validate a schedule text, reporting every problem found.

    Args:
        text: The schedule text.
        now_utc: The instant of the semantic checks; now when omitted.
        default_timezone: The zone used when the text has no TZ directive.

    Returns:
        The result: valid, problems, text (normalised), revision, timezone, jitter_minutes, catchup_hours, enabled,
        entries, and the private key _cron with the parsed entries.
    """
    parser = _Parser(default_timezone)
    try:
        text.encode("utf-8")
    except UnicodeEncodeError:
        parser.add(None, None, "ENCODING", "error", "the text is not valid UTF-8")
        text = text.encode("utf-8", "replace").decode("utf-8")
    normalised = normalise(text)
    lines = normalised.split("\n")[:-1] if normalised else []
    if len(lines) > MAX_LINES:
        parser.add(None, None, "TOO_MANY_LINES", "error", "a schedule holds at most %d lines" % MAX_LINES)
    for number, raw in enumerate(lines[:MAX_LINES], 1):
        parser.line(number, raw)
    if parser.entry_lines > MAX_ENTRIES:
        parser.add(None, None, "TOO_MANY_ENTRIES", "error", "a schedule holds at most %d entries" % MAX_ENTRIES)
    else:
        parser.semantics(now_utc or datetime.now(UTC))
    parser.warnings()
    parser.problems.sort(key=lambda item: (item["severity"] != "error", item["line"] or 0))
    return {
        "valid": not any(item["severity"] == "error" for item in parser.problems),
        "problems": parser.problems,
        "text": normalised,
        "revision": revision(normalised),
        "timezone": parser.zone,
        "jitter_minutes": parser.jitter,
        "catchup_hours": parser.catchup,
        "enabled": parser.enabled,
        "entries": [{"line": item.line, "expression": item.expression} for item in parser.entries],
        "_cron": parser.entries,
    }


def run_plan(slot: datetime, lines: tuple[int, ...], zone: ZoneInfo, jitter: int) -> dict[str, Any]:
    """Describe one slot as a run plan.

    Args:
        slot: The slot instant.
        lines: The entry lines that made the slot.
        zone: The schedule time zone.
        jitter: The JITTER minutes.

    Returns:
        The run plan of 10.20.3.
    """
    start = slot + timedelta(seconds=jitter_delay(slot, jitter))
    return {
        "slot_local": slot.astimezone(zone).isoformat(),
        "slot_utc": iso_utc(slot),
        "start_utc": iso_utc(start),
        "start_local": start.astimezone(zone).isoformat(),
        "entry_lines": list(lines),
    }


def next_runs(parsed: dict[str, Any], after_utc: datetime, count: int) -> list[dict[str, Any]]:
    """Return the next run plans ordered by planned start, each starting after the given instant.

    Args:
        parsed: The result of parse().
        after_utc: The instant the plans must start after.
        count: The number of plans wanted.

    Returns:
        The run plans; empty when the schedule is disabled or has no entry.
    """
    if count <= 0 or not parsed["enabled"] or not parsed["_cron"]:
        return []
    zone = ZoneInfo(parsed["timezone"])
    jitter = parsed["jitter_minutes"]
    plans: list[dict[str, Any]] = []
    lower = after_utc - timedelta(minutes=jitter, seconds=1)
    for slot, lines in iter_slots(parsed["_cron"], zone, lower, after_utc + timedelta(days=800)):
        if len(plans) >= count and iso_utc(slot) > plans[count - 1]["start_utc"]:
            break
        plan = run_plan(slot, lines, zone, jitter)
        if plan["start_utc"] > iso_utc(after_utc):
            plans.append(plan)
            plans.sort(key=lambda item: item["start_utc"])
    return plans[:count]


def entry_views(parsed: dict[str, Any], after_utc: datetime) -> list[dict[str, Any]]:
    """Return the entries of a parse result with the next planned start of each.

    Args:
        parsed: The result of parse().
        after_utc: The instant the starts must follow.

    Returns:
        A list of {line, expression, next_start_utc}; next_start_utc is None while the schedule is disabled.
    """
    zone = ZoneInfo(parsed["timezone"])
    jitter = parsed["jitter_minutes"]
    views = []
    for entry in parsed["_cron"]:
        found = None
        if parsed["enabled"]:
            lower = after_utc - timedelta(minutes=jitter, seconds=1)
            for slot, lines in iter_slots([entry], zone, lower, after_utc + timedelta(days=800)):
                plan = run_plan(slot, lines, zone, jitter)
                if plan["start_utc"] > iso_utc(after_utc):
                    found = plan["start_utc"]
                    break
        views.append({"line": entry.line, "expression": entry.expression, "next_start_utc": found})
    return views
