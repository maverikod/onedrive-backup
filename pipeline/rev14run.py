'''Revision 14 run diagnostics rows (matrix TODO 10.23.R.2, 10.23.R.5, 10.23.R.6; rows M17 CHANGED, M24 NEW; checks cmd_backup_schedule_status, cmd_backup_run_log, last_run_diagnosable; block RUN-REASON).

M17: last_run, every history item and current_run carry the additive keys reason (null or 1..500 characters, null for exit 0 and while running), log (null or
{name '<run_id>.log', size_bytes int >= 0, available bool}) and retried (int >= 0) beside the unchanged keys (TR1, RR1, RR2). The earlier M17 validator
s12_sc10 asserts the exact keys of 0.3.28, so it is wrapped: the three added keys are removed from a copy before it runs (RM7 additive rule). TR2 (last_run_diagnosable,
LAGGING): every non-ok run finished after the deployment's scheduler.started_at has a non-empty reason and log.available true; older runs are recorded as 'predates
the fix', never RED; absent keys are RED (TR1). M24 backup_run_log (TR5, RR2-RR4, RR8): the run ids come from the real history: $RUN_ID is the newest run whose log is
available, $RUN_ID_BEFORE_FIX the newest finished run without a log. TESTER ASSUMPTION: when no run has a log yet (the first run after the deployment writes it) the cases
that need a log are STATE RED, never skipped; while the command does not exist every case is PRODUCT RED (-32601). Nothing is written to the data volume.
'''

from __future__ import annotations
from typing import Any

from pipeline import live, rev11, sched12, sched12_rows
from pipeline.report import Report

ADDED = ('reason', 'log', 'retried')
LOG_KEYS = ['name', 'size_bytes', 'available']
ORIGINAL_SC10 = rev11.VALIDATORS['s12_sc10']


def _whole(value: Any) -> bool:
    '''Tell whether a value is an integer that is not a boolean.

    Args:
        value: any value.

    Returns:
        True for an int.
    '''
    return isinstance(value, int) and not isinstance(value, bool)


def run_problems(item: Any, label: str, current: bool = False) -> list[str]:
    '''Return the violations of one run object of M17 against TR1, RR1 and RR2.

    Args:
        item: last_run, a history item or current_run.
        label: where it came from.
        current: true for current_run (its own base keys, reason null).

    Returns:
        The problems.
    '''
    base = sched12_rows.CURRENT_KEYS if current else sched12_rows.RUN_KEYS
    if not isinstance(item, dict):
        return ['%s is %s, expected an object' % (label, str(item)[:80])]
    found: list[str] = []
    missing = [key for key in list(base) + list(ADDED) if key not in item]
    extra = [key for key in item if key not in base and key not in ADDED]
    if missing or extra:
        found.append('%s has the keys %s, missing %s, unexpected %s (TR1)' % (label, sorted(item), missing, extra))
    reason, log, retried = item.get('reason', None), item.get('log', None), item.get('retried', 0)
    if 'reason' in item and reason is not None and (not isinstance(reason, str) or not 0 < len(reason) <= 500 or item.get('exit_code') == 0 or current):
        found.append('%s reason %r, expected null for exit 0 or a running run, else 1..500 characters (RR1)' % (label, str(reason)[:60]))
    if 'log' in item and log is not None:
        name = '%s.log' % item.get('run_id')
        if not isinstance(log, dict) or sorted(log) != sorted(LOG_KEYS) or log.get('name') != name or not _whole(log.get('size_bytes')) \
                or log['size_bytes'] < 0 or not isinstance(log.get('available'), bool):
            found.append('%s log %s, expected null or {name %s, size_bytes int >= 0, available bool} (RR2)' % (label, str(log)[:100], name))
    if 'retried' in item and (not _whole(retried) or retried < 0):
        found.append('%s retried %r, expected an integer >= 0' % (label, retried))
    return found


def status_problems(data: Any) -> list[str]:
    '''Return the TR1 violations of a backup_schedule_status result (last_run, every history item, current_run).

    Args:
        data: the result.

    Returns:
        One entry per kind of violation, with the number of runs concerned.
    '''
    if not isinstance(data, dict):
        return ['the status is %s, expected an object' % str(data)[:80]]
    items = [('last_run', data.get('last_run'), False)] + [('a history item', item, False) for item in data.get('history') or []]
    items += [('current_run', data.get('current_run'), True)]
    seen: dict[str, int] = {}
    for label, item, current in items:
        for problem in run_problems(item, label, current) if item is not None else []:
            seen[problem] = seen.get(problem, 0) + 1
    return ['%s (%d run object(s) with this problem of %d)' % (problem, count, len(items)) for problem, count in seen.items()]


def diagnosable(data: Any) -> tuple[list[str], list[str]]:
    '''TR2: judge the history of a status result; return (violations, notes of runs that predate the fix).

    Args:
        data: the backup_schedule_status result with a long history.

    Returns:
        The violations and the notes.
    '''
    found = status_problems(data)
    notes: list[str] = []
    started = sched12.parse_iso(((data or {}).get('scheduler') or {}).get('started_at')) if isinstance(data, dict) else None
    for item in (data.get('history') or []) if isinstance(data, dict) else []:
        if not isinstance(item, dict) or item.get('exit_code') == 0 or 'reason' not in item or 'log' not in item:
            continue
        finished = sched12.parse_iso(item.get('finished_at'))
        log = item.get('log')
        label = 'run %s (exit %s, %s)' % (str(item.get('run_id'))[:8], item.get('exit_code'), item.get('status'))
        if started is not None and finished is not None and finished <= started:
            notes.append('%s predates the fix: reason %r, log %s' % (label, item['reason'], log))
        elif not isinstance(item['reason'], str) or not item['reason'] or not isinstance(log, dict) or log.get('available') is not True:
            found.append('%s finished after the deployment but reason is %r and log is %s (TR2)' % (label, item['reason'], log))
    return found, notes


def _run_keys(case: rev11.Case) -> None:
    '''TR1: judge the run objects of one M17 case (last_run, the history, or current_run by the case id).

    Args:
        case: the executed case.

    Returns:
        None.
    '''
    data = case.data
    if 'tr1_current' in case.desc:
        problems = run_problems(data.get('current_run'), 'current_run', True) if data.get('current_run') is not None else []
    elif 'history_limit' in case.params:
        problems = status_problems({'history': data.get('history')})
    else:
        problems = run_problems(data.get('last_run'), 'last_run') if data.get('last_run') is not None else []
    for problem in problems:
        case.bad(problem)


def _lagging(case: rev11.Case) -> None:
    '''TR2 inside the row M17: the same judgement as the named check last_run_diagnosable.

    Args:
        case: the executed case.

    Returns:
        None.
    '''
    found, notes = diagnosable(case.data)
    case.report.info.extend(notes)
    for problem in found:
        case.bad(problem)


def _without_added(value: Any) -> Any:
    '''Return a copy of a status result without the keys reason, log and retried of every run object.

    Args:
        value: the status result.

    Returns:
        The copy.
    '''
    def cut(item: Any) -> Any:
        '''Remove the added keys of one run object.

        Args:
            item: a run object or None.

        Returns:
            The object without them.
        '''
        return {key: part for key, part in item.items() if key not in ADDED} if isinstance(item, dict) else item

    if not isinstance(value, dict):
        return value
    copy = dict(value)
    for key in ('last_run', 'current_run'):
        copy[key] = cut(copy.get(key))
    copy['history'] = [cut(item) for item in value.get('history') or []]
    return copy


def _sc10(case: rev11.Case) -> None:
    '''SC10 of 0.3.28 on a copy without the added keys (additive compatibility RM7).

    Args:
        case: the executed case.

    Returns:
        None.
    '''
    ORIGINAL_SC10(rev11.Case(case.report, case.desc, _without_added(case.data), case.ctx, case.params))


rev11.VALIDATORS.update({'run_keys': _run_keys, 'lagging': _lagging, 's12_sc10': _sc10})


def status_row(name: str) -> None:
    '''Run every case of row M17 (the 0.3.28 cases and the TR1, TR2 cases).

    Args:
        name: the named check.

    Returns:
        None.
    '''
    sched12_rows.run_row('M17', name)


def last_run_diagnosable(name: str) -> None:
    '''TR2: every failed run after the deployment has a reason and an available log (LAGGING, read-only, never starts a run).

    Args:
        name: the named check.

    Returns:
        None.
    '''
    report = Report()
    try:
        data = sched12_rows.call('backup_schedule_status', {'history_limit': 50})
        found, notes = diagnosable(data) if data else (['backup_schedule_status answered no result'], [])
        report.product.extend('M17 tr2_last_run_diagnosable: %s' % problem for problem in found)
        report.info.extend(notes)
        report.info.append('%d run(s) in the history, deployment started_at %s' % (len((data or {}).get('history') or []), ((data or {}).get('scheduler') or {}).get('started_at')))
    except live.LiveUnreachable as exc:
        report.env.append('M17 tr2_last_run_diagnosable: not executed, production service unreachable: %s' % exc)
    report.finish(name)
