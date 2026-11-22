'''schedule_file (matrix TODO 10.20.2, 10.20.3, 10.20.6; rows PL16, M16 text, cases SC4, SC5, ST1-ST9): the parser and the store.

Mode: offline. The pure parser is called with fixed texts and a fixed instant; the store runs on a temporary directory. Nothing of the
production service or its data is read or written. The product module src/onedrive_api/schedule_file.py is written by the coder;
the interface the check drives is pinned in pipeline/sched12.py. An absent module is an exact PRODUCT finding.
'''

from __future__ import annotations

import functools
import hashlib
import json
import os
import re
import tempfile
import threading
from datetime import timedelta
from pathlib import Path
from types import ModuleType
from typing import Any, Callable
from unittest import mock

from pipeline import sched12
from pipeline.report import Report

NOW = sched12.utc(2026, 11, 24, 12)
BACKUP_NAME = re.compile(r'^schedule[.][0-9]{8}T[0-9]{6}Z[.][0-9a-f]{8}[.]cron$')
PROBLEM_KEYS = {'line', 'column', 'code', 'severity', 'message'}
PARSED_KEYS = ('valid', 'problems', 'text', 'revision', 'timezone', 'jitter_minutes', 'catchup_hours', 'enabled', 'entries')
TZ = 'TZ=Europe/Kyiv\n'
# SC4: (label, text, [(line, code)]); a line of None marks a whole-file problem.
BAD: list[tuple[str, str, list[tuple[int | None, str]]]] = [
    ('61 2 * * *', TZ + '61 2 * * *\n', [(2, 'CRON_RANGE')]),
    ('30 2 * *', TZ + '30 2 * *\n', [(2, 'CRON_FIELD_COUNT')]),
    ('30 2 * * * extra', TZ + '30 2 * * * extra\n', [(2, 'CRON_FIELD_COUNT')]),
    ('*/0 * * * *', TZ + '*/0 * * * *\n', [(2, 'CRON_STEP')]),
    ('*/10 * * * *', TZ + '*/10 * * * *\n', [(2, 'TOO_FREQUENT')]),
    ('0 0 31 2 *', TZ + '0 0 31 2 *\n', [(2, 'NEVER_FIRES')]),
    ('@daily', TZ + '@daily\n', [(2, 'CRON_SYNTAX')]),
    ('TZ=Mars/Base', 'TZ=Mars/Base\n30 2 * * *\n', [(1, 'TZ_UNKNOWN')]),
    ('JITTER=61m', 'JITTER=61m\n30 2 * * *\n', [(1, 'JITTER_RANGE')]),
    ('JITTER=15', 'JITTER=15\n30 2 * * *\n', [(1, 'JITTER_RANGE')]),
    ('CATCHUP=200h', 'CATCHUP=200h\n30 2 * * *\n', [(1, 'CATCHUP_RANGE')]),
    ('ENABLED=maybe', 'ENABLED=maybe\n30 2 * * *\n', [(1, 'ENABLED_VALUE')]),
    ('two TZ lines', 'TZ=UTC\nTZ=UTC\n30 2 * * *\n', [(2, 'DUPLICATE_DIRECTIVE')]),
    ('FOO=1', 'FOO=1\n30 2 * * *\n', [(1, 'UNKNOWN_DIRECTIVE')]),
    ('21 entries', ''.join('0 %d * * *\n' % hour for hour in range(21)), [(None, 'TOO_MANY_ENTRIES')]),
    ('NUL', '30 2 * * *\x00\n', [(1, 'CONTROL_CHARACTER')]),
    ('control character 1', '#\x01\n30 2 * * *\n', [(1, 'CONTROL_CHARACTER')]),
    ('lone surrogate', '# \udc80\n30 2 * * *\n', [(None, 'ENCODING')]),
    ('257 characters in a line', '#' + 'x' * 256 + '\n30 2 * * *\n', [(1, 'LINE_TOO_LONG')]),
    ('201 lines', '#\n' * 201, [(None, 'TOO_MANY_LINES')]),
    ('two bad lines', '61 2 * * *\n30 2 * *\n', [(1, 'CRON_RANGE'), (2, 'CRON_FIELD_COUNT')]),
]
# SC5: (label, text, warning code or None, entry count).
WARN: list[tuple[str, str, str | None, int]] = [
    ('empty text', '', 'NO_ENTRIES', 0), ('DOM and DOW both restricted', '0 3 1 * 1\n', 'DOM_DOW_OR', 1),
    ('duplicated entry', '30 2 * * *\n30 2 * * *\n', 'DUPLICATE_ENTRY', 2), ('29 February', '0 4 29 2 *\n', None, 1),
    ('names, lists, steps', '5,35 */2 1-15 jan-mar,jun mon-fri\n', None, 1), ('Sunday as 7', '0 3 * * 7\n', None, 1)]


def _safe(report: Report, label: str, func: Callable[[], None]) -> None:
    '''Run one case; an exception of the product code is a PRODUCT finding of that case.

    Args:
        report: the findings collector.
        label: the case label.
        func: the case body.

    Returns:
        None.
    '''
    try:
        func()
    except Exception as exc:  # noqa: BLE001 - product code that raises is a finding of that case
        report.product.append('%s: raised %s: %s' % (label, type(exc).__name__, str(exc)[:200]))


def _shape(report: Report, label: str, parsed: Any) -> bool:
    '''PRODUCT finding unless the parse result has the pinned keys and well-formed problems.

    Args:
        report: the findings collector.
        label: the case label.
        parsed: the parse result.

    Returns:
        True when the shape is right.
    '''
    if not isinstance(parsed, dict) or any(key not in parsed for key in PARSED_KEYS):
        report.product.append('%s: parse() returned %s, expected a mapping with %s' % (label, str(parsed)[:120], list(PARSED_KEYS)))
        return False
    bad = [item for item in parsed['problems'] if not isinstance(item, dict) or set(item) != PROBLEM_KEYS]
    if bad:
        report.product.append('%s: a problem is not {line, column, code, severity, message}: %s' % (label, str(bad[0])[:120]))
    return not bad


def _defaults(report: Report, mod: ModuleType) -> None:
    '''10.20.2: the default text, the directive defaults, the normalisation of RS2 and the revision.

    Args:
        report: the findings collector.
        mod: the product module schedule_file.

    Returns:
        None.
    '''
    default = getattr(mod, 'DEFAULT_TEXT', None)
    if default != sched12.EXPECTED_DEFAULT:
        report.product.append('DEFAULT_TEXT is %r, expected the exact bytes of 10.20.2 %r' % (str(default)[:80], sched12.EXPECTED_DEFAULT[:80]))
    parsed = mod.parse(sched12.EXPECTED_DEFAULT, NOW)
    if _shape(report, 'default text', parsed):
        line = sched12.EXPECTED_DEFAULT.split('\n').index('30 2 * * *') + 1
        got = (parsed['valid'], parsed['timezone'], parsed['jitter_minutes'], parsed['catchup_hours'], parsed['enabled'], parsed['entries'])
        if got != (True, 'Europe/Kyiv', 15, 24, True, [{'line': line, 'expression': '30 2 * * *'}]):
            report.product.append('10.20.2 default text: parse gives %s, expected valid, Europe/Kyiv, 15, 24, enabled and the entry on line %d' % (got, line))
    bare = mod.parse('30   2 *  * *\n', NOW)
    if _shape(report, 'bare entry', bare):
        plain = (bare['entries'], bare['timezone'], bare['jitter_minutes'], bare['catchup_hours'], bare['enabled'])
        if plain != ([{'line': 1, 'expression': '30 2 * * *'}], 'Europe/Kyiv', 0, 24, True):
            report.product.append('bare entry: parse gives %s, expected the blanks collapsed and TZ Europe/Kyiv, JITTER 0, CATCHUP 24, ENABLED yes' % (plain,))
    crlf = mod.parse('TZ=UTC\r\n# c  \r\n30 2 * * *', NOW)
    if _shape(report, 'CRLF', crlf):
        want = 'TZ=UTC\n# c  \n30 2 * * *\n'
        if crlf['text'] != want or crlf['revision'] != hashlib.sha256(want.encode('utf-8')).hexdigest() or mod.revision(want) != crlf['revision']:
            report.product.append('RS2 normalisation: text %r revision %s, expected %r and its sha256' % (crlf['text'], crlf['revision'], want))


def _cases(report: Report, mod: ModuleType) -> None:
    '''SC4 (every invalid text, all problems reported) and SC5 (valid texts with warnings) on the pure parser.

    Args:
        report: the findings collector.
        mod: the product module schedule_file.

    Returns:
        None.
    '''
    for label, text, expected in BAD:
        got = mod.parse(text, NOW)
        if not _shape(report, 'SC4 ' + label, got):
            continue
        found = [(line, code) for line, code, severity in sched12.codes(got) if severity == 'error']
        if got['valid'] is not False or [item for item in expected if item not in found]:
            report.product.append('SC4 %s: valid %r and errors %s, expected valid false and %s' % (label, got['valid'], found, expected))
    for label, text, warning, count in WARN:
        got = mod.parse(text, NOW)
        if not _shape(report, 'SC5 ' + label, got):
            continue
        seen = {code for _, code, severity in sched12.codes(got) if severity == 'warning'}
        errors = [item for item in sched12.codes(got) if item[2] == 'error']
        if got['valid'] is not True or errors or len(got['entries']) != count or (warning is not None and warning not in seen):
            report.product.append('SC5 %s: valid %r, errors %s, warnings %s, %d entries, expected valid, no error, %s and %d entries' % (label, got['valid'], errors, sorted(seen), len(got['entries']), warning, count))


def _plans(report: Report, mod: ModuleType) -> None:
    '''10.20.3 run_plan: five ordered runs of the default text, each start inside [slot, slot + 15 min] and each slot at 02:30 local.

    Args:
        report: the findings collector.
        mod: the product module schedule_file.

    Returns:
        None.
    '''
    plans = mod.next_runs(mod.parse(sched12.EXPECTED_DEFAULT, NOW), NOW, 5)
    starts = [sched12.parse_iso(item.get('start_utc')) for item in plans]
    slots = [sched12.parse_iso(item.get('slot_utc')) for item in plans]
    pairs = [(slot, start) for slot, start in zip(slots, starts) if slot is not None and start is not None]
    if len(plans) != 5 or len(pairs) != 5 or [start for _, start in pairs] != sorted(start for _, start in pairs):
        report.product.append('next_runs(default, 5) returned %s, expected five ordered run plans' % str(plans)[:160])
    elif any(not slot <= start <= slot + timedelta(minutes=15) or start <= NOW for slot, start in pairs) or any(not str(item.get('slot_local', '')).split('T')[-1].startswith('02:30:00') for item in plans):
        report.product.append('next_runs(default, 5): a start outside [slot, slot + 15 min], not after the call instant, or a slot not at 02:30 local: %s' % str(plans)[:200])


def _store(mod: ModuleType, base: Path, storage_ok: Callable[[], bool] | None = None) -> Any:
    '''Return a ScheduleStore on base/schedule.

    Args:
        mod: the product module schedule_file.
        base: the temporary data directory.
        storage_ok: the storage guard, or None.

    Returns:
        The store.
    '''
    return mod.ScheduleStore(base / 'schedule', storage_ok)


def _changes(base: Path) -> list[dict]:
    '''Return the parsed lines of changes.jsonl, empty when there is none.

    Args:
        base: the temporary data directory.

    Returns:
        The change records.
    '''
    path = base / 'schedule' / 'changes.jsonl'
    return [json.loads(line) for line in path.read_text(encoding='utf-8').splitlines() if line] if path.is_file() else []


def _leftovers(folder: Path) -> list[str]:
    '''Return the names of temporary files under the schedule directory.

    Args:
        folder: the schedule directory.

    Returns:
        The names that contain tmp.
    '''
    return [str(item) for item in folder.rglob('*') if 'tmp' in item.name]


def _st1_st3(report: Report, mod: ModuleType, base: Path) -> None:
    '''ST1 bootstrap, ST2 file mode and history file, ST3 a failing os.replace.

    Args:
        report: the findings collector.
        mod: the product module schedule_file.
        base: the temporary data directory.

    Returns:
        None.
    '''
    store = _store(mod, base)
    store.bootstrap()
    folder = base / 'schedule'
    live = folder / 'schedule.cron'
    if not live.is_file() or live.read_text(encoding='utf-8') != sched12.EXPECTED_DEFAULT:
        report.product.append('ST1 bootstrap: schedule.cron is missing or not the default text')
        return
    modes = (folder.stat().st_mode & 0o777, live.stat().st_mode & 0o777, folder.stat().st_uid)
    if modes != (0o700, 0o600, os.getuid()):
        report.product.append('ST1/ST2 directory mode, file mode and owner are %s, expected (0o700, 0o600, %d)' % ((oct(modes[0]), oct(modes[1]), modes[2]), os.getuid()))
    if [item.get('actor') for item in _changes(base)] != ['service']:
        report.product.append('ST1 changes.jsonl holds %s, expected one line with actor service' % _changes(base))
    new = sched12.EXPECTED_DEFAULT + '# second\n'
    done = store.write(new, actor='check')
    name = done.get('backup_file') if isinstance(done, dict) else None
    flags = isinstance(done, dict) and done.get('written') is True and done.get('changed') is True
    if not (flags and isinstance(name, str) and BACKUP_NAME.match(name)) or done.get('previous_revision') != mod.revision(sched12.EXPECTED_DEFAULT):
        report.product.append('ST2 write returned %s, expected written, changed, previous_revision of the default and backup_file schedule.<ts>.<8hex>.cron' % str(done)[:200])
    elif (folder / 'history' / str(name)).read_bytes() != sched12.EXPECTED_DEFAULT.encode('utf-8'):
        report.product.append('ST2 the history file %s does not hold the previous bytes' % name)
    if _leftovers(folder):
        report.product.append('ST2 a temporary file is left behind: %s' % _leftovers(folder))
    before = live.read_bytes()
    try:
        with mock.patch('os.replace', side_effect=OSError('injected')):
            store.write(new + '# third\n', actor='check')
        report.product.append('ST3 a failing os.replace did not make the write fail')
    except Exception as exc:  # noqa: BLE001 - the expected path
        got = (getattr(exc, 'code', None), getattr(exc, 'status', None))
        if got != ('SCHEDULE_WRITE_FAILED', 500):
            report.product.append('ST3 a failing os.replace raised %s %r, expected SCHEDULE_WRITE_FAILED status 500' % (type(exc).__name__, got))
    if live.read_bytes() != before or _leftovers(folder):
        report.product.append('ST3 the old file is not byte-identical or a temporary file is left after the failed write')


def _st4_st5(report: Report, mod: ModuleType, base: Path) -> None:
    '''ST4 two concurrent sets with one expected_revision, ST5 history pruned to the newest 50 versions.

    Args:
        report: the findings collector.
        mod: the product module schedule_file.
        base: the temporary data directory.

    Returns:
        None.
    '''
    store = _store(mod, base)
    store.bootstrap()
    revision = mod.revision(sched12.EXPECTED_DEFAULT)
    outcomes: list[str] = []
    gate = threading.Barrier(2)

    def attempt(tag: str) -> None:
        '''One writer of ST4.

        Args:
            tag: the writer label.

        Returns:
            None.
        '''
        gate.wait()
        try:
            store.write(sched12.EXPECTED_DEFAULT + '# ' + tag + '\n', expected_revision=revision, actor=tag)
            outcomes.append('ok')
        except Exception as exc:  # noqa: BLE001 - classified below
            outcomes.append('%s:%s' % (getattr(exc, 'code', type(exc).__name__), getattr(exc, 'status', None)))
    workers = [threading.Thread(target=attempt, args=(tag,)) for tag in ('a', 'b')]
    for worker in workers:
        worker.start()
    for worker in workers:
        worker.join(30)
    if sorted(outcomes) != ['SCHEDULE_CONFLICT:409', 'ok']:
        report.product.append('ST4 two concurrent sets with the same expected_revision ended %s, expected exactly one ok and one SCHEDULE_CONFLICT 409' % sorted(outcomes))
    for index in range(52):
        store.write(sched12.EXPECTED_DEFAULT + '# version %d\n' % index, actor='check')
    files = sorted((base / 'schedule' / 'history').glob('*.cron'))
    newest = mod.revision(sched12.EXPECTED_DEFAULT + '# version 50\n')[:8]
    oldest = mod.revision(sched12.EXPECTED_DEFAULT)[:8]
    hexes = [item.name.split('.')[-2] for item in files]
    if len(files) != 50 or newest not in hexes or oldest in hexes:
        report.product.append('ST5 after 54 different writes history/ holds %d files (newest previous version present %s, the first version present %s), expected 50, the newest kept and the oldest removed' % (len(files), newest in hexes, oldest in hexes))


def _st6_st9(report: Report, mod: ModuleType, base: Path) -> None:
    '''ST6 corrupt file at start, ST7 corrupt file under a held schedule, ST8 deleted file, ST9 hand edit.

    Args:
        report: the findings collector.
        mod: the product module schedule_file.
        base: the temporary data directory.

    Returns:
        None.
    '''
    store = _store(mod, base)
    store.bootstrap()
    store.write(sched12.EXPECTED_DEFAULT + '# valid history\n', actor='check')
    live = base / 'schedule' / 'schedule.cron'
    live.write_text('61 2 * * *\n', encoding='utf-8')
    held = _store(mod, base).read()
    if not str(held.get('source', '')).startswith('history:') or held.get('valid') is not False or live.read_text(encoding='utf-8') != '61 2 * * *\n':
        report.product.append('ST6 corrupt file with a valid history version: read() gives source %r valid %r, expected history:<file>, valid false and the corrupt file untouched' % (held.get('source'), held.get('valid')))
    with tempfile.TemporaryDirectory() as other:
        folder = Path(other) / 'schedule'
        folder.mkdir()
        (folder / 'schedule.cron').write_text('61 2 * * *\n', encoding='utf-8')
        bare = mod.ScheduleStore(folder).read()
        if bare.get('source') != 'default' or (folder / 'schedule.cron').read_text(encoding='utf-8') != '61 2 * * *\n':
            report.product.append('ST6 corrupt file and no history: read() gives source %r, expected default and the file untouched' % bare.get('source'))
    with tempfile.TemporaryDirectory() as other:
        keeper = _store(mod, Path(other))
        keeper.bootstrap()
        keeper.read()
        (Path(other) / 'schedule' / 'schedule.cron').write_text('61 2 * * *\n', encoding='utf-8')
        kept = keeper.read()
        if kept.get('source') != 'memory' or kept.get('valid') is not False:
            report.product.append('ST7 corrupt file while a valid schedule is held: read() gives source %r valid %r, expected memory and valid false' % (kept.get('source'), kept.get('valid')))
    with tempfile.TemporaryDirectory() as other:
        _st8_st9(report, mod, Path(other))


def _st8_st9(report: Report, mod: ModuleType, base: Path) -> None:
    '''ST8 a deleted file is recreated once (and never when the storage guard fails), ST9 a hand edit is picked up.

    Args:
        report: the findings collector.
        mod: the product module schedule_file.
        base: the temporary data directory.

    Returns:
        None.
    '''
    keeper = _store(mod, base)
    keeper.bootstrap()
    live = base / 'schedule' / 'schedule.cron'
    live.unlink()
    keeper.read(create_missing=True)
    keeper.read(create_missing=True)
    service = [item for item in _changes(base) if item.get('actor') == 'service']
    if not live.is_file() or live.read_text(encoding='utf-8') != sched12.EXPECTED_DEFAULT or len(service) != 2:
        report.product.append('ST8 deleted file: the default is %s and changes.jsonl holds %d service lines, expected the default rewritten once (2 service lines with the bootstrap)' % ('back' if live.is_file() else 'not rewritten', len(service)))
    live.unlink()
    result = mod.ScheduleStore(base / 'schedule', lambda: False).read(create_missing=True)
    if live.exists() or result.get('source') != 'default':
        report.product.append('ST8 with the storage guard failing the file is recreated or the source is %r, expected no write and source default' % result.get('source'))
    edited = sched12.EXPECTED_DEFAULT + '# by hand\n'
    live.write_text(edited, encoding='utf-8')
    seen = keeper.read()
    if seen.get('revision') != mod.revision(edited) or seen.get('source') != 'file':
        report.product.append('ST9 hand edit: read() gives revision %s source %r, expected the revision of the edited text and source file' % (str(seen.get('revision'))[:12], seen.get('source')))


def run() -> None:
    '''Raise CheckFailure when the parser or the store differs from 10.20.2, 10.20.3 or 10.20.6.

    Returns:
        None.
    '''
    report = Report()
    mod = sched12.load(report, 'file')
    if mod is not None and not sched12.missing(report, mod, ('DEFAULT_TEXT', 'parse', 'revision', 'next_runs', 'ScheduleError', 'ScheduleStore')):
        for label, body in (('grammar', _defaults), ('SC4 and SC5', _cases), ('next_runs', _plans)):
            _safe(report, label, functools.partial(body, report, mod))
        for label, case in (('ST1-ST3', _st1_st3), ('ST4-ST5', _st4_st5), ('ST6-ST9', _st6_st9)):
            with tempfile.TemporaryDirectory() as tmp:
                _safe(report, label, functools.partial(case, report, mod, Path(tmp)))
    report.finish('schedule_file')
