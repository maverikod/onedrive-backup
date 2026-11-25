'''Revision 14 client and odbcli checks of the run diagnostics (matrix TODO 10.23.R.5 CLIENT and ODBCLI, 10.23.R.6 TR6; rows CK-RUN1, CK-RUN2, OC-RUN1, OC-RUN2; block RUN-REASON).

BackupClient.schedule_status keeps its signature and returns reason, log and retried of every run object unchanged from the wire; the new BackupClient.run_log(run_id,
offset=None, limit=None, tail=None) returns the raw result of backup_run_log (an omitted optional parameter is the key ABSENT on the wire). odbcli schedule-status prints
one line per non-ok run with its reason text and log name; the new subcommand run-log --run-id [--offset N] [--limit N] [--tail] [--json] prints the text of the slice,
--json the raw result (flag spelling is a tester assumption, 10.23.R.2). Because the live history of 0.3.28 holds no run with a reason or a log, the printing and the
pass-through are also proved on a FIXTURE: the transport of the thin wrapper (JsonRpcClient.execute_command_unified of mcp-proxy-adapter) is replaced inside this process
and answers a fixed status or log result; nothing reaches the service then. TESTER ASSUMPTION: the readable line of a non-ok run holds the first 8 characters of its
run id, its reason text and its log name on ONE line that is not a JSON or dict dump (no brace).
'''

from __future__ import annotations

import contextlib
import importlib
import inspect
import json
from typing import Any, Iterator
from unittest import mock

from pipeline import b4cli, b4client, live, rev14run, rev14runlog, sched12_live, sched12_rows
from pipeline.report import Report
from pipeline.rev14cli import _cli_wire, _help_flags, _signature, _wire

EMPTY = inspect.Parameter.empty
BAD_ID = 'aaaaaaaa-1111-4111-8111-111111111111'
OK_ID = 'bbbbbbbb-2222-4222-8222-222222222222'
REASON = 'library ДЕНЬГИ: rclone sync exit 5: Failed to sync with 2 errors'
COMMAND = 'backup_run_log'
SIG_RUN_LOG: list[tuple[str, Any]] = [('run_id', EMPTY), ('offset', None), ('limit', None), ('tail', None)]
FLAGS_RUN_LOG = ['--run-id', '--offset', '--limit', '--tail', '--json']
LOG_RESULT = {'run_id': BAD_ID, 'name': BAD_ID + '.log', 'size_bytes': 18, 'offset': 0, 'length': 18, 'eof': True, 'encoding': 'utf-8', 'text': 'line one\nline two\n', 'rotated': False}


def _run(run_id: str, code: int, status: str, reason: str | None) -> dict[str, Any]:
    '''Build one fixture run object with the keys of revision 14.

    Args:
        run_id: the run id.
        code: the exit code.
        status: the status word.
        reason: the reason or None.

    Returns:
        The run object.
    '''
    log = {'name': run_id + '.log', 'size_bytes': 1234, 'available': True}
    return {'run_id': run_id, 'started_at': '2026-11-25T23:06:24Z', 'finished_at': '2026-11-25T23:20:00Z', 'exit_code': code, 'status': status, 'trigger': 'schedule',
            'slot_utc': '2026-11-25T23:00:00Z', 'reason': reason, 'log': log, 'retried': 0}


STATUS = {'scheduler': {'state': 'waiting', 'thread_alive': True, 'leader': True}, 'current_run': None, 'last_run': _run(BAD_ID, 1, 'errors', REASON), 'next_run': None,
          'missed': None, 'history': [_run(BAD_ID, 1, 'errors', REASON), _run(OK_ID, 0, 'ok', None)], 'server_time_utc': '2026-11-26T00:00:00Z'}


@contextlib.contextmanager
def serve(answers: dict[str, Any]) -> Iterator[None]:
    '''Answer every command of the odbcli or client from a fixture instead of sending it.

    Args:
        answers: command name -> the data of its success answer.

    Yields:
        None while the transport is replaced.
    '''
    rpc_class = importlib.import_module('mcp_proxy_adapter.client.jsonrpc_client.client').JsonRpcClient

    async def execute(rpc: Any, command: str, params: Any = None, *args: Any, **kwargs: Any) -> dict:
        '''Answer one command from the fixture.

        Args:
            rpc: the adapter client.
            command: the command name.
            params: the parameter map, ignored.
            args: ignored.
            kwargs: ignored.

        Returns:
            A success envelope with the fixture data.
        '''
        return {'result': {'success': True, 'data': answers[command]}}

    async def close(rpc: Any) -> None:
        '''Close nothing: no connection was opened.

        Args:
            rpc: the adapter client.

        Returns:
            None.
        '''
        return None

    with mock.patch.object(rpc_class, 'execute_command_unified', execute), mock.patch.object(rpc_class, 'close', close):
        yield


def _client(report: Report, method: str, label: str) -> Any:
    '''Return the bound BackupClient method, or None after a PRODUCT finding when the client or the method is missing.

    Args:
        report: the findings collector.
        method: the method name.
        label: the row label.

    Returns:
        The bound method or None.
    '''
    module = b4client.load_client(report)
    client = b4client.make_client(module, report) if module is not None else None
    func = getattr(client, method, None)
    if client is not None and not callable(func):
        report.product.append('%s client/onedrive_backup_client: BackupClient has no method %s (10.23.R.5 CLIENT)' % (label, method))
        return None
    return func


def client_status(name: str) -> None:
    '''CK-RUN1: schedule_status keeps its signature and returns reason, log and retried unchanged from the wire (fixture and live).

    Args:
        name: the named check.

    Returns:
        None.
    '''
    report = Report()
    method = _client(report, 'schedule_status', 'CK-RUN1')
    if method is not None:
        names = [item[0] for item in _signature(method)]
        if names != ['history_limit']:
            report.product.append('CK-RUN1 BackupClient.schedule_status takes %s, expected [history_limit] (unchanged signature)' % names)
        with serve({'backup_schedule_status': STATUS}):
            got, error = b4client.drive(method, history_limit=3)
        if error is not None or got != STATUS:
            report.product.append('CK-RUN1 fixture: schedule_status returned %s (error %s), expected the fixture unchanged' % (str(got)[:100], error))
        try:
            got, error = b4client.drive(method, history_limit=50)
            wire = sched12_rows.call('backup_schedule_status', {'history_limit': 50})
            if error is not None or sched12_live.strip(got) != sched12_live.strip(wire):
                report.product.append('CK-RUN1 live: schedule_status(history_limit=50) returned %s (error %s), not the result of the command' % (str(got)[:100], error))
            report.product.extend('CK-RUN1 live: %s' % problem for problem in rev14run.status_problems(got))
        except live.LiveUnreachable as exc:
            report.env.append('CK-RUN1 live case: production service unreachable: %s' % exc)
    report.finish(name)


def client_run_log(name: str) -> None:
    '''CK-RUN2: BackupClient.run_log(run_id, offset=None, limit=None, tail=None), its wire map and the raw result of backup_run_log.

    Args:
        name: the named check.

    Returns:
        None.
    '''
    report = Report()
    method = _client(report, 'run_log', 'CK-RUN2')
    if method is not None:
        got = _signature(method)
        if got != SIG_RUN_LOG:
            report.product.append('CK-RUN2 BackupClient.run_log%s, expected %s' % (got, SIG_RUN_LOG))
        for kwargs in ({'run_id': BAD_ID}, {'run_id': BAD_ID, 'offset': 5, 'limit': 10}, {'run_id': BAD_ID, 'tail': True}):
            _wire(report, 'CK-RUN2', method, COMMAND, kwargs, {})
        with serve({COMMAND: LOG_RESULT}):
            value, error = b4client.drive(method, BAD_ID, tail=True)
        if error is not None or value != LOG_RESULT:
            report.product.append('CK-RUN2 fixture: run_log returned %s (error %s), expected the raw result unchanged' % (str(value)[:100], error))
        try:
            ctx = rev14runlog.RunContext()
            if ctx.run_id is not None:
                value, error = b4client.drive(method, ctx.run_id, tail=True)
                kind, _, _, raw = live.request(COMMAND, {'run_id': ctx.run_id, 'tail': True})
                if error is not None or kind != 'success' or value != raw:
                    report.product.append('CK-RUN2 live: run_log(%s, tail=True) returned %s (error %s), not the result of the command' % (ctx.run_id[:8], str(value)[:100], error))
        except live.LiveUnreachable as exc:
            report.env.append('CK-RUN2 live case: production service unreachable: %s' % exc)
    report.finish(name)


def odbcli_status(name: str) -> None:
    '''OC-RUN1: schedule-status --json equals the command and carries the keys; the plain output has one readable line per non-ok run.

    Args:
        name: the named check.

    Returns:
        None.
    '''
    report = Report()
    main = b4cli.entry(report)
    subs = b4cli._subcommands(main) if main is not None else None
    if main is not None and (subs is None or 'schedule-status' not in subs):
        report.product.append('OC-RUN1 odbcli lists the subcommands %s, expected schedule-status among them' % subs)
    elif main is not None:
        with serve({'backup_schedule_status': STATUS}):
            code, out, err = b4cli.run_cli(main, b4cli.global_args() + ['schedule-status'])
        lines = [line for line in out.splitlines() if BAD_ID[:8] in line and REASON in line and BAD_ID + '.log' in line and '{' not in line]
        if code != 0 or not lines or any(OK_ID[:8] in line and REASON in line for line in out.splitlines()):
            report.product.append('OC-RUN1 odbcli schedule-status prints no readable line with the run id, the reason and the log name of a non-ok run (exit %r, stdout %s)' % (code, out[:200].replace('\n', ' | ')))
        try:
            code, out, err = b4cli.run_cli(main, b4cli.global_args() + ['schedule-status', '--json'])
            try:
                printed = json.loads(out)
            except ValueError:
                printed = None
            wire = sched12_rows.call('backup_schedule_status', {})
            if code != 0 or sched12_live.strip(printed) != sched12_live.strip(wire):
                report.product.append('OC-RUN1 schedule-status --json: exit %r, stdout %s, stderr %s, expected the JSON result of the command' % (code, out[:100], err[:100]))
            report.product.extend('OC-RUN1 live: %s' % problem for problem in rev14run.status_problems(printed))
        except live.LiveUnreachable as exc:
            report.env.append('OC-RUN1 live case: production service unreachable: %s' % exc)
    report.finish(name)


def odbcli_run_log(name: str) -> None:
    '''OC-RUN2: the subcommand run-log, its help, its wire map and its printed text or raw JSON.

    Args:
        name: the named check.

    Returns:
        None.
    '''
    report = Report()
    main = b4cli.entry(report)
    subs = b4cli._subcommands(main) if main is not None else None
    if main is not None and (subs is None or 'run-log' not in subs):
        report.product.append('OC-RUN2 odbcli lists the subcommands %s, expected run-log among them (10.23.R.5 ODBCLI)' % subs)
    elif main is not None:
        _help_flags(report, main, 'run-log', 'OC-RUN2', FLAGS_RUN_LOG)
        _cli_wire(report, main, 'OC-RUN2', ['run-log', '--run-id', BAD_ID, '--offset', '5', '--limit', '10'], COMMAND, {'run_id': BAD_ID, 'offset': 5, 'limit': 10})
        _cli_wire(report, main, 'OC-RUN2', ['run-log', '--run-id', BAD_ID, '--tail'], COMMAND, {'run_id': BAD_ID, 'tail': True})
        with serve({COMMAND: LOG_RESULT}):
            code, out, err = b4cli.run_cli(main, b4cli.global_args() + ['run-log', '--run-id', BAD_ID])
            jcode, jout, jerr = b4cli.run_cli(main, b4cli.global_args() + ['run-log', '--run-id', BAD_ID, '--json'])
        if code != 0 or 'line one' not in out or 'line two' not in out or '{' in out:
            report.product.append('OC-RUN2 run-log --run-id prints %s (exit %r), expected the text of the slice' % (out[:100], code))
        try:
            printed = json.loads(jout)
        except ValueError:
            printed = None
        if jcode != 0 or printed != LOG_RESULT:
            report.product.append('OC-RUN2 run-log --json prints %s (exit %r, stderr %s), expected the raw result' % (jout[:100], jcode, jerr[:80]))
    report.finish(name)
