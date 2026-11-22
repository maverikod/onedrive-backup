'''schedule_engine (matrix TODO 10.20.5 and 10.20.6, rows PL17 and PL18 cases EN1-EN20): decide(), the slot rules and the scheduler core.

Mode: offline. decide() is a pure function; it is driven with fixed instants, parsed schedules, run records and states. The scheduler
core (EN10 reconcile, EN18-EN20) runs with a fake clock, a fake runner and a fake lock probe on a temporary directory: no real backup
is ever started and nothing of production is touched. All times are 2026-2027 UTC; Europe/Kyiv is UTC+2 in winter and UTC+3 in
summer. The pinned interface is in pipeline/sched12.py; an absent module is an exact PRODUCT finding.
'''

from __future__ import annotations

import functools
import hashlib
import json
import subprocess
import sys
import tempfile
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from types import ModuleType
from typing import Any, Callable
from zoneinfo import ZoneInfo

from pipeline import sched12
from pipeline.report import Report
from pipeline.sched12 import iso, utc

SLOT = utc(2026, 11, 24, 0, 30)
BASE = utc(2026, 11, 23, 10)
HEAD = 'TZ=Europe/Kyiv\nJITTER=0m\n'
TEXT = HEAD + 'CATCHUP=24h\n30 2 * * *\n'
SALT = 'onedrive-backup-schedule'


class Fixture:
    '''The modules and the helpers of one run of the check.

    Attributes:
        report: the findings collector.
        files: the product module schedule_file.
        engine: the product module scheduler.
    '''

    def __init__(self, report: Report, files: ModuleType, engine: ModuleType) -> None:
        '''Keep the run parts.

        Args:
            report: the findings collector.
            files: the product module schedule_file.
            engine: the product module scheduler.
        '''
        self.report, self.files, self.engine = report, files, engine

    def bad(self, label: str, text: str) -> None:
        '''PRODUCT finding of one case.

        Args:
            label: the case id.
            text: what differs.

        Returns:
            None.
        '''
        self.report.product.append('%s: %s' % (label, text))

    def decide(self, now: datetime, text: str = TEXT, runs: list[dict] | None = None, baseline: datetime = BASE,
               started: datetime = BASE, busy: bool = False, **flags: Any) -> tuple[Any, str | None, str | None, str | None]:
        '''Call decide() and return (kind, slot as ISO, trigger, reason).

        Args:
            now: the instant.
            text: the schedule text.
            runs: the run records.
            baseline: the baseline instant of the state.
            started: the instant the thread started.
            busy: the lock probe answer.
            flags: leader, scaffold or storage_ok.

        Returns:
            The four visible fields of the action.
        '''
        parsed = self.files.parse(text, now)
        state = {'schedule_revision': parsed['revision'], 'baseline_utc': iso(baseline), 'thread_started_utc': iso(started)}
        action = self.engine.decide(now, parsed, runs or [], state, busy, **flags)
        slot = getattr(action, 'slot_utc', None)
        return (getattr(action, 'kind', None), iso(slot) if isinstance(slot, datetime) else None, getattr(action, 'trigger', None),
                getattr(action, 'reason', None))

    def expect(self, label: str, got: tuple, kind: str, slot: datetime | None = None, trigger: str | None = None) -> bool:
        '''PRODUCT finding unless the action has the kind, the slot and the trigger.

        Args:
            label: the case id with its instant.
            got: the result of decide().
            kind: WAIT, START, SKIP_BUSY or NOTHING.
            slot: the slot of a START or SKIP_BUSY.
            trigger: the trigger of a START.

        Returns:
            True when it matches.
        '''
        want = (kind, iso(slot) if slot else None, trigger)
        have = (got[0], got[1] if slot else None, got[2] if trigger else None)
        if have != want:
            self.bad(label, 'decide() gave %s, expected %s' % (got, want))
        return have == want

    def never(self, label: str, got: tuple) -> None:
        '''PRODUCT finding when the action starts or skips a run.

        Args:
            label: the case id with its instant.
            got: the result of decide().

        Returns:
            None.
        '''
        if got[0] in ('START', 'SKIP_BUSY'):
            self.bad(label, 'decide() gave %s, expected no start and no skip' % (got,))


def rec(started: datetime, status: str, code: int | None = None, slot: datetime = SLOT) -> dict:
    '''Return one run record of the pinned shape.

    Args:
        started: the start instant.
        status: ok, errors, refused, interrupted, launch_failed, skipped_busy or running.
        code: the exit code.
        slot: the slot the run belongs to.

    Returns:
        The record.
    '''
    end = None if status == 'running' else iso(started + timedelta(seconds=30))
    return {'run_id': 'r' + iso(started), 'started_at': iso(started), 'finished_at': end, 'exit_code': code, 'status': status,
            'trigger': 'schedule', 'slot_utc': iso(slot)}


def _basic(fx: Fixture) -> None:
    '''EN1-EN4: wait before the slot, one start at the planned start, no second start, a refusal closes the slot.

    Args:
        fx: the run parts.

    Returns:
        None.
    '''
    fx.expect('EN1 one minute before the slot', fx.decide(SLOT - timedelta(minutes=1)), 'WAIT')
    until = getattr(fx.engine.decide(SLOT - timedelta(minutes=1), fx.files.parse(TEXT, SLOT), [], {'schedule_revision': fx.files.parse(TEXT, SLOT)['revision'], 'baseline_utc': iso(BASE), 'thread_started_utc': iso(BASE)}, False), 'until', None)
    if until != SLOT:
        fx.bad('EN1', 'WAIT.until is %s, expected the planned start %s' % (until, SLOT))
    fx.expect('EN2 at the planned start', fx.decide(SLOT), 'START', SLOT, 'schedule')
    live = [rec(SLOT + timedelta(seconds=5), 'running')]
    for gap in (60, 90):
        got = fx.decide(SLOT + timedelta(seconds=gap), runs=live, busy=True)
        fx.expect('EN3 tick %d s after the start' % gap, got, 'NOTHING')
    refused = [rec(SLOT + timedelta(seconds=5), 'refused', 2)]
    for gap in (90, 6 * 3600, 12 * 3600):
        fx.never('EN4 %d s after a refused run' % gap, fx.decide(SLOT + timedelta(seconds=gap), runs=refused))


def _catchup(fx: Fixture) -> None:
    '''EN5-EN8: the grace after a start, one catch-up run for several missed slots, the catch-up window.

    Args:
        fx: the run parts.

    Returns:
        None.
    '''
    started = utc(2026, 11, 24, 5, 1)
    fx.expect('EN5 inside the 120 s grace', fx.decide(started + timedelta(seconds=30), started=started), 'NOTHING')
    fx.expect('EN5 after the grace', fx.decide(started + timedelta(seconds=130), started=started), 'START', SLOT, 'catchup')
    old = utc(2026, 11, 21, 10)
    now = started + timedelta(seconds=130)
    fx.expect('EN6 three nights down, CATCHUP 24h', fx.decide(now, baseline=old, started=started), 'START', SLOT, 'catchup')
    after = [rec(now + timedelta(seconds=5), 'running')]
    fx.expect('EN6 the run satisfies every older slot', fx.decide(now + timedelta(seconds=60), baseline=old, started=started, runs=after, busy=True), 'NOTHING')
    long = HEAD + 'CATCHUP=72h\n30 2 * * *\n'
    fx.expect('EN7 three nights down, CATCHUP 72h', fx.decide(now, text=long, baseline=old, started=started), 'START', SLOT, 'catchup')
    fx.expect('EN7 one run only', fx.decide(now + timedelta(seconds=60), text=long, baseline=old, started=started, runs=after, busy=True), 'NOTHING')
    none = HEAD + 'CATCHUP=0h\n30 2 * * *\n'
    fx.never('EN8 CATCHUP=0 at 05:00', fx.decide(now, text=none, started=started))
    fx.expect('EN8 CATCHUP=0 inside the first 60 s', fx.decide(SLOT + timedelta(seconds=30), text=none), 'START', SLOT, 'schedule')


def _overlap(fx: Fixture) -> None:
    '''EN9 a still running backup skips the slot, EN10 an interrupted run is retried once.

    Args:
        fx: the run parts.

    Returns:
        None.
    '''
    yesterday = rec(utc(2026, 11, 23, 0, 31), 'running', slot=SLOT - timedelta(days=1))
    fx.expect('EN9 lock busy at the slot', fx.decide(SLOT, runs=[yesterday], busy=True), 'SKIP_BUSY', SLOT)
    closed = [dict(yesterday, status='ok', exit_code=0, finished_at=iso(utc(2026, 11, 24, 0, 40))), rec(SLOT + timedelta(seconds=10), 'skipped_busy')]
    fx.expect('EN9 the next day', fx.decide(SLOT + timedelta(days=1), runs=closed), 'START', SLOT + timedelta(days=1), 'schedule')
    again = utc(2026, 11, 24, 0, 33)
    first = [rec(SLOT + timedelta(seconds=5), 'interrupted')]
    fx.expect('EN10 one interrupted run is retried', fx.decide(again + timedelta(seconds=130), runs=first, started=again), 'START', SLOT, 'catchup')
    second = first + [rec(again + timedelta(seconds=140), 'interrupted')]
    fx.never('EN10 a second interrupted run is not retried', fx.decide(again + timedelta(minutes=10), runs=second, started=again))


def _edits(fx: Fixture) -> None:
    '''EN11-EN12: a schedule edit resets the baseline, so an edit never starts a run at once.

    Args:
        fx: the run parts.

    Returns:
        None.
    '''
    text = TEXT + '0 14 * * *\n'
    revision = fx.files.parse(text, SLOT)['revision']
    old = {'schedule_revision': 'old', 'baseline_utc': iso(BASE), 'thread_started_utc': iso(BASE)}
    for label, edit, probe, want in (('15:00 local', utc(2026, 11, 24, 13), 30, False), ('13:00 local', utc(2026, 11, 24, 11), 3600, True)):
        state = fx.engine.next_state(old, revision, edit)
        if sched12.parse_iso(state.get('baseline_utc')) != edit or state.get('schedule_revision') != revision:
            fx.bad('EN11 ' + label, 'next_state() gave %s, expected baseline %s and the new revision' % (state, iso(edit)))
            continue
        now = edit + timedelta(seconds=probe)
        parsed = fx.files.parse(text, now)
        action = fx.engine.decide(now, parsed, [], state, False)
        if want:
            fx.expect('EN11 edit at ' + label, (getattr(action, 'kind', None), iso(action.slot_utc) if getattr(action, 'slot_utc', None) else None, None), 'START', utc(2026, 11, 24, 12))
        else:
            fx.never('EN11 edit at ' + label, (getattr(action, 'kind', None), None, None, None))
    zone = 'TZ=UTC\nJITTER=0m\nCATCHUP=24h\n30 2 * * *\n'
    edit = utc(2026, 11, 24, 5)
    state = fx.engine.next_state(old, fx.files.parse(zone, edit)['revision'], edit)
    action = fx.engine.decide(edit + timedelta(seconds=30), fx.files.parse(zone, edit), [], state, False)
    fx.never('EN12 time zone edit', (getattr(action, 'kind', None), None, None, None))


def _dst(fx: Fixture) -> None:
    '''EN13 the DST slot rules, EN14 the deterministic jitter.

    Args:
        fx: the run parts.

    Returns:
        None.
    '''
    daily = fx.files.parse(HEAD + '30 3 * * *\n', SLOT)
    for label, begin, end, want in (('spring 2027-03-28', utc(2027, 3, 27, 12), utc(2027, 3, 28, 12), [utc(2027, 3, 28, 1)]),
                                    ('autumn 2026-10-25', utc(2026, 10, 24, 12), utc(2026, 10, 25, 12), [utc(2026, 10, 25, 0, 30)])):
        got = list(fx.engine.slots(daily, begin, end))
        if got != want:
            fx.bad('EN13 ' + label, 'the 03:30 slots are %s, expected exactly %s' % ([iso(item) for item in got], [iso(item) for item in want]))
    hourly = fx.files.parse(HEAD + '0 * * * *\n', SLOT)
    zone = ZoneInfo('Europe/Kyiv')
    for label, day in (('spring', date(2027, 3, 28)), ('autumn', date(2026, 10, 25))):
        before = datetime(day.year, day.month, day.day, tzinfo=zone) - timedelta(days=1)
        found = [item for item in fx.engine.slots(hourly, before, before + timedelta(days=3)) if item.astimezone(zone).date() == day]
        count = len({datetime(day.year, day.month, day.day, hour, tzinfo=zone).astimezone(UTC) for hour in range(24)})
        if len(set(found)) != count or len(found) != count:
            fx.bad('EN13 hourly ' + label, '%d distinct slots on the local day %s, expected %d (counted from zoneinfo)' % (len(found), day, count))
    delays = []
    for offset in range(30):
        slot = SLOT + timedelta(days=offset)
        delay = fx.engine.jitter_delay(slot, 15)
        formula = int(hashlib.sha256((iso(slot) + '|' + SALT).encode('utf-8')).hexdigest()[:8], 16) % 901
        if delay != formula or delay != fx.engine.jitter_delay(slot, 15) or fx.engine.jitter_delay(slot, 0) != 0:
            fx.bad('EN14', 'jitter_delay(%s, 15) is %s, expected %d from sha256(<slot ISO Z>|%s) mod 901, stable, and 0 for JITTER=0' % (iso(slot), delay, formula, SALT))
            return
        delays.append(delay)
    if len(set(delays)) <= 20 or not all(0 <= item <= 900 for item in delays):
        fx.bad('EN14', 'over 30 days the delays %s hold %d distinct values inside [0, 900], expected more than 20' % (delays[:8], len(set(delays))))


def _clock(fx: Fixture) -> None:
    '''EN15 clock steps, EN16 disabled, scaffold and storage guards, EN17 not leader.

    Args:
        fx: the run parts.

    Returns:
        None.
    '''
    done = [rec(SLOT + timedelta(seconds=5), 'running')]
    fx.never('EN15 clock stepped back 5 minutes after a start', fx.decide(SLOT - timedelta(minutes=4), runs=done, busy=True))
    fx.expect('EN15 clock stepped forward 10 hours', fx.decide(SLOT + timedelta(hours=10)), 'START', SLOT, 'catchup')
    off = 'ENABLED=no\n' + TEXT
    for hours in (0, 1, 10):
        got = fx.decide(SLOT + timedelta(hours=hours), text=off)
        if got[0] != 'NOTHING' or got[3] != 'paused':
            fx.bad('EN16 ENABLED=no at +%d h' % hours, 'decide() gave %s, expected NOTHING with the reason paused' % (got,))
    at_slot = functools.partial(fx.decide, SLOT)
    cases: list[tuple[str, str, dict[str, Any], str]] = [
            ('no entries', HEAD, {}, 'idle'), ('scaffold', TEXT, {'scaffold': True}, 'scaffold'),
            ('storage guard', TEXT, {'storage_ok': False}, 'storage_unavailable'), ('EN17 not leader', TEXT, {'leader': False}, 'not_leader')]
    for label, text, opts, reason in cases:
        got = at_slot(text, **opts)
        if got[0] != 'NOTHING' or got[3] != reason:
            fx.bad('EN16 ' + label, 'decide() at the slot gave %s, expected NOTHING with the reason %s' % (got, reason))


class Child:
    '''A fake backup child: it never exits by itself and records what the scheduler does to it.

    Attributes:
        events: the recorded calls.
        waited: the sum of the timeouts of wait().
        code: the exit code once killed.
    '''

    def __init__(self) -> None:
        '''Start alive.'''
        self.events: list[str] = []
        self.waited = 0.0
        self.code: int | None = None

    def poll(self) -> int | None:
        '''Return the exit code, None while alive.

        Returns:
            The exit code or None.
        '''
        return self.code

    def terminate(self) -> None:
        '''Record SIGTERM.

        Returns:
            None.
        '''
        self.events.append('terminate')

    def kill(self) -> None:
        '''Record SIGKILL and die.

        Returns:
            None.
        '''
        self.events.append('kill')
        self.code = -9

    def wait(self, timeout: float | None = None) -> int:
        '''Time out while alive, as subprocess does.

        Args:
            timeout: the wait bound in seconds.

        Returns:
            The exit code once dead.
        '''
        if self.code is None:
            self.waited += timeout or 0.0
            raise subprocess.TimeoutExpired('fake-backup', timeout or 0.0)
        return self.code


class Runner:
    '''A fake process runner that records argv and env and hands out Child objects.

    Attributes:
        calls: the recorded (argv, env) pairs.
        children: the children handed out.
    '''

    def __init__(self) -> None:
        '''Start empty.'''
        self.calls: list[tuple[list[str], dict[str, str]]] = []
        self.children: list[Child] = []

    def __call__(self, argv: list[str], env: dict[str, str]) -> Child:
        '''Record one start.

        Args:
            argv: the command line.
            env: the environment.

        Returns:
            A new fake child.
        '''
        self.calls.append((list(argv), dict(env)))
        self.children.append(Child())
        return self.children[-1]


class Clock:
    '''A settable clock.

    Attributes:
        now: the current instant.
    '''

    def __init__(self, now: datetime) -> None:
        '''Set the instant.

        Args:
            now: the instant.
        '''
        self.now = now

    def __call__(self) -> datetime:
        '''Return the instant.

        Returns:
            The instant.
        '''
        return self.now


def _make(fx: Fixture, base: Path, clock: Clock, probe: Callable[[], bool]) -> tuple[Any, Runner]:
    '''Write the schedule file and build a Scheduler with a fake runner.

    Args:
        fx: the run parts.
        base: the temporary data directory.
        clock: the fake clock.
        probe: the fake lock probe.

    Returns:
        The scheduler and its runner.
    '''
    (base / 'schedule').mkdir(mode=0o700, exist_ok=True)
    (base / 'schedule' / 'schedule.cron').write_text(TEXT, encoding='utf-8')
    runner = Runner()
    return fx.engine.Scheduler(base, clock=clock, runner=runner, lock_probe=probe), runner


def _threads(fx: Fixture) -> None:
    '''EN10 reconcile, EN18 the start arguments, EN19 the shutdown signals, EN20 survival of an exception.

    Args:
        fx: the run parts.

    Returns:
        None.
    '''
    with tempfile.TemporaryDirectory() as tmp:
        clock = Clock(SLOT - timedelta(minutes=10))
        sch, runner = _make(fx, Path(tmp), clock, lambda: False)
        clock.now = SLOT - timedelta(minutes=3)
        fx.never('EN18 three minutes before the slot', ('%s' % getattr(sch.tick(), 'kind', None), None, None, None))
        clock.now = SLOT
        sch.tick()
        want = {'ONEDRIVE_RUN_TRIGGER': 'schedule', 'ONEDRIVE_RUN_SLOT': iso(SLOT)}
        if len(runner.calls) != 1 or runner.calls[0][0] != [sys.executable, '-m', 'onedrive_api.backup_run'] or any(runner.calls[0][1].get(k) != v for k, v in want.items()):
            fx.bad('EN18', 'the runner was called %s, expected one call with argv [sys.executable, -m, onedrive_api.backup_run] (no --dry-run) and env %s' % ([(c[0], {k: c[1].get(k) for k in want}) for c in runner.calls], want))
        else:
            sch.shutdown(lambda seconds: setattr(runner.children[0], 'waited', runner.children[0].waited + seconds))
            child = runner.children[0]
            if child.events[:1] != ['terminate'] or 'kill' not in child.events or not 7.5 <= child.waited <= 9.0:
                fx.bad('EN19', 'the child saw %s after waiting %.1f s, expected terminate, then kill after about 8 seconds' % (child.events, child.waited))
    with tempfile.TemporaryDirectory() as tmp:
        clock = Clock(SLOT - timedelta(minutes=10))
        broken = {'on': True}

        def probe() -> bool:
            '''A lock probe that fails once.

            Returns:
                False when it works.
            '''
            if broken['on']:
                raise RuntimeError('injected probe failure')
            return False
        sch, runner = _make(fx, Path(tmp), clock, probe)
        clock.now = SLOT
        try:
            sch.tick()
        except Exception as exc:  # noqa: BLE001 - the case asserts that nothing escapes
            fx.bad('EN20', 'tick() raised %s: %s, expected the exception to be logged and the loop to continue' % (type(exc).__name__, exc))
            return
        broken['on'] = False
        clock.now = SLOT + timedelta(seconds=30)
        sch.tick()
        if getattr(sch, 'next_wait_seconds', None) is None or len(runner.calls) != 1:
            fx.bad('EN20', 'after the failed tick the next tick 30 s later started %d runs, expected 1 (next_wait_seconds %r)' % (len(runner.calls), getattr(sch, 'next_wait_seconds', None)))
    with tempfile.TemporaryDirectory() as tmp:
        base = Path(tmp)
        (base / 'schedule').mkdir(mode=0o700)
        start = {'event': 'start', 'run_id': 'r-open', 'started_at': iso(SLOT + timedelta(seconds=5)), 'trigger': 'schedule', 'slot': iso(SLOT), 'pid': 1, 'schedule_revision': None}
        (base / 'schedule' / 'runs.jsonl').write_text(json.dumps(start) + '\n', encoding='utf-8')
        sch, _ = _make(fx, base, Clock(SLOT + timedelta(minutes=5)), lambda: False)
        sch.tick()
        lines = [json.loads(line) for line in (base / 'schedule' / 'runs.jsonl').read_text(encoding='utf-8').splitlines() if line]
        closing = [item for item in lines if item.get('event') == 'end' and item.get('run_id') == 'r-open']
        if len(closing) != 1 or closing[0].get('exit_code') is not None or closing[0].get('status') != 'interrupted':
            fx.bad('EN10 reconcile', 'runs.jsonl holds %s after the first tick, expected one end line of r-open with exit_code null and status interrupted' % lines)


def run() -> None:
    '''Raise CheckFailure when decide(), the slot rules or the scheduler core differ from 10.20.5.

    Returns:
        None.
    '''
    report = Report()
    files, engine = sched12.load(report, 'file'), sched12.load(report, 'engine')
    if files is not None and engine is not None:
        names = ('decide', 'slots', 'jitter_delay', 'next_state', 'Scheduler')
        if not sched12.missing(report, engine, names) and not sched12.missing(report, files, ('parse',)):
            fx = Fixture(report, files, engine)
            for label, body in (('EN1-EN4', _basic), ('EN5-EN8', _catchup), ('EN9-EN10', _overlap), ('EN11-EN12', _edits), ('EN13-EN14', _dst),
                                ('EN15-EN17', _clock), ('EN10, EN18-EN20', _threads)):
                try:
                    body(fx)
                except Exception as exc:  # noqa: BLE001 - product code that raises is a finding of that case
                    report.product.append('%s: raised %s: %s' % (label, type(exc).__name__, str(exc)[:200]))
    report.finish('schedule_engine')
