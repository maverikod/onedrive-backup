'''Revision 13 client and odbcli checks (matrix TODO 10.21.4 CLIENT and ODBCLI, rows CK-TREE1..3 and OC-TREE1..3, block TREE-REV13).

BackupClient of the checkout source must expose folder_children and the scope parameters site_id, drive_id, dir and recursive of
search_files and suggest_names with the signatures of 10.21.4; an omitted optional parameter is the key ABSENT on the wire, never null.
The wire map is read by recording JsonRpcClient.execute_command_unified of mcp-proxy-adapter inside this process (the transport of the
thin wrapper, decision 1): nothing reaches the service while recording. The results are compared with the live command where the
deployed service answers it. odbcli gains the subcommand folder-children and the arguments --site-id, --drive-id, --dir and --recursive
of search-files and suggest-names (flag spelling of 10.21.4, a tester assumption as in 10.19); the subcommand help documents every
argument, the info manual and the command reference list backup_folder_children. The revision 11 assertions of C-K17, C-K18, O18 and
O19 stay: the baseline result equals the command result.
'''

from __future__ import annotations

import contextlib
import importlib
import inspect
import json
import re
from typing import Any, Iterator
from unittest import mock

from pipeline import b4cli, b4client, live, rev11, rev13
from pipeline.report import Report

EMPTY = inspect.Parameter.empty
SCOPE = ('site_id', 'drive_id', 'dir', 'recursive')
FOLDER = 'backup_folder_children'
SIGNATURES: dict[str, list[tuple[str, Any]]] = {
    'folder_children': [('site_id', None), ('drive_id', None), ('dir', None), ('site_ids', None), ('dates', None), ('name_part', ''),
                        ('limit', 200), ('offset', 0)],
    'search_files': [('site_ids', None), ('dates', None), ('name_part', ''), ('limit', 100), ('offset', 0), ('site_id', None),
                     ('drive_id', None), ('dir', None), ('recursive', None)],
    'suggest_names': [('text', EMPTY), ('site_ids', None), ('dates', None), ('limit', 10), ('site_id', None), ('drive_id', None),
                      ('dir', None), ('recursive', None)],
}
COMMANDS = {'folder_children': FOLDER, 'search_files': 'backup_search_files', 'suggest_names': 'backup_suggest_names'}
METHODS = {command: method for method, command in COMMANDS.items()}
CK_ROWS = {FOLDER: 'CK-TREE1', 'backup_search_files': 'CK-TREE2', 'backup_suggest_names': 'CK-TREE3'}
OC_ROWS = {FOLDER: 'OC-TREE1', 'backup_search_files': 'OC-TREE2', 'backup_suggest_names': 'OC-TREE3'}
OLD_ROWS = {FOLDER: 'CK-TREE1', 'backup_search_files': 'C-K17', 'backup_suggest_names': 'C-K18'}
OLD_OC_ROWS = {'backup_search_files': 'O18', 'backup_suggest_names': 'O19'}
BASELINE: dict[str, dict[str, Any]] = {FOLDER: {}, 'backup_search_files': rev11.BASELINE['backup_search_files'],
                                       'backup_suggest_names': rev11.BASELINE['backup_suggest_names']}
GIVEN: dict[str, dict[str, Any]] = {
    FOLDER: {'site_id': 'site-1', 'drive_id': 'drive-1', 'dir': 'a/b', 'site_ids': ['site-1'], 'dates': [rev13.TREE_DATE],
             'name_part': '*.pdf', 'limit': 5, 'offset': 2},
    'backup_search_files': {'name_part': 'акт*', 'limit': 5, 'site_id': 'site-1', 'drive_id': 'drive-1', 'dir': 'a/b', 'recursive': True},
    'backup_suggest_names': {'text': 'акт', 'site_id': 'site-1', 'drive_id': 'drive-1', 'dir': 'a/b', 'recursive': True},
}
OMITTED: dict[str, tuple[str, ...]] = {FOLDER: ('site_id', 'drive_id', 'dir', 'site_ids', 'dates'), 'backup_search_files': SCOPE,
                                       'backup_suggest_names': SCOPE}
SUBCOMMANDS = {FOLDER: 'folder-children', 'backup_search_files': 'search-files', 'backup_suggest_names': 'suggest-names'}
FLAGS = {FOLDER: ['--site-id', '--drive-id', '--dir', '--site-ids', '--dates', '--name-part', '--limit', '--offset'],
         'backup_search_files': ['--site-id', '--drive-id', '--dir', '--recursive'],
         'backup_suggest_names': ['--site-id', '--drive-id', '--dir', '--recursive']}
ARGV_BASE = {FOLDER: [], 'backup_search_files': ['--name-part', 'акт*', '--limit', '5'], 'backup_suggest_names': ['--text', 'акт']}
ARGV_GIVEN = {
    FOLDER: ['--site-id', 'site-1', '--drive-id', 'drive-1', '--dir', 'a/b', '--site-ids', 'site-1', '--dates', rev13.TREE_DATE,
             '--name-part', '*.pdf', '--limit', '5', '--offset', '2'],
    'backup_search_files': ['--name-part', 'акт*', '--limit', '5', '--site-id', 'site-1', '--drive-id', 'drive-1', '--dir', 'a/b',
                            '--recursive'],
    'backup_suggest_names': ['--text', 'акт', '--site-id', 'site-1', '--drive-id', 'drive-1', '--dir', 'a/b', '--recursive'],
}


def _live_case(command: str, site: str, drive: str) -> dict[str, Any]:
    '''Return the live scope case of a command: the real site and the library ДЕНЬГИ of 10.21.1 F4.

    Args:
        command: the service command.
        site: the site id.
        drive: the drive id of ДЕНЬГИ.

    Returns:
        The parameter map.
    '''
    if command == FOLDER:
        return {'site_id': site, 'dates': [rev13.TREE_DATE]}
    if command == 'backup_search_files':
        return {'site_id': site, 'drive_id': drive, 'dates': [rev13.TREE_DATE], 'recursive': True, 'limit': 5}
    return {'text': 'акт', 'site_id': site, 'drive_id': drive, 'recursive': True}


@contextlib.contextmanager
def recorder() -> Iterator[list[tuple[str, dict]]]:
    '''Record every JsonRpcClient.execute_command_unified call instead of sending it; each answers a success with no data.

    Yields:
        The list of (command, parameter map) recorded in call order.
    '''
    calls: list[tuple[str, dict]] = []
    rpc_class = importlib.import_module('mcp_proxy_adapter.client.jsonrpc_client.client').JsonRpcClient

    async def execute(rpc: Any, command: str, params: Any = None, *args: Any, **kwargs: Any) -> dict:
        '''Record one command call.

        Args:
            rpc: the adapter client.
            command: the command name.
            params: the parameter map sent.
            args: further positional arguments.
            kwargs: further keyword arguments.

        Returns:
            A success envelope.
        '''
        calls.append((command, dict(params or {})))
        return {'result': {'success': True, 'data': {'recorded': command}}}

    async def close(rpc: Any) -> None:
        '''Close nothing: no connection was opened.

        Args:
            rpc: the adapter client.

        Returns:
            None.
        '''
        return None

    with mock.patch.object(rpc_class, 'execute_command_unified', execute), mock.patch.object(rpc_class, 'close', close):
        yield calls


def wire_problem(calls: list[tuple[str, dict]], command: str, wanted: dict[str, Any], omitted: tuple[str, ...]) -> str:
    '''Judge the recorded wire map: exactly one call of the command, the given keys with their values, no omitted key, no null.

    Args:
        calls: the recorded calls.
        command: the expected command.
        wanted: the keys and values that must be sent.
        omitted: the keys that must be absent.

    Returns:
        '' when conformant, else the finding text.
    '''
    if len(calls) != 1 or calls[0][0] != command:
        return 'sent %s, expected exactly one %s' % (calls, command)
    sent = calls[0][1]
    defaults = {name: value for name, value in SIGNATURES[METHODS[command]] if value is not None and value is not EMPTY}
    nulls = sorted(name for name, value in sent.items() if value is None)
    present = sorted(name for name in omitted if name in sent)
    wrong = {name: sent.get(name, '<absent>') for name, value in wanted.items() if sent.get(name, '<absent>') != value}
    off = {name: sent[name] for name, value in defaults.items() if name in sent and name not in wanted and sent[name] != value}
    if nulls or present or wrong or off:
        return 'sent %s: null keys %s, omitted keys present %s, given keys differing %s, defaults differing %s' % (sent, nulls, present, wrong, off)
    return ''


def _text(entries: list[tuple[str, Any]]) -> str:
    '''Render a parameter list as a signature text.

    Args:
        entries: (name, default) pairs; EMPTY marks a required parameter.

    Returns:
        The text, e.g. "text, limit=10".
    '''
    return ', '.join(name if default is EMPTY else '%s=%r' % (name, default) for name, default in entries)


def _ids() -> tuple[str, str]:
    '''Return the site id of the service and the drive id of the library ДЕНЬГИ (10.21.1 F4).

    Returns:
        (site id, drive id); 'site-none' or 'drive-none' when absent.
    '''
    site = rev11.Context().site or 'site-none'
    kind, _, _, data = live.request('backup_libraries_list', {'site_id': site, 'limit': 1000})
    items = data.get('items', []) if kind == 'success' and isinstance(data, dict) else []
    drive = next((str(i.get('drive_id')) for i in items if rev11.key(str(i.get('display_name'))) == rev11.key(rev13.DENGI)), 'drive-none')
    return site, drive


def _client_live(report: Report, client: Any, command: str, cases: list[dict[str, Any]], label: str) -> None:
    '''Compare the client result with the live command for each case; the deployed service must answer a success.

    Args:
        report: the findings collector.
        client: the project client.
        command: the service command.
        cases: the parameter maps.
        label: the row label of the findings.

    Returns:
        None.
    '''
    method = METHODS[command]
    for params in cases:
        kind, code, message, data = live.request(command, params)
        got, error = b4client.drive(getattr(client, method), **params)
        if kind != 'success':
            report.product.append('%s live %s(%s): the deployed service answers %s %s %s, expected the result of %s (10.21.4)'
                                  % (label, method, params, kind, code, str(message)[:120], command))
        elif error is not None or got != data:
            report.product.append('%s live BackupClient.%s(%s) returned %s (error %s), not the result of %s'
                                  % (label, method, params, str(got)[:100], error, command))
        else:
            report.info.append('%s live BackupClient.%s(%s) conformant: equals the result of %s' % (label, method, params, command))


def client_scope(method: str, name: str) -> None:
    '''CK-TREE1..3 (with C-K17/C-K18): the signature of 10.21.4, the wire map and the result of the command.

    Args:
        method: folder_children, search_files or suggest_names.
        name: the named check.

    Returns:
        None.
    '''
    report = Report()
    command = COMMANDS[method]
    row = CK_ROWS[command]
    module = b4client.load_client(report)
    func = getattr(module.BackupClient, method, None) if module is not None else None
    if module is not None and not callable(func):
        report.product.append('%s client/onedrive_backup_client/api.py: BackupClient has no method %s (10.21.4 CLIENT, command %s)' % (row, method, command))
    elif module is not None and func is not None:
        got = [(p.name, p.default) for p in list(inspect.signature(func).parameters.values())[1:]]
        conformant = got == SIGNATURES[method]
        if not conformant:
            report.product.append('%s BackupClient.%s(%s), expected (%s) (10.21.4 CLIENT; the existing positional order unchanged)'
                                  % (row, method, _text(got), _text(SIGNATURES[method])))
        client = b4client.make_client(module, report)
        if client is not None:
            for params, omitted in ((BASELINE[command], OMITTED[command]), (GIVEN[command], ())):
                with recorder() as calls:
                    _, error = b4client.drive(getattr(client, method), **params)
                problem = wire_problem(calls, command, params, omitted)
                if problem:
                    report.product.append('%s wire BackupClient.%s(%s): %s%s' % (row, method, params, problem, '; raised %s: %s' % (type(error).__name__, str(error)[:100]) if error else ''))
                else:
                    report.info.append('%s wire BackupClient.%s(%s) conformant: %s' % (row, method, params, calls[0][1]))
            try:
                _client_live(report, client, command, [BASELINE[command]], OLD_ROWS[command])
                if conformant:
                    site, drive = _ids()
                    _client_live(report, client, command, [_live_case(command, site, drive)], row)
            except live.LiveUnreachable as exc:
                report.env.append('%s live cases: not executed, production service unreachable: %s' % (row, exc))
    report.finish(name)


def _printed(out: str) -> Any:
    '''Return the JSON printed by odbcli, or None.

    Args:
        out: the standard output.

    Returns:
        The decoded value or None.
    '''
    try:
        return json.loads(out)
    except ValueError:
        return None


def _cli_help(report: Report, main: Any, command: str) -> None:
    '''The subcommand --help documents every argument of 10.21.4 (exact flag, '--site-id' is not matched by '--site-ids').

    Args:
        report: the findings collector.
        main: the odbcli entry function.
        command: the service command.

    Returns:
        None.
    '''
    sub = SUBCOMMANDS[command]
    code, out, err = b4cli.run_cli(main, [sub, '--help'])
    missing = [flag for flag in FLAGS[command] if not re.search(r'(?<![\w-])%s(?![\w-])' % re.escape(flag), out + err)]
    if code != 0 or missing:
        report.product.append('%s odbcli %s --help: exit %r, the arguments %s are not documented (10.21.4 ODBCLI, every argument documented)'
                              % (OC_ROWS[command], sub, code, missing))


def _cli_wire(report: Report, main: Any, command: str) -> None:
    '''odbcli maps its arguments to the client keys: omitted arguments are absent on the wire, given ones carry their values.

    Args:
        report: the findings collector.
        main: the odbcli entry function.
        command: the service command.

    Returns:
        None.
    '''
    sub = SUBCOMMANDS[command]
    for argv, wanted, omitted in ((ARGV_BASE[command], BASELINE[command], OMITTED[command]), (ARGV_GIVEN[command], GIVEN[command], ())):
        with recorder() as calls:
            code, out, err = b4cli.run_cli(main, b4cli.global_args() + [sub] + argv)
        problem = wire_problem(calls, command, wanted, omitted)
        if problem:
            report.product.append('%s wire odbcli %s %s: exit %r, %s, stderr %s' % (OC_ROWS[command], sub, ' '.join(argv), code, problem, err.strip()[-160:]))
        else:
            report.info.append('%s wire odbcli %s %s conformant: %s' % (OC_ROWS[command], sub, ' '.join(argv), calls[0][1]))


def _cli_listing(report: Report, main: Any) -> None:
    '''The command reference (odbcli help) and the info manual (odbcli info, the table of contents) list backup_folder_children.

    Args:
        report: the findings collector.
        main: the odbcli entry function.

    Returns:
        None.
    '''
    for sub, token in (('help', FOLDER), ('info', FOLDER + ' (command)')):
        code, out, err = b4cli.run_cli(main, b4cli.global_args() + [sub])
        text = json.dumps(_printed(out), ensure_ascii=False)
        if code != 0 or token not in text:
            report.product.append('OC-TREE1 odbcli %s: exit %r, the output does not list %r (10.21.4: the command reference and the info manual gain M19)%s'
                                  % (sub, code, token, '; stderr ' + err.strip()[-120:] if code != 0 else ''))


def odbcli_scope(command: str, name: str) -> None:
    '''OC-TREE1..3 (with O18/O19): the subcommand, its help, the wire map of the arguments and the printed result.

    Args:
        command: backup_folder_children, backup_search_files or backup_suggest_names.
        name: the named check.

    Returns:
        None.
    '''
    report = Report()
    sub = SUBCOMMANDS[command]
    main = b4cli.entry(report)
    if main is not None:
        try:
            subs = b4cli._subcommands(main)
            if subs is None or sub not in subs:
                report.product.append('%s odbcli lists the subcommands %s, expected %s among them (10.21.4 ODBCLI)' % (OC_ROWS[command], subs, sub))
            else:
                code, out, err = b4cli.run_cli(main, b4cli.global_args() + [sub] + ARGV_BASE[command])
                kind, rcode, message, data = live.request(command, BASELINE[command])
                label = OLD_OC_ROWS.get(command, OC_ROWS[command])
                if kind != 'success' or code != 0 or _printed(out) != data:
                    report.product.append('%s odbcli %s %s: exit %s, stdout %s, stderr %s, expected the JSON result of %s (service answered %s %s)'
                                          % (label, sub, ARGV_BASE[command], code, out[:100], err[:100], command, kind, rcode))
                else:
                    report.info.append('%s odbcli %s %s conformant: prints the result of %s' % (label, sub, ARGV_BASE[command], command))
                _cli_help(report, main, command)
                _cli_wire(report, main, command)
            if command == FOLDER:
                _cli_listing(report, main)
        except live.LiveUnreachable as exc:
            report.env.append('%s: not executed, production service unreachable: %s' % (OC_ROWS[command], exc))
    report.finish(name)
