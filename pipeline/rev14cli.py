'''Revision 14 client and odbcli checks of the BYTES group (matrix TODO 10.22.6.11; rows CK-BYTE1, CK-BYTE2, OC-BYTE1, OC-BYTE2).

BackupClient.backup_prepare_download (the C-K5 method, named like the command; 10.22.6.11 writes prepare_download) gains the file
address and inline_max_bytes after the positional snapshot_id, file_path; BackupClient.download_chunk(export_id, offset=0,
limit=65536) is new. odbcli prepare documents --snapshot-id --file-path --file-id --site-id --drive-id --dir --name --copy-index
--inline-max-bytes and the new subcommand chunk --export-id --offset --limit prints the command result (flag spelling is a tester
assumption, 10.22.6.11). The wire map is recorded inside this process (pipeline.rev13cli.recorder): an omitted optional parameter
is ABSENT, never null. The C-K5 and O5 assertions of the earlier checks stay. Staged exports are deleted.
'''

from __future__ import annotations

import inspect
import json
import re
from typing import Any

from pipeline import b4base, b4cli, b4client, cmdcases, live
from pipeline.report import Report
from pipeline.rev13cli import recorder
from pipeline.rev14 import file_id

EMPTY = inspect.Parameter.empty
PREPARE = 'backup_prepare_download'
CHUNK = 'backup_download_chunk'
FID = 'abcdef12.' + '0' * 24
SIG_PREPARE: list[tuple[str, Any]] = [('snapshot_id', None), ('file_path', None), ('file_id', None), ('site_id', None), ('drive_id', None),
                                      ('dir', None), ('name', None), ('copy_index', None), ('inline_max_bytes', None)]
SIG_CHUNK: list[tuple[str, Any]] = [('export_id', EMPTY), ('offset', 0), ('limit', 65536)]
FLAGS_PREPARE = ['--snapshot-id', '--file-path', '--file-id', '--site-id', '--drive-id', '--dir', '--name', '--copy-index', '--inline-max-bytes']
FLAGS_CHUNK = ['--export-id', '--offset', '--limit']


def _signature(func: Any) -> list[tuple[str, Any]]:
    '''Return the (name, default) list of a client method without self and timeout.

    Args:
        func: the bound or unbound method.

    Returns:
        The parameter list.
    '''
    return [(p.name, p.default) for p in inspect.signature(func).parameters.values() if p.name not in ('self', 'timeout')]


def _wire(report: Report, label: str, func: Any, command: str, kwargs: dict, allowed: dict) -> None:
    '''Record one client call: exactly one command, the given keys with their values, nothing else except an equal default, no null.

    Args:
        report: the findings collector.
        label: the row label.
        func: the client method.
        command: the expected command.
        kwargs: the arguments given.
        allowed: keys that may also be sent with exactly this value (defaults).

    Returns:
        None.
    '''
    with recorder() as calls:
        _, error = b4client.drive(func, **kwargs)
    sent = calls[0][1] if len(calls) == 1 and calls[0][0] == command else None
    extra = {k: v for k, v in (sent or {}).items() if k not in kwargs and allowed.get(k, object()) != v}
    if sent is None or any(sent.get(k, '<absent>') != v for k, v in kwargs.items()) or extra or None in (sent or {}).values():
        raised = '; raised %s: %s' % (type(error).__name__, str(error)[:100]) if error else ''
        report.product.append('%s wire %s(%s): sent %s, expected exactly %s%s' % (label, getattr(func, '__name__', command), kwargs, calls, kwargs, raised))
    else:
        report.info.append('%s wire %s(%s) conformant' % (label, getattr(func, '__name__', command), kwargs))


def _small(report: Report) -> tuple[str, str] | None:
    '''Return (snapshot id, path) of the smallest file of the newest snapshot (C-K5 baseline), or None after a STATE finding.

    Args:
        report: the findings collector.

    Returns:
        The pair or None.
    '''
    snapshot = cmdcases._first_snapshot()
    entry = cmdcases._smallest_file(snapshot['id']) if snapshot else None
    if entry is None:
        report.state.append('no snapshot with a file to stage')
        return None
    return str(snapshot['id']), str(entry['path'])


def client_prepare(name: str) -> None:
    '''CK-BYTE1 with C-K5: signature, wire map of the address forms, raw negative cases, baseline, unknown snapshot, form A live.

    Args:
        name: the named check.

    Returns:
        None.
    '''
    report = Report()
    module = b4client.load_client(report)
    client = b4client.make_client(module, report) if module is not None else None
    method = getattr(client, PREPARE, None)
    if client is not None and not callable(method):
        report.product.append('C-K5 BackupClient has no method %s' % PREPARE)
    elif client is not None:
        got = _signature(method)
        if got != SIG_PREPARE:
            report.product.append('CK-BYTE1 BackupClient.%s%s, expected %s (10.22.6.11; positional order snapshot_id, file_path kept)' % (PREPARE, got, SIG_PREPARE))
        _wire(report, 'CK-BYTE1', method, PREPARE, {'file_id': FID, 'inline_max_bytes': 65536}, {})
        _wire(report, 'CK-BYTE1', method, PREPARE, {'snapshot_id': 'abcdef12', 'site_id': 'site-1', 'drive_id': 'drive-1', 'dir': 'a', 'name': 'b.txt', 'copy_index': 0}, {})
        _wire(report, 'C-K5', method, PREPARE, {'snapshot_id': 'abcdef12', 'file_path': 'a/b.txt'}, {})
        try:
            for params, violation in (({'file_path': 'x'}, 'missing'), ({'snapshot_id': 'abcdef12', 'zz': 1}, 'unknown')):
                _, exc = b4client.drive(client.raw_call, PREPARE, params)
                if exc is None or b4client.error_code(exc) != -32602 or b4client.violation(exc) != violation:
                    report.product.append('C-K5 raw_call %s(%s): expected -32602 violation=%s, got %s' % (PREPARE, params, violation, exc))
            state = live.service_state()
            pair = _small(report) if state == 'S1' else None
            if pair is not None:
                value, exc = b4client.drive(method, pair[0], file_path=pair[1])
                if exc is not None or not isinstance(value, dict):
                    report.product.append('C-K5 baseline %s(%s, file_path=%s): raised %s' % (PREPARE, pair[0][:8], pair[1][-40:], exc))
                else:
                    live.request('backup_delete_export', {'export_id': value.get('export_id', b4base.ZERO_ID)})
                b4client._unknown_snapshot(report, method, PREPARE, 'M5', state)
                if got == SIG_PREPARE and pair is not None:
                    value, exc = b4client.drive(method, file_id=file_id(pair[0], pair[1]), inline_max_bytes=65536)
                    if exc is not None or not isinstance(value, dict) or value.get('staged') is not False:
                        report.product.append('CK-BYTE1 live %s(file_id, inline_max_bytes=65536): %s, expected the inline result' % (PREPARE, exc or str(value)[:100]))
        except live.LiveUnreachable as exc:
            report.env.append('CK-BYTE1 live cases: production service unreachable: %s' % exc)
    report.finish(name)


def client_chunk(name: str) -> None:
    '''CK-BYTE2: BackupClient.download_chunk(export_id, offset=0, limit=65536), its wire map and the result of the command.

    Args:
        name: the named check.

    Returns:
        None.
    '''
    report = Report()
    module = b4client.load_client(report)
    client = b4client.make_client(module, report) if module is not None else None
    method = getattr(client, 'download_chunk', None)
    if client is not None and not callable(method):
        report.product.append('CK-BYTE2 client/onedrive_backup_client/api.py: BackupClient has no method download_chunk (10.22.4.3, 10.22.6.11; command %s)' % CHUNK)
    elif client is not None:
        got = _signature(method)
        if got != SIG_CHUNK:
            report.product.append('CK-BYTE2 BackupClient.download_chunk%s, expected %s' % (got, SIG_CHUNK))
        _wire(report, 'CK-BYTE2', method, CHUNK, {'export_id': b4base.ZERO_ID}, {'offset': 0, 'limit': 65536})
        _wire(report, 'CK-BYTE2', method, CHUNK, {'export_id': b4base.ZERO_ID, 'offset': 5, 'limit': 10}, {})
        try:
            pair = _small(report) if live.service_state() == 'S1' else None
            kind, _, _, staged = live.request(PREPARE, {'snapshot_id': pair[0], 'file_path': pair[1]}) if pair else ('none', None, '', {})
            if kind == 'success' and isinstance(staged, dict):
                value, exc = b4client.drive(method, staged['export_id'])
                raw, rexc = b4client.drive(client.raw_call, CHUNK, {'export_id': staged['export_id']})
                if exc is not None or value != raw:
                    report.product.append('CK-BYTE2 live download_chunk(export_id): %s, expected the result of %s %s' % (exc or str(value)[:100], CHUNK, rexc or str(raw)[:80]))
                live.request('backup_delete_export', {'export_id': staged['export_id']})
        except live.LiveUnreachable as exc:
            report.env.append('CK-BYTE2 live case: production service unreachable: %s' % exc)
    report.finish(name)


def _help_flags(report: Report, main: Any, sub: str, label: str, flags: list[str]) -> None:
    '''The subcommand --help documents every flag exactly (10.22.6.11).

    Args:
        report: the findings collector.
        main: the odbcli entry function.
        sub: the subcommand.
        label: the row label.
        flags: the flags.

    Returns:
        None.
    '''
    code, out, err = b4cli.run_cli(main, [sub, '--help'])
    missing = [flag for flag in flags if not re.search(r'(?<![\w-])%s(?![\w-])' % re.escape(flag), out + err)]
    if code != 0 or missing:
        report.product.append('%s odbcli %s --help: exit %r, the arguments %s are not documented (10.22.6.11 ODBCLI)' % (label, sub, code, missing))


def _cli_wire(report: Report, main: Any, label: str, argv: list[str], command: str, wanted: dict) -> None:
    '''odbcli maps its arguments to the command keys: exactly the given keys with their values.

    Args:
        report: the findings collector.
        main: the odbcli entry function.
        label: the row label.
        argv: the subcommand and its arguments.
        command: the expected command.
        wanted: the expected parameter map.

    Returns:
        None.
    '''
    with recorder() as calls:
        code, out, err = b4cli.run_cli(main, b4cli.global_args() + argv)
    if [c for c, _ in calls] != [command] or calls[0][1] != wanted:
        report.product.append('%s wire odbcli %s: exit %r, sent %s, expected %s %s; stderr %s' % (label, ' '.join(argv), code, calls, command, wanted, err.strip()[-160:]))
    else:
        report.info.append('%s wire odbcli %s conformant' % (label, ' '.join(argv)))


def odbcli_prepare(name: str) -> None:
    '''OC-BYTE1 with O5: the O5 help, usage, baseline and unknown snapshot cases, the new flags and their wire map.

    Args:
        name: the named check.

    Returns:
        None.
    '''
    report = Report()
    main = b4cli.entry(report)
    if main is not None:
        b4cli._help_names(report, main, 'prepare', 'O5', ['snapshot_id', 'file_path'])
        b4cli._usage_cases(report, main, 'prepare', 'O5', ['id'])
        _help_flags(report, main, 'prepare', 'OC-BYTE1', FLAGS_PREPARE)
        _cli_wire(report, main, 'OC-BYTE1', ['prepare', '--file-id', FID, '--inline-max-bytes', '65536'], PREPARE, {'file_id': FID, 'inline_max_bytes': 65536})
        try:
            state = live.service_state()
            b4cli._baseline(report, main, 'prepare', 'O5', state)
            b4cli._unknown_snapshot(report, main, 'prepare', 'O5', state)
        except live.LiveUnreachable as exc:
            report.env.append('production service unreachable: %s' % exc)
    report.finish(name)


def odbcli_chunk(name: str) -> None:
    '''OC-BYTE2: the subcommand chunk, its help, its wire map and the printed result of backup_download_chunk.

    Args:
        name: the named check.

    Returns:
        None.
    '''
    report = Report()
    main = b4cli.entry(report)
    if main is not None:
        subs = b4cli._subcommands(main)
        if subs is None or 'chunk' not in subs:
            report.product.append('OC-BYTE2 odbcli lists the subcommands %s, expected chunk among them (10.22.6.11 ODBCLI)' % subs)
        else:
            _help_flags(report, main, 'chunk', 'OC-BYTE2', FLAGS_CHUNK)
            _cli_wire(report, main, 'OC-BYTE2', ['chunk', '--export-id', b4base.ZERO_ID, '--offset', '5', '--limit', '10'], CHUNK,
                      {'export_id': b4base.ZERO_ID, 'offset': 5, 'limit': 10})
            try:
                pair = _small(report) if live.service_state() == 'S1' else None
                kind, _, _, staged = live.request(PREPARE, {'snapshot_id': pair[0], 'file_path': pair[1]}) if pair else ('none', None, '', {})
                if kind == 'success' and isinstance(staged, dict):
                    code, out, err = b4cli.run_cli(main, b4cli.global_args() + ['chunk', '--export-id', staged['export_id']])
                    rkind, _, _, data = live.request(CHUNK, {'export_id': staged['export_id']})
                    try:
                        printed = json.loads(out)
                    except ValueError:
                        printed = None
                    if code != 0 or rkind != 'success' or printed != data:
                        report.product.append('OC-BYTE2 odbcli chunk --export-id: exit %r, stdout %s, expected the JSON result of %s' % (code, out[:100], CHUNK))
                    live.request('backup_delete_export', {'export_id': staged['export_id']})
            except live.LiveUnreachable as exc:
                report.env.append('OC-BYTE2 live case: production service unreachable: %s' % exc)
    report.finish(name)
