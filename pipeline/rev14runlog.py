'''Revision 14 executor of row M24 backup_run_log (matrix TODO 10.23.R.2 option O-RD2 B, 10.23.R.6 TR5, RR2-RR4, RR8; check cmd_backup_run_log; block RUN-REASON).

The run ids come from the real history of backup_schedule_status (history_limit 50): $RUN_ID is the newest run whose log is available, $RUN_ID_BEFORE_FIX the newest
finished run without an available log. TESTER ASSUMPTION: when no run has a log yet (the first run after the 0.3.28 deployment writes the first one) the cases that
need a log are STATE RED, never skipped; while the command does not exist (-32601) every case is PRODUCT RED. Nothing is written to the data volume; every case is a read.
'''

from __future__ import annotations

import json
import re
from typing import Any, Callable

from pipeline import cmdcases, live, matrix, rev11, sched12_live, sched12_rows
from pipeline.report import Report

RESULT_KEYS = ['run_id', 'name', 'size_bytes', 'offset', 'length', 'eof', 'encoding', 'text', 'rotated']
UPPER = 'ABCDEF12-0000-4000-8000-000000000000'
SHORT = '00000000-0000-4000-8000-00000000000'
UNKNOWN = '00000000-0000-4000-8000-000000000000'
NEEDS_LOG = ('baseline_tail', 'tr5_slices_reassemble', 'tr5_tail_last_bytes', 'rr3_tail_with_offset', 'rr4_offset_beyond', 'rr8_writes_nothing')
ERROR_DATA = {'rr3_tail_with_offset': ('fields', ['offset', 'tail']), 'tr5_unknown_run_id': ('hint', 'backup_schedule_status'), 'tr5_run_without_log': ('hint', ''),
              'rr4_offset_beyond': ('size_bytes', None)}


def _whole(value: Any) -> bool:
    '''Tell whether a value is an integer that is not a boolean.

    Args:
        value: any value.

    Returns:
        True for an int.
    '''
    return isinstance(value, int) and not isinstance(value, bool)


class RunContext(rev11.Context):
    '''Run ids of the M24 cases, read from the real history; nothing is written.

    Attributes:
        snapshots: always empty.
        days: always empty.
        site: always None.
        status0: the backup_schedule_status read before the row.
        run_id: the newest run whose log is available, or None.
        any_id: the newest run id of any kind, or a fixed unknown id.
        bare_id: the newest finished run without an available log, or None.
        size: the size_bytes of the log of run_id, or 0.
    '''

    def __init__(self) -> None:
        '''Read the status history once.'''
        self.snapshots: list[dict] = []
        self.days: list[str] = []
        self.site: str | None = None
        self.status0: dict = sched12_rows.call('backup_schedule_status', {'history_limit': 50})
        items = [item for item in self.status0.get('history') or [] if isinstance(item, dict) and isinstance(item.get('run_id'), str)]
        logged = [item for item in items if isinstance(item.get('log'), dict) and item['log'].get('available') is True]
        bare = [item for item in items if item.get('finished_at') and item not in logged]
        self.run_id: str | None = logged[0]['run_id'] if logged else None
        self.size: int = int(logged[0]['log'].get('size_bytes') or 0) if logged else 0
        self.any_id: str = items[0]['run_id'] if items else UNKNOWN
        self.bare_id: str | None = bare[0]['run_id'] if bare else None

    def resolve(self, value: Any) -> Any:
        '''Replace $RUN_ID, $RUN_ID_UPPER, $RUN_ID_35, $RUN_ID_BEFORE_FIX and $SIZE+1 inside a case parameter map.

        Args:
            value: a parameter value, list or map.

        Returns:
            The value with the placeholders replaced.
        '''
        if isinstance(value, list):
            return [self.resolve(item) for item in value]
        if isinstance(value, dict):
            return {name: self.resolve(item) for name, item in value.items()}
        table = {'$RUN_ID': self.run_id or self.any_id, '$RUN_ID_UPPER': UPPER, '$RUN_ID_35': SHORT, '$RUN_ID_BEFORE_FIX': self.bare_id or self.any_id, '$SIZE+1': self.size + 1}
        return table.get(value, value) if isinstance(value, str) else value


def _result(case: rev11.Case) -> bool:
    '''Judge the shape of one backup_run_log result (RR2): keys, types, name, eof, bound.

    Args:
        case: the executed case.

    Returns:
        True when the shape is right.
    '''
    data, rid = case.data, case.params.get('run_id')
    before = len(case.report.product)
    if sorted(data) != sorted(RESULT_KEYS):
        case.bad('result keys %s, expected %s' % (sorted(data), sorted(RESULT_KEYS)))
        return False
    if data['run_id'] != rid or not re.fullmatch(re.escape(str(rid)) + r'[.]log([.][0-9]+)?', str(data['name'])) or (data['rotated'] is not True and data['name'] != '%s.log' % rid):
        case.bad('run_id %r name %r rotated %r, expected %r and the name <run_id>.log (RR2)' % (data['run_id'], data['name'], data['rotated'], rid))
    if not all(_whole(data[key]) and data[key] >= 0 for key in ('size_bytes', 'offset', 'length')) or not isinstance(data['eof'], bool) or not isinstance(data['rotated'], bool):
        case.bad('size_bytes, offset, length must be integers >= 0, eof and rotated booleans: %s' % {key: data[key] for key in RESULT_KEYS if key != 'text'})
    elif data['eof'] != (data['offset'] + data['length'] == data['size_bytes']) or data['length'] > case.params.get('limit', 16384):
        case.bad('eof %r with offset %s length %s size_bytes %s limit %s (RR2)' % (data['eof'], data['offset'], data['length'], data['size_bytes'], case.params.get('limit', 16384)))
    if data['encoding'] != 'utf-8' or not isinstance(data['text'], str):
        case.bad('encoding %r text %s, expected utf-8 and a string' % (data['encoding'], type(data['text']).__name__))
    return len(case.report.product) == before


def _tail(case: rev11.Case) -> None:
    '''TR5 baseline_tail and tr5_tail_last_bytes: the last min(limit, size) bytes, the slice ends at the end of the file.

    Args:
        case: the executed case.

    Returns:
        None.
    '''
    data, limit = case.data, case.params.get('limit', 16384)
    if _result(case) and (data['length'] != min(limit, data['size_bytes']) or data['offset'] != data['size_bytes'] - data['length'] or data['eof'] is not True):
        case.bad('tail true limit %s returned offset %s length %s of size_bytes %s eof %r, expected the last min(limit, size) bytes' % (limit, data['offset'], data['length'], data['size_bytes'], data['eof']))


def _reassemble(case: rev11.Case) -> None:
    '''TR5 tr5_slices_reassemble: the slices from offset 0 are contiguous and add up to size_bytes, eof only on the last.

    Args:
        case: the executed case.

    Returns:
        None.
    '''
    if not _result(case):
        return
    data, total, pages = case.data, 0, 0
    while True:
        total, pages = total + data['length'], pages + 1
        if data['eof'] or pages > 200:
            break
        kind, code, message, reply = live.request('backup_run_log', {'run_id': case.params['run_id'], 'offset': total, 'limit': 65536})
        if kind != 'success' or not isinstance(reply, dict) or reply.get('offset') != total or reply.get('eof') is None:
            case.bad('slice %d at offset %d: %s' % (pages + 1, total, cmdcases._brief(kind, code, message, reply)))
            return
        data = reply
    if total != data['size_bytes'] or not data['eof']:
        case.bad('%d slice(s) add up to %d bytes, expected size_bytes %s with eof on the last (RR2)' % (pages, total, data['size_bytes']))


def _nowrite(case: rev11.Case) -> None:
    '''RR8: the call changed no run record, no log size and not the schedule revision.

    Args:
        case: the executed case.

    Returns:
        None.
    '''
    _result(case)
    after = sched12_rows.call('backup_schedule_status', {'history_limit': 50})
    before = case.ctx.status0 if isinstance(case.ctx, RunContext) else {}
    old, new = (before.get('schedule') or {}).get('revision'), (after.get('schedule') or {}).get('revision')
    if old != new or any(sched12_live.strip(after.get(key)) != sched12_live.strip(before.get(key)) for key in ('last_run', 'current_run', 'history')):
        case.bad('the status after the call differs from the status before it: revision %s then %s; a run may have started meanwhile' % (old, new))


M24_VALIDATORS: dict[str, Callable[[rev11.Case], None]] = {'runlog': _tail, 'runlog_all': _reassemble, 'runlog_tail': _tail, 'nowrite': _nowrite}


def _judge(report: Report, desc: str, cid: str, params: dict, expect: str, ctx: RunContext) -> None:
    '''Send one M24 case and judge it; the cases that need a log are STATE RED while no run has one and the command exists.

    Args:
        report: the findings collector.
        desc: the case description.
        cid: the case id.
        params: the parameter map to send.
        expect: the expectation of the result contract.
        ctx: the run ids.

    Returns:
        None.
    '''
    mode, _, rest = expect.partition(':')
    missing = ctx.run_id is None and cid in NEEDS_LOG or ctx.bare_id is None and cid == 'tr5_run_without_log'
    reply = live.request('backup_run_log', params)
    kind, code, message, data = reply
    if code == -32601:
        report.product.append('%s: %s' % (desc, cmdcases._brief(*reply)))
    elif missing and kind != 'success':
        report.state.append('%s: no recorded run has %s to read (the first run after the deployment writes the first log); got %s' % (desc, 'no log' if cid == 'tr5_run_without_log' else 'a log', cmdcases._brief(*reply)))
    elif mode == 'cmd':
        want, _, token = rest.partition(':')
        key, wanted = ERROR_DATA.get(cid, ('', None))
        value = data.get(key) if isinstance(data, dict) else None
        if not (kind == 'command_error' and code == int(want) and token in message):
            report.product.append('%s: expected command error %s %s, got %s' % (desc, want, token, cmdcases._brief(*reply)))
        elif key and (value is None or wanted is not None and (sorted(value) if isinstance(value, list) else value) != wanted and (not isinstance(wanted, str) or wanted not in str(value))):
            report.product.append('%s: error.data.%s is %s, expected %s' % (desc, key, str(value)[:100], wanted if wanted is not None else 'an integer'))
    elif mode == 'rpc':
        cmdcases._judge_rpc(report, desc, reply, rest, rest in ('type', 'value'), 'text')
    elif kind != 'success' or not isinstance(data, dict):
        report.product.append('%s: expected success, got %s' % (desc, cmdcases._brief(*reply)))
    else:
        M24_VALIDATORS[rest](rev11.Case(report, desc, data, ctx, params))


def run_log_row(name: str) -> None:
    '''Execute every case of row M24 against the deployed service and raise CheckFailure on a finding.

    Args:
        name: the named check.

    Returns:
        None.
    '''
    data = matrix.load()
    row = next(item for item in data['rows'] if item['id'] == 'M24')
    contracts = data['result_contracts']['M24']['cases']
    report = Report()
    try:
        state = live.service_state()
        if state != 'S1':
            report.state.append('M24: the cases need an S1 service, production answers %s' % state)
        else:
            ctx = RunContext()
            for case in row['cases']:
                expect = contracts.get(case['id'], {}).get('expect')
                params = ctx.resolve(case['params'])
                desc = 'M24 %s backup_run_log(%s)' % (case['id'], json.dumps(params))
                if expect is None:
                    report.product.append('%s: no result contract with an expectation in pipeline/matrix.yaml' % desc)
                else:
                    _judge(report, desc, case['id'], params, expect, ctx)
            report.info.append('%d cases of row M24 executed; run with a log: %s, run without a log: %s' % (len(row['cases']), ctx.run_id, ctx.bare_id))
    except live.LiveUnreachable as exc:
        report.env.append('M24: not executed, production service unreachable: %s' % exc)
    report.finish(name)
