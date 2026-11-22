"""The pure decision of the backup scheduler: slots, the baseline rule and decide() (10.20.5, rules E1-E8)."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

from .schedule_cron import iso_utc, iter_slots, jitter_delay, parse_iso

GRACE_SECONDS = 120
START_WINDOW_SECONDS = 60
MAX_ATTEMPTS = 2
CLOSING = ("ok", "errors", "refused", "launch_failed", "skipped_busy", "running")


@dataclass
class Action:
    """What the scheduler does next.

    Attributes:
        kind: WAIT, START, SKIP_BUSY or NOTHING.
        slot_utc: The slot of a START or SKIP_BUSY, or the slot a NOTHING is about.
        trigger: schedule or catchup for a START.
        until: The planned start the WAIT waits for.
        reason: Why nothing is done.
    """

    kind: str
    slot_utc: datetime | None = None
    trigger: str | None = None
    until: datetime | None = None
    reason: str | None = None


def slots(parsed: dict[str, Any], after_utc: datetime, until_utc: datetime) -> list[datetime]:
    """List the merged slots with after < slot <= until.

    Args:
        parsed: The result of parse().
        after_utc: The exclusive lower bound.
        until_utc: The inclusive upper bound.

    Returns:
        The slot instants in order.
    """
    zone = ZoneInfo(parsed["timezone"])
    return [moment for moment, _ in iter_slots(parsed["_cron"], zone, after_utc, until_utc)]


def next_state(state: dict[str, Any], revision: str, now_utc: datetime) -> dict[str, Any]:
    """Apply the baseline rule: a revision other than the stored one moves the baseline to now.

    Args:
        state: The scheduler state with schedule_revision, baseline_utc and thread_started_utc.
        revision: The revision of the effective schedule.
        now_utc: The instant of the observation.

    Returns:
        The new state; the old one when the revision is unchanged.
    """
    if state.get("schedule_revision") == revision:
        return dict(state)
    return dict(state, schedule_revision=revision, baseline_utc=iso_utc(now_utc))


def _planned(slot: datetime, parsed: dict[str, Any]) -> datetime:
    """Return the planned start of a slot: the slot plus its deterministic jitter.

    Args:
        slot: The slot instant.
        parsed: The result of parse().

    Returns:
        The planned start.
    """
    return slot + timedelta(seconds=jitter_delay(slot, parsed["jitter_minutes"]))


def due_slot(parsed: dict[str, Any], now: datetime, baseline: datetime) -> datetime | None:
    """Find the newest slot after the baseline whose planned start has come.

    Args:
        parsed: The result of parse().
        now: The instant of the decision.
        baseline: The reference point; slots at or before it are never missed.

    Returns:
        The slot, or None.
    """
    lower = max(baseline, now - timedelta(hours=parsed["catchup_hours"] + 49))
    found = None
    for slot in slots(parsed, lower, now):
        if _planned(slot, parsed) <= now:
            found = slot
    return found


def next_planned(parsed: dict[str, Any], now: datetime) -> datetime | None:
    """Find the first planned start after the instant.

    Args:
        parsed: The result of parse().
        now: The instant.

    Returns:
        The planned start, or None when no slot follows within 800 days.
    """
    lower = now - timedelta(minutes=parsed["jitter_minutes"], seconds=1)
    for slot in slots(parsed, lower, now + timedelta(days=800)):
        planned = _planned(slot, parsed)
        if planned > now:
            return planned
    return None


def _guard(parsed: dict[str, Any], leader: bool, scaffold: bool, storage_ok: bool) -> str | None:
    """Apply rule E1: the reason nothing may start, or None.

    Args:
        parsed: The result of parse().
        leader: True for the process that holds the leader lock.
        scaffold: True in scaffold mode.
        storage_ok: The result of the storage guard G2.

    Returns:
        not_leader, scaffold, storage_unavailable, paused, idle or None.
    """
    if not leader:
        return "not_leader"
    if scaffold:
        return "scaffold"
    if not storage_ok:
        return "storage_unavailable"
    if not parsed["enabled"]:
        return "paused"
    if not parsed["_cron"]:
        return "idle"
    return None


def decide(
    now_utc: datetime,
    parsed: dict[str, Any],
    runs: list[dict[str, Any]],
    state: dict[str, Any],
    lock_busy: bool,
    *,
    leader: bool = True,
    scaffold: bool = False,
    storage_ok: bool = True,
) -> Action:
    """Decide the next action from the schedule, the run records, the state and the lock probe (rules E1-E8).

    Args:
        now_utc: The instant of the decision.
        parsed: The effective schedule, the result of parse().
        runs: The run records, oldest first.
        state: schedule_revision, baseline_utc and thread_started_utc.
        lock_busy: True when somebody holds the backup lock.
        leader: True for the process that holds the leader lock.
        scaffold: True in scaffold mode.
        storage_ok: The result of the storage guard G2.

    Returns:
        WAIT with the planned start, START or SKIP_BUSY with the slot, or NOTHING with the reason.
    """
    reason = _guard(parsed, leader, scaffold, storage_ok)
    if reason:
        return Action("NOTHING", reason=reason)
    baseline = parse_iso(state.get("baseline_utc")) or now_utc
    started = parse_iso(state.get("thread_started_utc")) or baseline
    slot = due_slot(parsed, now_utc, baseline)
    if slot is None:
        return Action("WAIT", until=next_planned(parsed, now_utc))
    mine = [item for item in runs if not item.get("dry_run") and (parse_iso(item.get("started_at")) or now_utc) >= slot]
    if any(item["status"] in CLOSING and (item["status"] != "running" or lock_busy) for item in mine):
        return Action("NOTHING", slot_utc=slot, reason="satisfied")
    if sum(1 for item in mine if item["status"] in ("interrupted", "running")) >= MAX_ATTEMPTS:
        return Action("NOTHING", slot_utc=slot, reason="attempts_exhausted")
    if now_utc < started + timedelta(seconds=GRACE_SECONDS):
        return Action("NOTHING", slot_utc=slot, reason="grace")
    trigger = "schedule"
    if now_utc - _planned(slot, parsed) > timedelta(seconds=START_WINDOW_SECONDS):
        if now_utc - slot > timedelta(hours=parsed["catchup_hours"]):
            return Action("NOTHING", slot_utc=slot, reason="dropped")
        trigger = "catchup"
    if lock_busy:
        return Action("SKIP_BUSY", slot_utc=slot)
    return Action("START", slot_utc=slot, trigger=trigger)
