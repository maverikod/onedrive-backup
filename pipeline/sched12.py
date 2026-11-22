'''Revision 12 (matrix TODO 10.20, block SCHEDULE-REV12): the product interface the offline checks drive and their shared helpers.

The product modules are written by the coder and 10.20 leaves their names open ("names are the coder's"). The checks must still run
them, so this module PINS the interface; it is recorded in the matrix as identity.reconciliations_10_20.interface. A module or a
name that is absent is an exact PRODUCT finding, never a skip.

onedrive_api.schedule_file
    DEFAULT_TEXT: str, the default schedule text of 10.20.2 (exact bytes)
    parse(text, now_utc=None, default_timezone='Europe/Kyiv') -> dict with the keys valid, problems [{line, column, code, severity,
        message}], text (normalised), revision, timezone, jitter_minutes, catchup_hours, enabled, entries [{line, expression}]
    revision(text) -> str, the lowercase hex sha256 of the UTF-8 bytes of the normalised text
    next_runs(parsed, after_utc, count) -> [{slot_local, slot_utc, start_utc, start_local, entry_lines}]
    ScheduleError(Exception) with .code (str), .status (int) and .data (dict)
    ScheduleStore(directory, storage_ok=None): bootstrap(); read(create_missing=False) -> dict (text, revision, exists, source, valid,
        problems); write(text, *, expected_revision=None, dry_run=False, actor='unknown') -> dict (written, changed, revision,
        previous_revision, backup_file)
onedrive_api.scheduler
    jitter_delay(slot_utc, jitter_minutes) -> int seconds; slots(parsed, after_utc, until_utc) -> [datetime] with after < slot <= until;
    next_state(state, revision, now_utc) -> dict (the baseline rule of 10.20.5); decide(now_utc, parsed, runs, state, lock_busy, *,
    leader=True, scaffold=False, storage_ok=True) -> Action with .kind (WAIT, START, SKIP_BUSY, NOTHING), .slot_utc, .trigger, .until,
    .reason; Scheduler(data_dir, *, clock, runner, lock_probe) with tick() -> Action (never raises; reconciles on its first tick),
    next_wait_seconds and shutdown(sleep)
onedrive_api.backup_run: main(argv) writes <ONEDRIVE_BACKUP_DATA>/schedule/runs.jsonl

A state is {schedule_revision, baseline_utc, thread_started_utc} (ISO UTC strings ending in Z); a run record is {run_id, started_at,
finished_at, exit_code, status, trigger, slot_utc} with the status values of 10.20.3.
'''

from __future__ import annotations

import importlib
import sys
from datetime import datetime, timezone
from types import ModuleType
from typing import Any

from pipeline import fixtures
from pipeline.report import Report

MODULES = {'file': 'onedrive_api.schedule_file', 'engine': 'onedrive_api.scheduler', 'run': 'onedrive_api.backup_run'}
EXPECTED_DEFAULT = (
    '# OneDrive backup schedule (edit through the API, the client, odbcli or the UI).\n'
    '# Fields: minute hour day-of-month month day-of-week. Lines starting with # are comments.\n'
    'TZ=Europe/Kyiv\nJITTER=15m\nCATCHUP=24h\n30 2 * * *\n')
ZONE = 'Europe/Kyiv'


def iso(moment: datetime) -> str:
    '''Return an aware datetime as the ISO UTC string with the Z suffix, whole seconds.'''
    return moment.astimezone(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')


def utc(year: int, month: int, day: int, hour: int = 0, minute: int = 0, second: int = 0) -> datetime:
    '''Return an aware UTC datetime.'''
    return datetime(year, month, day, hour, minute, second, tzinfo=timezone.utc)


def parse_iso(text: Any) -> datetime | None:
    '''Parse an ISO UTC string of a result or a record; return None when it is not one.'''
    try:
        return datetime.fromisoformat(str(text).replace('Z', '+00:00')).astimezone(timezone.utc)
    except ValueError:
        return None


def load(report: Report, kind: str) -> ModuleType | None:
    '''Import a product module of the pinned interface; an absent module is a PRODUCT finding (the rev 12 reason of the offline checks).

    Args:
        report: the findings collector.
        kind: file, engine or run.

    Returns:
        The module, or None after the finding.
    '''
    for item in (str(fixtures.SRC), str(fixtures.ROOT)):
        if item not in sys.path:
            sys.path.insert(0, item)
    name = MODULES[kind]
    try:
        return importlib.import_module(name)
    except ImportError as exc:
        report.product.append('%s: not importable (%s: %s); matrix TODO 10.20 requires src/%s.py' % (name, type(exc).__name__, exc, name.replace('.', '/')))
    except Exception as exc:  # noqa: BLE001 - a module that fails on import is itself a finding
        report.product.append('%s: raises on import (%s: %s)' % (name, type(exc).__name__, str(exc)[:200]))
    return None


def missing(report: Report, module: ModuleType, names: tuple[str, ...]) -> bool:
    '''Add a PRODUCT finding for every pinned name the module lacks; return True when one is missing.'''
    absent = [name for name in names if not hasattr(module, name)]
    if absent:
        report.product.append('%s lacks %s of the interface pinned in pipeline/sched12.py (10.20)' % (module.__name__, absent))
    return bool(absent)


def codes(parsed: Any) -> list[tuple[Any, str, str]]:
    '''Return the (line, code, severity) triples of a parse result, empty when the result is not a mapping with problems.'''
    problems = parsed.get('problems') if isinstance(parsed, dict) else None
    return [(item.get('line'), str(item.get('code')), str(item.get('severity'))) for item in problems or [] if isinstance(item, dict)]
