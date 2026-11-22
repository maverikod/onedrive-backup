'''Revision 12 client, odbcli and live checks of the schedule commands (matrix TODO 10.20.3 CLIENT AND CLI, 10.20.7 safety rule, 10.20.10).

client_check and odbcli_check compare the client method and the odbcli subcommand with the raw command (the volatile fields are removed).
schedule_live reads the status twice 35 s apart (SC10) and performs the ONE real write of the revision (SC6) under the safety rule of
10.20.7: the original text and revision are read first, only a valid schedule that cannot fire inside the next 24 hours is written (with
CATCHUP=0), nothing is written while a backup runs or is due within 15 minutes, and the original text is restored byte-exact in a
finally with the expected revision. No live case ever starts a backup.
'''

from __future__ import annotations

import inspect
import json
import re
import time
from typing import Any

from pipeline import b4cli, b4client, live, sched12, sched12_rows
from pipeline.report import Report
from pipeline.sched12_rows import call, far_future

CLIENT = {'schedule_get': ['next_count'], 'schedule_set': ['text', 'expected_revision', 'dry_run', 'next_count', 'actor'],
          'schedule_status': ['history_limit']}
BACKUP_FILE = re.compile(r'^schedule[.][0-9]{8}T[0-9]{6}Z[.][0-9a-f]{8}[.]cron$')
POLL_SECONDS = 35


def strip(value: Any) -> Any:
    '''Return a copy of a result without the volatile fields (server time, last tick, elapsed seconds).

    Args:
        value: a result, list or scalar.

    Returns:
        The copy.
    '''
    if isinstance(value, dict):
        return {key: strip(item) for key, item in value.items() if key not in sched12_rows.VOLATILE}
    if isinstance(value, list):
        return [strip(item) for item in value]
    return value


def _args(method: str) -> tuple[str, dict[str, Any], dict[str, Any]]:
    '''Return the command, the client keywords and the raw parameters of the baseline call of a method (a dry run for set).

    Args:
        method: schedule_get, schedule_set or schedule_status.

    Returns:
        The command, the keyword arguments of the client call and the parameter map of the equal raw call.
    '''
    if method == 'schedule_set':
        text = str(call('backup_schedule_get', {}).get('text', ''))
        return 'backup_schedule_set', {'text': text, 'dry_run': True}, {'text': text, 'dry_run': True, 'actor': 'client'}
    return 'backup_' + method.replace('schedule_', 'schedule_'), {}, {}


def client_check(method: str, name: str) -> None:
    '''CK-SCH1..3: BackupClient has the method with the contract parameters and it returns what the command returns.

    Args:
        method: the client method.
        name: the named check.

    Returns:
        None.
    '''
    report = Report()
    module = b4client.load_client(report)
    func = getattr(module.BackupClient, method, None) if module is not None else None
    if module is not None and not callable(func):
        report.product.append('client/onedrive_backup_client/api.py: BackupClient has no method %s (10.20.3 CLIENT AND CLI)' % method)
    elif module is not None and func is not None:
        names = list(inspect.signature(func).parameters)[1:]
        client = b4client.make_client(module, report)
        command, kwargs, raw = _args(method)
        if names != CLIENT[method]:
            report.product.append('BackupClient.%s takes %s, expected %s' % (method, names, CLIENT[method]))
        elif client is not None:
            got, error = b4client.drive(getattr(client, method), **kwargs)
            if error is not None or strip(got) != strip(call(command, raw)):
                report.product.append('BackupClient.%s(%s) returned %s (error %s), not the result of %s' % (method, kwargs, str(got)[:100], error, command))
    report.finish(name)


def odbcli_check(sub: str, name: str) -> None:
    '''OC-SCH1..3: odbcli has the subcommand; get and status print the JSON result, set prints the revision of a dry run.

    Args:
        sub: schedule-get, schedule-set or schedule-status.
        name: the named check.

    Returns:
        None.
    '''
    report = Report()
    main = b4cli.entry(report)
    if main is not None:
        subs = b4cli._subcommands(main)
        if subs is None or sub not in subs:
            report.product.append('odbcli lists the subcommands %s, expected %s among them (10.20.3 CLIENT AND CLI)' % (subs, sub))
        elif sub == 'schedule-set':
            text = str(call('backup_schedule_get', {}).get('text', ''))
            code, out, err = b4cli.run_cli(main, b4cli.global_args() + [sub, '--text', text, '--dry-run'])
            if code != 0 or sched12_rows.digest(text) not in out:
                report.product.append('odbcli %s --text <stored text> --dry-run: exit %s, stdout %s, stderr %s, expected exit 0 and the revision of the text' % (sub, code, out[:100], err[:100]))
        else:
            code, out, err = b4cli.run_cli(main, b4cli.global_args() + [sub, '--json'])
            command = 'backup_' + sub.replace('-', '_')
            try:
                printed = json.loads(out)
            except ValueError:
                printed = None
            if code != 0 or strip(printed) != strip(call(command, {})):
                report.product.append('odbcli %s --json: exit %s, stdout %s, stderr %s, expected the JSON result of %s' % (sub, code, out[:100], err[:100], command))
    report.finish(name)


def _ticks(report: Report) -> None:
    '''SC10: two status reads 35 s apart both show a live thread and the second shows a later last tick.

    Args:
        report: the findings collector.

    Returns:
        None.
    '''
    first = call('backup_schedule_status', {})
    time.sleep(POLL_SECONDS)
    second = call('backup_schedule_status', {})
    ticks = [sched12.parse_iso((item.get('scheduler') or {}).get('last_tick_at')) for item in (first, second)]
    alive = [bool((item.get('scheduler') or {}).get('thread_alive')) for item in (first, second)]
    if alive != [True, True] or ticks[0] is None or ticks[1] is None or not ticks[1] > ticks[0]:
        report.product.append('SC10 two backup_schedule_status reads %d s apart: thread_alive %s and last_tick_at %s, expected true twice and the second later' % (POLL_SECONDS, alive, [str(item) for item in ticks]))


def _busy(status: dict) -> bool:
    '''Return True when a backup runs or the next planned start is within 15 minutes.

    Args:
        status: the status result.

    Returns:
        True when a write must not happen now.
    '''
    start = sched12.parse_iso((status.get('next_run') or {}).get('start_utc'))
    now = sched12.parse_iso(status.get('server_time_utc'))
    near = start is not None and now is not None and abs((start - now).total_seconds()) < 900
    return status.get('current_run') is not None or near


def _write(report: Report) -> None:
    '''SC6: write a far-future schedule, read it back, wait for the scheduler, restore the original in a finally.

    Args:
        report: the findings collector.

    Returns:
        None.
    '''
    before = call('backup_schedule_get', {})
    text, revision = before.get('text'), before.get('revision')
    if not isinstance(text, str) or not isinstance(revision, str) or before.get('valid') is not True:
        report.state.append('SC6 the stored schedule is not readable and valid (valid %r): the write case is not run' % before.get('valid'))
        return
    if _busy(call('backup_schedule_status', {})):
        report.state.append('SC6 a backup runs or is due within 15 minutes: the write case is not run (safety rule of 10.20.7)')
        return
    new = far_future(str(before.get('timezone') or sched12.ZONE))
    current = revision
    try:
        kind, code, message, data = live.request('backup_schedule_set', {'text': new, 'expected_revision': revision, 'actor': 'pipeline'})
        if kind != 'success' or not isinstance(data, dict):
            report.product.append('SC6 backup_schedule_set of a far-future text: got %s %s %s, expected success' % (kind, code, message))
            return
        current = str(data.get('revision'))
        if (data.get('written'), data.get('changed'), data.get('previous_revision')) != (True, True, revision) or not BACKUP_FILE.match(str(data.get('backup_file'))):
            report.product.append('SC6 written %r changed %r previous_revision %s backup_file %r, expected true, true, the revision read first and schedule.<ts>.<8hex>.cron' % (data.get('written'), data.get('changed'), str(data.get('previous_revision'))[:12], data.get('backup_file')))
        if call('backup_schedule_get', {}).get('text') != new:
            report.product.append('SC6 backup_schedule_get after the write does not return the written text')
        for _ in range(8):
            if call('backup_schedule_status', {}).get('schedule', {}).get('revision') == current:
                break
            time.sleep(5)
        else:
            report.product.append('SC6 the status schedule.revision did not converge to %s within 35 s' % current[:12])
    finally:
        done = call('backup_schedule_set', {'text': text, 'expected_revision': current, 'actor': 'pipeline'})
        if done.get('revision') != revision or call('backup_schedule_get', {}).get('revision') != revision:
            report.env.append('SC6 RESTORE FAILED: the original schedule revision %s is not back (now %s); restore the text by hand' % (revision[:12], str(call('backup_schedule_get', {}).get('revision'))[:12]))


def schedule_live() -> None:
    '''Run the live schedule check: SC1 and SC12 reads, SC10 ticks, SC6 the guarded real write.

    Returns:
        None.
    '''
    report = Report()
    try:
        if live.service_state() != 'S1':
            report.state.append('the live schedule cases need an S1 service')
        else:
            got = call('backup_schedule_get', {})
            if not got:
                report.product.append('backup_schedule_get answered no success result on the deployed service (10.20.3 M15)')
            else:
                before = (got.get('revision'), call('backup_schedule_status', {}).get('history'))
                _ticks(report)
                _write(report)
                if (call('backup_schedule_get', {}).get('revision'), call('backup_schedule_status', {}).get('history')) != (before[0], before[1]) and before[1] is not None:
                    report.info.append('SC12 the history changed during the check: the write case ran and restored the schedule')
    except live.LiveUnreachable as exc:
        report.env.append('schedule_live: not executed, production service unreachable: %s' % exc)
    report.finish('schedule_live')
