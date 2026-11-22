"""Five-field cron entries of the backup schedule: parsing, day matching and the slot instants (10.20.2)."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta, tzinfo
from typing import Iterator

MONTHS = {
    name: index
    for index, name in enumerate(("jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"), 1)
}
WEEKDAYS = {name: index for index, name in enumerate(("sun", "mon", "tue", "wed", "thu", "fri", "sat"))}
RANGES = ((0, 59), (0, 23), (1, 31), (1, 12), (0, 7))
SALT = "onedrive-backup-schedule"
ISO_FORMAT = "%Y-%m-%dT%H:%M:%SZ"


class CronError(ValueError):
    """One field of a cron entry is invalid.

    Attributes:
        code: The problem code CRON_SYNTAX, CRON_RANGE or CRON_STEP.
        index: The zero-based index of the field.
    """

    def __init__(self, code: str, index: int, message: str) -> None:
        """Keep the code and the field index.

        Args:
            code: The problem code.
            index: The zero-based index of the field.
            message: The explanation.
        """
        super().__init__(message)
        self.code = code
        self.index = index


@dataclass(frozen=True)
class CronEntry:
    """One parsed entry: the value sets of its five fields.

    Attributes:
        line: The one-based line of the entry in the file.
        expression: The five fields separated by single blanks.
        minutes: The minutes 0-59.
        hours: The hours 0-23.
        days: The days of the month 1-31.
        months: The months 1-12.
        weekdays: The days of the week 0-6, Sunday is 0.
        day_star: True when the day-of-month field starts with a star.
        weekday_star: True when the day-of-week field starts with a star.
    """

    line: int
    expression: str
    minutes: frozenset[int]
    hours: frozenset[int]
    days: frozenset[int]
    months: frozenset[int]
    weekdays: frozenset[int]
    day_star: bool
    weekday_star: bool

    def matches_day(self, day: date) -> bool:
        """Tell whether the entry can fire on a calendar day (standard cron OR rule for the two day fields).

        Args:
            day: The local calendar day.

        Returns:
            True when the month and the day fields allow the day.
        """
        if day.month not in self.months:
            return False
        by_date = day.day in self.days
        by_week = (day.weekday() + 1) % 7 in self.weekdays
        if self.day_star and self.weekday_star:
            return True
        if self.day_star:
            return by_week
        if self.weekday_star:
            return by_date
        return by_date or by_week


def iso_utc(moment: datetime) -> str:
    """Format an aware instant as ISO UTC with the Z suffix and whole seconds.

    Args:
        moment: The instant.

    Returns:
        The text YYYY-MM-DDTHH:MM:SSZ.
    """
    return moment.astimezone(UTC).strftime(ISO_FORMAT)


def parse_iso(text: object) -> datetime | None:
    """Parse an ISO UTC text of the schedule files.

    Args:
        text: The stored text.

    Returns:
        The aware UTC instant, or None when the text is not one.
    """
    try:
        return datetime.fromisoformat(str(text).replace("Z", "+00:00")).astimezone(UTC)
    except ValueError:
        return None


def jitter_delay(slot_utc: datetime, jitter_minutes: int) -> int:
    """Return the deterministic delay in seconds of one slot (10.20.2 JITTER semantics).

    Args:
        slot_utc: The slot instant.
        jitter_minutes: The JITTER directive in minutes.

    Returns:
        The delay in [0, jitter_minutes * 60]; zero without jitter.
    """
    if jitter_minutes <= 0:
        return 0
    digest = hashlib.sha256((iso_utc(slot_utc) + "|" + SALT).encode("utf-8")).hexdigest()
    return int(digest[:8], 16) % (jitter_minutes * 60 + 1)


def _value(token: str, index: int) -> int:
    """Convert one number or name of a field.

    Args:
        token: The text of the value.
        index: The zero-based field index.

    Returns:
        The number.

    Raises:
        CronError: The token is no number or name, or is out of range.
    """
    low, high = RANGES[index]
    names = MONTHS if index == 3 else WEEKDAYS if index == 4 else {}
    if token.lower() in names:
        return names[token.lower()]
    if not (token.isascii() and token.isdigit()):
        raise CronError("CRON_SYNTAX", index, "unsupported token '%s'" % token)
    number = int(token)
    if not low <= number <= high:
        raise CronError("CRON_RANGE", index, "%d is outside %d-%d" % (number, low, high))
    return number


def parse_field(text: str, index: int) -> frozenset[int]:
    """Parse one field: star, value, range, list and step.

    Args:
        text: The field text.
        index: The zero-based field index (minute, hour, day, month, weekday).

    Returns:
        The allowed values; 7 of the weekday field is Sunday 0.

    Raises:
        CronError: The field is invalid.
    """
    values: set[int] = set()
    low, high = RANGES[index]
    for part in text.split(","):
        base, slash, step_text = part.partition("/")
        step = 1
        if slash:
            if not (step_text.isascii() and step_text.isdigit()) or int(step_text) < 1:
                raise CronError("CRON_STEP", index, "step '%s' must be an integer of at least 1" % step_text)
            step = int(step_text)
        if base == "*":
            first, last = low, (6 if index == 4 else high)
        elif "-" in base:
            left, right = base.split("-", 1)
            first, last = _value(left, index), _value(right, index)
            if first > last:
                raise CronError("CRON_RANGE", index, "range %s runs backwards" % base)
        elif slash:
            raise CronError("CRON_SYNTAX", index, "a step needs a star or a range, not '%s'" % base)
        else:
            first = last = _value(base, index)
        values.update(range(first, last + 1, step))
    if index == 4:
        values = {item % 7 for item in values}
    return frozenset(values)


def make_entry(line: int, fields: list[str]) -> CronEntry:
    """Build an entry from its five fields.

    Args:
        line: The one-based line number.
        fields: The five field texts.

    Returns:
        The entry.
    """
    sets = [parse_field(text, index) for index, text in enumerate(fields)]
    return CronEntry(line, " ".join(fields), sets[0], sets[1], sets[2], sets[3], sets[4],
                     fields[2].startswith("*"), fields[4].startswith("*"))


def local_to_utc(naive: datetime, zone: tzinfo) -> datetime:
    """Return the UTC instant of a local wall-clock minute.

    A repeated time gives its first occurrence; a missing time (a gap) gives the instant the gap ends.

    Args:
        naive: The local wall-clock time without a zone.
        zone: The schedule time zone.

    Returns:
        The aware UTC instant.
    """
    moment = naive.replace(tzinfo=zone, fold=0).astimezone(UTC)
    if moment.astimezone(zone).replace(tzinfo=None) == naive:
        return moment
    after = moment.astimezone(zone).utcoffset()
    step = timedelta(minutes=1)
    for _ in range(1500):
        if (moment - step).astimezone(zone).utcoffset() != after:
            break
        moment -= step
    return moment


def day_slots(entries: list[CronEntry], day: date, zone: tzinfo) -> dict[datetime, list[int]]:
    """Return the slots of one local day, merged by instant, with the lines of the entries that made each.

    Args:
        entries: The entries.
        day: The local calendar day.
        zone: The schedule time zone.

    Returns:
        The map from the UTC instant to the entry lines.
    """
    found: dict[datetime, list[int]] = {}
    for entry in entries:
        if not entry.matches_day(day):
            continue
        for hour in sorted(entry.hours):
            for minute in sorted(entry.minutes):
                moment = local_to_utc(datetime(day.year, day.month, day.day, hour, minute), zone)
                lines = found.setdefault(moment, [])
                if entry.line not in lines:
                    lines.append(entry.line)
    return found


def iter_slots(
    entries: list[CronEntry], zone: tzinfo, after: datetime, until: datetime
) -> Iterator[tuple[datetime, tuple[int, ...]]]:
    """Yield the merged slots with after < slot <= until in time order.

    Args:
        entries: The entries.
        zone: The schedule time zone.
        after: The exclusive lower bound.
        until: The inclusive upper bound.

    Returns:
        An iterator of (UTC instant, entry lines).
    """
    day = after.astimezone(zone).date() - timedelta(days=1)
    last = until.astimezone(zone).date() + timedelta(days=1)
    while day <= last:
        for moment, lines in sorted(day_slots(entries, day, zone).items()):
            if after < moment <= until:
                yield moment, tuple(sorted(lines))
        day += timedelta(days=1)
