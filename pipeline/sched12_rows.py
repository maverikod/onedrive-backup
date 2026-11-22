'''Revision 12 live executors of the command rows M15, M16 and M17 (matrix TODO 10.20.3 and 10.20.4, block SCHEDULE-REV12).

Every case of a row is executed through pipeline.live with the parameters the matrix names and judged against its result contract
(`expect`: rpc:<violation>, cmd:<status>:<token>, sched:<status>:<token>:<problem codes or conflict> or ok:<validator>). SAFETY (10.20.7
safety rule): no case of these rows writes a schedule to the production service. Valid texts are sent with dry_run true; the cases
that are not dry runs end in an error before any write. After every row the schedule revision is read again and must equal the one
read before the row. Findings are PRODUCT, STATE or ENVIRONMENT as in pipeline.report.
'''

from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime, timedelta
from typing import Any, Callable
from zoneinfo import ZoneInfo

from pipeline import live, matrix, rev11, sched12, sched12_file
from pipeline.report import Report

GET_KEYS = ['text', 'revision', 'exists', 'source', 'valid', 'problems', 'timezone', 'jitter_minutes', 'catchup_hours', 'enabled', 'entries',
            'next_runs', 'server_time_utc', 'path']
SET_KEYS = ['written', 'changed', 'dry_run', 'revision', 'previous_revision', 'backup_file', 'text', 'valid', 'problems', 'timezone',
            'jitter_minutes', 'catchup_hours', 'enabled', 'entries', 'next_runs', 'server_time_utc']
STATUS_KEYS = ['scheduler', 'schedule', 'current_run', 'last_run', 'next_run', 'missed', 'history', 'server_time_utc']
SCHEDULER_KEYS = ['state', 'thread_alive', 'started_at', 'last_tick_at', 'leader', 'message']
SCHEDULE_KEYS = ['revision', 'valid', 'source', 'timezone', 'enabled', 'entries', 'baseline_utc']
RUN_KEYS = ['run_id', 'started_at', 'finished_at', 'exit_code', 'status', 'trigger', 'slot_utc']
CURRENT_KEYS = ['run_id', 'started_at', 'trigger', 'slot_utc', 'pid', 'elapsed_seconds']
PLAN_KEYS = ['slot_local', 'slot_utc', 'start_utc', 'start_local', 'entry_lines']
ENTRY_KEYS = ['line', 'expression', 'next_start_utc']
STATUSES = ('ok', 'errors', 'refused', 'interrupted', 'launch_failed', 'skipped_busy')
STATES = ('starting', 'waiting', 'running', 'paused', 'idle', 'file_invalid', 'storage_unavailable', 'scaffold', 'not_leader', 'stopped')
PATH = '/data/schedule/schedule.cron'
FULL = ('#' + 'x' * 126 + '\n') * 128
IDS = ('range', 'fields', 'extra', 'step0', 'freq', 'never', 'macro', 'tz', 'jit61', 'jitnounit', 'catch200', 'enabled', 'twotz', 'foo',
       'entries21', 'nul', 'ctl', 'surrogate', 'long257', 'lines201', 'twobad')
BAD_TEXTS = {name: item[1] for name, item in zip(IDS, sched12_file.BAD)}
WARN_TEXTS = {'$WARN:empty': ('', 'NO_ENTRIES'), '$WARN:domdow': ('0 3 1 * 1\n', 'DOM_DOW_OR'), '$WARN:dup': ('30 2 * * *\n30 2 * * *\n', 'DUPLICATE_ENTRY')}
VOLATILE = ('server_time_utc', 'last_tick_at', 'elapsed_seconds')


def call(command: str, params: dict) -> dict:
    '''Return the data of a successful command call, or an empty map.

    Args:
        command: the service command.
        params: its parameters.

    Returns:
        The data map, empty after a failure.
    '''
    kind, _, _, data = live.request(command, params)
    return data if kind == 'success' and isinstance(data, dict) else {}


def digest(text: str) -> str:
    '''Return the lowercase hex sha256 of the UTF-8 bytes of a text.

    Args:
        text: the stored text.

    Returns:
        The revision.
    '''
    return hashlib.sha256(text.encode('utf-8')).hexdigest()


def far_future(zone: str) -> str:
    '''Return a valid schedule text that cannot fire inside the next 24 hours (the safety rule of 10.20.7).

    Args:
        zone: the time zone of the original schedule.

    Returns:
        The text: the zone, no jitter, no catch-up and one entry 120 days ahead at 04:00 local.
    '''
    when = datetime.now(ZoneInfo(zone)) + timedelta(days=120)
    return 'TZ=%s\nJITTER=0m\nCATCHUP=0h\n0 4 %d %d *\n' % (zone, when.day, when.month)


class Context12(rev11.Context):
    '''Runtime placeholders of the schedule cases: the original text and revision and the generated texts.

    Attributes:
        snapshots: always empty; the schedule cases read no snapshot.
        days: always empty.
        site: always None.
        text: the stored text read before the row, or None.
        revision: its revision, or None.
        zone: its time zone.
        history: the status history read before the row.
    '''

    def __init__(self) -> None:
        '''Read the stored schedule and the status history once; no snapshot is read.'''
        self.snapshots: list[dict] = []
        self.days: list[str] = []
        self.site: str | None = None
        data = call('backup_schedule_get', {})
        text, revision, zone = data.get('text'), data.get('revision'), data.get('timezone')
        self.text: str | None = text if isinstance(text, str) else None
        self.revision: str | None = revision if isinstance(revision, str) else None
        self.zone: str = zone if isinstance(zone, str) else sched12.ZONE
        self.history: list = call('backup_schedule_status', {}).get('history') or []

    def resolve(self, value: Any) -> Any:
        '''Replace the placeholders $ORIG, $ORIGX, $FULL, $BIG, $FUTURE, $BAD:<id> and $WARN:<id>, then the placeholders of rev11.

        Args:
            value: a parameter value, list or map.

        Returns:
            The value with the placeholders replaced.
        '''
        if isinstance(value, str):
            if value.startswith('$BAD:'):
                return BAD_TEXTS[value[5:]]
            if value in WARN_TEXTS:
                return WARN_TEXTS[value][0]
            table = {'$ORIG': self.text or '', '$ORIGX': (self.text or '') + '# dry run by the pipeline\n', '$FULL': FULL, '$BIG': FULL + '#',
                     '$FUTURE': far_future(self.zone)}
            if value in table:
                return table[value]
        return super().resolve(value)


def _plans(case: rev11.Case, count: int | None) -> None:
    '''PRODUCT finding unless next_runs holds run plans in start order, each start inside [slot, slot + jitter] after the call instant.

    Args:
        case: the executed case.
        count: the exact number of plans, or None for any number up to 20.

    Returns:
        None.
    '''
    plans = case.data.get('next_runs')
    if not isinstance(plans, list) or (count is not None and len(plans) != count) or len(plans) > 20:
        case.bad('next_runs has %s entries, expected %s' % (len(plans) if isinstance(plans, list) else plans, count))
        return
    jitter = case.data.get('jitter_minutes')
    starts = [sched12.parse_iso(item.get('start_utc')) for item in plans]
    now = sched12.parse_iso(case.data.get('server_time_utc'))
    for item, start in zip(plans, starts):
        slot = sched12.parse_iso(item.get('slot_utc'))
        if sorted(item) != sorted(PLAN_KEYS) or slot is None or start is None or not isinstance(jitter, int) or not slot <= start <= slot + timedelta(minutes=jitter):
            case.bad('a run plan is %s, expected the keys %s and a start inside [slot, slot + %s min]' % (str(item)[:120], PLAN_KEYS, jitter))
            return
    ordered = [item for item in starts if item is not None]
    if ordered != sorted(ordered) or (now is not None and ordered and ordered[0] <= now):
        case.bad('next_runs are not in start order after server_time_utc %s' % case.data.get('server_time_utc'))


def _common(case: rev11.Case, keys: list[str]) -> bool:
    '''The shape shared by M15 and M16: keys, 64-hex revision equal to the sha256 of text, entries and run plans.

    Args:
        case: the executed case.
        keys: the exact result keys.

    Returns:
        True when the shape is right.
    '''
    data = case.data
    if not case.fields(keys):
        return False
    before = len(case.report.product)
    if data['revision'] != digest(str(data['text'])) or not re.fullmatch('[0-9a-f]{64}', str(data['revision'])):
        case.bad('revision %s is not the lowercase sha256 of text' % data['revision'])
    if any(not isinstance(item, dict) or sorted(item) != sorted(ENTRY_KEYS) for item in data['entries']):
        case.bad('an entry is not {line, expression, next_start_utc}: %s' % str(data['entries'])[:120])
    if sched12.parse_iso(data['server_time_utc']) is None or any(sorted(item) != sorted(['line', 'column', 'code', 'severity', 'message']) for item in data['problems']):
        case.bad('server_time_utc %r or a problem has other keys than line, column, code, severity, message' % data['server_time_utc'])
    return len(case.report.product) == before


def _sc1(case: rev11.Case) -> None:
    '''SC1: the stored schedule, its shape and, when it is still the default, the exact default values.

    Args:
        case: the executed case.

    Returns:
        None.
    '''
    data = case.data
    if not _common(case, GET_KEYS):
        return
    if data['valid'] is not True or data['source'] != 'file' or data['path'] != PATH or data['exists'] is not True:
        case.bad('valid %r source %r exists %r path %r, expected true, file, true and %s' % (data['valid'], data['source'], data['exists'], data['path'], PATH))
    _plans(case, 5 if data['enabled'] and data['entries'] else None)
    if data['text'] == sched12.EXPECTED_DEFAULT:
        line = sched12.EXPECTED_DEFAULT.split('\n').index('30 2 * * *') + 1
        got = (data['timezone'], data['jitter_minutes'], data['catchup_hours'], data['enabled'], [(item['line'], item['expression']) for item in data['entries']])
        if got != ('Europe/Kyiv', 15, 24, True, [(line, '30 2 * * *')]) or any('T02:30:00' not in str(item['slot_local']) for item in data['next_runs']):
            case.bad('the stored text is the default, expected Europe/Kyiv, 15, 24, enabled, the entry on line %d and every slot at 02:30 local, got %s' % (line, got))


def _plans_n(count: int) -> Callable[[rev11.Case], None]:
    '''Return the validator of next_count cases: exactly count run plans (fewer only when the schedule has no entry).

    Args:
        count: the next_count sent.

    Returns:
        The validator.
    '''
    def check(case: rev11.Case) -> None:
        '''Judge one next_count case.

        Args:
            case: the executed case.

        Returns:
            None.
        '''
        if _common(case, GET_KEYS):
            _plans(case, count if case.data['enabled'] and case.data['entries'] else None)
            if count == 0 and case.data['next_runs'] != []:
                case.bad('next_count 0 returned %s, expected []' % case.data['next_runs'])
    return check


def _unchanged(case: rev11.Case) -> None:
    '''SC3 and SC12: a following read gives the same revision and text as before the case.

    Args:
        case: the executed case.

    Returns:
        None.
    '''
    after = call('backup_schedule_get', {})
    ctx = case.ctx
    if isinstance(ctx, Context12) and (after.get('revision') != ctx.revision or after.get('text') != ctx.text):
        case.bad('the schedule changed during the case: revision %s then %s' % (str(ctx.revision)[:12], str(after.get('revision'))[:12]))
    if isinstance(ctx, Context12) and call('backup_schedule_status', {}).get('history') != ctx.history:
        case.bad('the status history changed during the case')


def _sc3(case: rev11.Case) -> None:
    '''SC3: a dry run of a different valid text writes nothing and answers the revision the text would have.

    Args:
        case: the executed case.

    Returns:
        None.
    '''
    data = case.data
    if _common(case, SET_KEYS):
        text = str(case.params['text'])
        if (data['written'], data['dry_run'], data['valid']) != (False, True, True) or data['revision'] != digest(text):
            case.bad('written %r dry_run %r valid %r revision %s, expected false, true, true and the sha256 of the sent text' % (data['written'], data['dry_run'], data['valid'], str(data['revision'])[:12]))
        _plans(case, 3)
    _unchanged(case)


def _warn(case: rev11.Case) -> None:
    '''SC5: a valid text with a warning is accepted by a dry run, the warning is reported and the run plans follow the entries.

    Args:
        case: the executed case.

    Returns:
        None.
    '''
    text = str(case.params['text'])
    code = next(item[1] for item in WARN_TEXTS.values() if item[0] == text)
    data = case.data
    if not _common(case, SET_KEYS):
        return
    if data['valid'] is not True or data['written'] is not False or code not in [item['code'] for item in data['problems'] if item['severity'] == 'warning']:
        case.bad('valid %r written %r warnings %s, expected valid, not written and the warning %s' % (data['valid'], data['written'], [item['code'] for item in data['problems']], code))
    slots = [item['slot_utc'] for item in data['next_runs']]
    if code == 'NO_ENTRIES' and (data['entries'] != [] or data['next_runs'] != []):
        case.bad('no entry: entries %s and next_runs %s, expected both empty' % (data['entries'], data['next_runs']))
    if code == 'DUPLICATE_ENTRY' and (len(set(slots)) != len(slots) or not slots):
        case.bad('a duplicated entry gives the slots %s, expected one run plan per slot' % slots)


def _full(case: rev11.Case) -> None:
    '''SC8: 16384 bytes of comments are accepted (a dry run): valid, the warning NO_ENTRIES, nothing written.

    Args:
        case: the executed case.

    Returns:
        None.
    '''
    data = case.data
    if _common(case, SET_KEYS) and (data['valid'] is not True or data['written'] is not False or 'NO_ENTRIES' not in [item['code'] for item in data['problems']]):
        case.bad('16384 bytes of comments: valid %r written %r, expected valid, not written and the warning NO_ENTRIES' % (data['valid'], data['written']))
    _unchanged(case)


def _dry_conflict(case: rev11.Case) -> None:
    '''SC7: with dry_run true a wrong expected_revision is ignored and the call succeeds without a write.

    Args:
        case: the executed case.

    Returns:
        None.
    '''
    if _common(case, SET_KEYS) and case.data['written'] is not False:
        case.bad('dry_run with a wrong expected_revision wrote the schedule')
    _unchanged(case)


def _run_shape(case: rev11.Case, item: Any, label: str) -> None:
    '''PRODUCT finding unless item is a run record of the status contract.

    Args:
        case: the executed case.
        item: the record.
        label: where it came from.

    Returns:
        None.
    '''
    if not isinstance(item, dict) or sorted(item) != sorted(RUN_KEYS) or item['status'] not in STATUSES:
        case.bad('%s is %s, expected the keys %s and a status in %s' % (label, str(item)[:120], RUN_KEYS, STATUSES))


def _sc10(case: rev11.Case) -> None:
    '''SC10: the scheduler thread is alive and leader, the status agrees with the schedule, the records have the contract shape.

    Args:
        case: the executed case.

    Returns:
        None.
    '''
    data = case.data
    if not case.fields(STATUS_KEYS):
        return
    sched, plan, current = data['scheduler'], data['schedule'], data['current_run']
    if sorted(sched) != sorted(SCHEDULER_KEYS) or sorted(plan) != sorted(SCHEDULE_KEYS):
        case.bad('scheduler keys %s or schedule keys %s differ from the contract' % (sorted(sched), sorted(plan)))
        return
    if sched['thread_alive'] is not True or sched['leader'] is not True or sched['state'] not in ('waiting', 'running'):
        case.bad('scheduler %s, expected thread_alive true, leader true and state waiting or running' % {key: sched[key] for key in ('state', 'thread_alive', 'leader')})
    stored = call('backup_schedule_get', {})
    if plan['revision'] != stored.get('revision') or plan['valid'] is not stored.get('valid'):
        case.bad('schedule.revision %s differs from backup_schedule_get %s' % (str(plan['revision'])[:12], str(stored.get('revision'))[:12]))
    first = (stored.get('next_runs') or [{}])[0].get('start_utc')
    after = (data['next_run'] or {}).get('start_utc')
    if data['next_run'] is not None and first is not None and after != first:
        case.bad('next_run.start_utc %s differs from backup_schedule_get next_runs[0] %s (RS5)' % (after, first))
    if len(data['history']) > 10:
        case.bad('history holds %d records, expected at most 10 by default' % len(data['history']))
    _run_shape(case, data['last_run'], 'last_run') if data['last_run'] is not None else None
    for item in data['history']:
        _run_shape(case, item, 'a history record')
    if current is not None and (sorted(current) != sorted(CURRENT_KEYS) or not isinstance(current['pid'], int)):
        case.bad('current_run is %s, expected the keys %s and a pid' % (str(current)[:120], CURRENT_KEYS))


def _history(limit: int) -> Callable[[rev11.Case], None]:
    '''Return the validator of history_limit cases: the keys and a history of at most limit records, newest first.

    Args:
        limit: the history_limit sent.

    Returns:
        The validator.
    '''
    def check(case: rev11.Case) -> None:
        '''Judge one history_limit case.

        Args:
            case: the executed case.

        Returns:
            None.
        '''
        history = case.data.get('history')
        if not case.fields(STATUS_KEYS) or not isinstance(history, list):
            return
        starts = [str(item.get('started_at')) for item in history if isinstance(item, dict)]
        if len(history) > limit or (limit == 0 and history != []) or starts != sorted(starts, reverse=True):
            case.bad('history_limit %d gave %d records or an order that is not newest first: %s' % (limit, len(history), starts[:3]))
    return check


rev11.VALIDATORS.update({
    's12_sc1': _sc1, 's12_n0': _plans_n(0), 's12_n20': _plans_n(20), 's12_unchanged': _unchanged, 's12_sc3': _sc3, 's12_warn': _warn,
    's12_full': _full, 's12_dry_conflict': _dry_conflict, 's12_sc10': _sc10, 's12_h0': _history(0), 's12_h50': _history(50)})


def _judge(report: Report, desc: str, command: str, params: dict, expect: str, ctx: Context12) -> None:
    '''Send one case and judge the reply; the sched kind also reads the problems of the error.

    Args:
        report: the findings collector.
        desc: the case description.
        command: the service command.
        params: the parameter map to send.
        expect: the expectation of the result contract.
        ctx: the runtime placeholders.

    Returns:
        None.
    '''
    mode, _, rest = expect.partition(':')
    if mode != 'sched':
        rev11._judge(report, desc, command, params, expect, ctx)
        return
    status, token, codes = rest.split(':', 2)
    raw = live.call(command, params)
    kind, code, message, _ = live.classify(raw)
    result = raw.get('result')
    error: dict[str, Any] = dict(result['error']) if isinstance(result, dict) and isinstance(result.get('error'), dict) else {}
    info: dict[str, Any] = dict(error.get('data') or error.get('details') or {})
    if not (kind == 'command_error' and code == int(status) and token in message):
        report.product.append('%s: expected command error %s %s, got %s' % (desc, status, token, str(raw)[:160]))
    elif codes == 'conflict':
        if info.get('current_revision') != ctx.revision or info.get('current_text') != ctx.text:
            report.product.append('%s: error.data is %s, expected current_revision and current_text of backup_schedule_get' % (desc, str(info)[:120]))
    else:
        problems = info.get('problems')
        found = [(item.get('code'), item.get('line')) for item in problems or [] if isinstance(item, dict) and item.get('severity') == 'error']
        wanted = [(part.partition('@')[0], None if part.partition('@')[2] in ('', '-') else int(part.partition('@')[2])) for part in codes.split(',')]
        if [item for item in wanted if item not in found]:
            report.product.append('%s: error.data.problems holds the errors %s, expected %s (every error is reported)' % (desc, found, wanted))


def run_row(row_id: str, name: str) -> None:
    '''Execute every case of the command row against the deployed service and raise CheckFailure on a finding.

    Args:
        row_id: the matrix row, M15, M16 or M17.
        name: the named check.

    Returns:
        None.
    '''
    data = matrix.load()
    row = next(item for item in data['rows'] if item['id'] == row_id)
    contracts = data['result_contracts'][row_id]['cases']
    report = Report()
    try:
        state = live.service_state()
        ctx = Context12()
        if state != 'S1':
            report.state.append('%s: the cases need an S1 service, production answers %s' % (row_id, state))
        for case in row['cases'] if state == 'S1' else []:
            expect = contracts.get(case['id'], {}).get('expect')
            params = ctx.resolve(case['params'])
            desc = '%s %s %s(%s)' % (row_id, case['id'], row['command'], json.dumps(params, ensure_ascii=False)[:160])
            if expect is None:
                report.product.append('%s: no result contract with an expectation in pipeline/matrix.yaml' % desc)
            else:
                _judge(report, desc, row['command'], params, expect, ctx)
        if state == 'S1' and ctx.revision is not None and call('backup_schedule_get', {}).get('revision') != ctx.revision:
            report.product.append('%s: the schedule revision changed during the row (SC12); a case wrote the production schedule' % row_id)
        report.info.append('%d cases of row %s executed' % (len(row['cases']), row_id))
    except live.LiveUnreachable as exc:
        report.env.append('%s: not executed, production service unreachable: %s' % (row_id, exc))
    report.finish(name)
