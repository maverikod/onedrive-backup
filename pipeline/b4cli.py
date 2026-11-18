'''B4 named checks of odbcli: the console command installed with the client and built on it (decision 2).

odbcli contract these checks hold the implementation to (tester reading of matrix rows O1..O15, OS1, OS2):
  client/pyproject.toml [project.scripts] odbcli = <module>:<function>; the function is main(argv=None) -> int.
  global options before the subcommand: --url --ca --cert --key --timeout --login --password --token; each also
  readable from the environment is not required. Subcommands: help [CMDNAME], info [--page N], snapshots [--limit],
  files SNAPSHOT_ID [--prefix --offset --limit], prepare SNAPSHOT_ID [--path], status EXPORT_ID, delete EXPORT_ID,
  sites [--limit --offset --query], libraries SITE_ID [--limit --offset], discovery-status, health,
  fetch EXPORT_ID --output PATH [--force] [--delete-after], download SNAPSHOT_ID --output PATH [--path] [--force]
  [--keep-export], call COMMAND [--params-json JSON], download-link EXPORT_ID, and download-begin EXPORT_ID for the
  command backup_download_begin (the matrix has no O row for it: reported as a gap).
  stdout is JSON; exit 0 on success, 1 on an authentication failure, 2 on a usage error, other non-zero on a server error.
'''

from __future__ import annotations

import contextlib
import importlib
import io
import json
import re
import sys
import tempfile
import tomllib
from pathlib import Path

from pipeline import b4base as base, b4client, cmdcases, live
from pipeline.b4base import NO_CREDS
from pipeline.report import Report

PYPROJECT = 'client/pyproject.toml'
SUBCOMMAND = {'help': 'help', 'info': 'info', 'backup_snapshots': 'snapshots', 'backup_list_files': 'files',
              'backup_prepare_download': 'prepare', 'backup_download_status': 'status', 'backup_delete_export': 'delete',
              'backup_sites_list': 'sites', 'backup_libraries_list': 'libraries', 'backup_discovery_status': 'discovery-status',
              'backup_download_begin': 'download-begin'}
OPTION_ALIAS = {'file_path': ('path',)}
BASELINE = {'help': [], 'info': [], 'snapshots': [], 'files': ['abcdef12'], 'prepare': ['abcdef12'], 'status': [base.ZERO_ID],
            'delete': [base.ZERO_ID], 'sites': [], 'libraries': ['site-1'], 'discovery-status': [], 'health': [],
            'download-link': [base.ZERO_ID]}
NEEDS_S1 = ('snapshots', 'files', 'prepare', 'sites', 'libraries')


def entry(report: Report):
    '''Resolve the odbcli entry function from pyproject.toml; None after a finding.'''
    data = tomllib.loads((base.ROOT / PYPROJECT).read_text(encoding='utf-8'))
    target = data.get('project', {}).get('scripts', {}).get('odbcli')
    if not target:
        report.product.append('%s: [project.scripts] holds %s and no odbcli (decision 2: odbcli is installed with the client)' % (base.src_line(PYPROJECT, 'project.scripts'), sorted(data.get('project', {}).get('scripts', {}))))
        return None
    module_name, _, func = target.partition(':')
    b4client.load_client(Report())
    try:
        return getattr(importlib.import_module(module_name), func)
    except (ImportError, AttributeError) as exc:
        report.product.append('%s: the odbcli entry %s cannot be imported: %s: %s' % (PYPROJECT, target, type(exc).__name__, exc))
        return None


def run_cli(main, argv: list[str]) -> tuple[object, str, str]:
    '''Run odbcli in-process; return (exit code or a crash text, stdout, stderr).'''
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        try:
            code = main(list(argv))
            code = 0 if code is None else code
        except SystemExit as exc:
            code = exc.code if isinstance(exc.code, int) else (0 if exc.code is None else 1)
        except Exception as exc:
            code = 'raised %s: %s' % (type(exc).__name__, exc)
    return code, out.getvalue(), err.getvalue()


def global_args(creds: bool = True, **extra) -> list[str]:
    ca, cert, key = live._tls_files()
    args = ['--url', live.base_url(), '--ca', ca, '--cert', cert, '--key', key, '--timeout', '30']
    if creds and live.token():
        args += ['--token', live.token()]
    for name, value in extra.items():
        args += ['--' + name, value]
    return args


def _usage_cases(report: Report, main, sub: str, label: str, required: list[str]) -> None:
    code, out, err = run_cli(main, global_args() + [sub, '--no-such-option'])
    if code != 2:
        report.product.append('%s odbcli %s --no-such-option: exit %r, expected the usage error 2' % (label, sub, code))
    if required:
        code, out, err = run_cli(main, global_args() + [sub])
        if code != 2:
            report.product.append('%s odbcli %s without its required argument: exit %r, expected the usage error 2' % (label, sub, code))


def _help_names(report: Report, main, sub: str, label: str, names: list[str]) -> None:
    code, out, err = run_cli(main, [sub, '--help'])
    text = (out + err).lower()
    if code != 0:
        report.product.append('%s odbcli %s --help: exit %r, expected 0' % (label, sub, code))
        return
    for name in names:
        forms = [name, name.replace('_', '-')] + list(OPTION_ALIAS.get(name, ()))
        if not any(form.lower() in text for form in forms):
            report.product.append('%s odbcli %s --help does not mention the argument %s (forms %s)' % (label, sub, name, forms))


def _baseline(report: Report, main, sub: str, label: str, state) -> None:
    code, out, err = run_cli(main, global_args() + [sub] + BASELINE.get(sub, []))
    if state is None:
        report.env.append('%s baseline odbcli %s: not executed, production service unreachable' % (label, sub))
    elif code == 0:
        try:
            json.loads(out)
        except ValueError:
            report.product.append('%s baseline odbcli %s: exit 0 but stdout is not JSON: %r' % (label, sub, out[:80]))
        else:
            if sub in ('help', 'health'):
                missing = [name for name in base.live_commands() if name not in out]
                if missing:
                    report.product.append('%s baseline odbcli %s: the JSON output omits the live commands %s' % (label, sub, missing))
    elif state == 'S0' and sub in NEEDS_S1 and '503' in (out + err):
        report.state.append('%s baseline odbcli %s: needs an S1 service but production answers S0 (503)' % (label, sub))
    elif sub in ('status', 'delete', 'download-link') and '404' in (out + err) and code not in (1, 2):
        pass
    else:
        report.product.append('%s baseline odbcli %s: exit %r %s' % (label, sub, code, (out + err).strip()[:120]))


def odbcli_command(row_id: str, sub: str, params: list[str], required: list[str], name: str, command_row: str | None) -> None:
    '''One odbcli_<x> check: entry point, --help names the row parameters, usage errors, one live baseline.'''
    report = Report()
    main = entry(report)
    if main is not None:
        label = row_id
        _help_names(report, main, sub, label, params)
        _usage_cases(report, main, sub, label, required)
        try:
            state = live.service_state()
        except live.LiveUnreachable as exc:
            report.env.append('production service unreachable: %s' % exc)
            state = None
        if sub in BASELINE:
            _baseline(report, main, sub, label, state)
    report.finish(name)


def odbcli_transfer(row_id: str, sub: str, extra: list[str], flags: list[str], name: str) -> None:
    '''odbcli fetch / download: flags, the pre-network refusal of an existing output, and the S1 requirement.'''
    report = Report()
    main = entry(report)
    if main is not None:
        _help_names(report, main, sub, row_id, ['output'] + flags)
        _usage_cases(report, main, sub, row_id, ['id'])
        with tempfile.TemporaryDirectory() as work:
            target = Path(work) / 'existing.bin'
            target.write_bytes(b'keep')
            code, out, err = run_cli(main, global_args() + [sub, base.ZERO_ID if sub == 'fetch' else 'abcdef12', '--output', str(target)])
            if code in (0, None) or target.read_bytes() != b'keep':
                report.product.append('%s odbcli %s onto an existing output without --force: exit %r, expected a refusal and the file untouched' % (row_id, sub, code))
        try:
            state = live.service_state()
        except live.LiveUnreachable as exc:
            report.env.append('production service unreachable: %s' % exc)
            state = None
        if state is not None and state != 'S1':
            report.state.append('%s odbcli %s of a staged export needs an S1 service (host directory, container mount, restic password, login and password, finished inventory) but production answers %s' % (row_id, sub, state))
    report.finish(name)


def odbcli_call() -> None:
    '''O14: odbcli call COMMAND [--params-json JSON] sends any parameter map and reports the server error.'''
    report = Report()
    main = entry(report)
    if main is not None:
        _help_names(report, main, 'call', 'O14', ['command', 'params-json'])
        code, out, err = run_cli(main, global_args() + ['call', 'help', '--params-json', '{}'])
        if code != 0:
            report.product.append('O14 odbcli call help --params-json {}: exit %r %s' % (code, (out + err).strip()[:100]))
        code, out, err = run_cli(main, global_args() + ['call', 'backup_snapshots', '--params-json', '{' + chr(34) + 'no_such_param' + chr(34) + ': 1}'])
        if code in (0, 2) or 'unknown' not in (out + err).lower():
            report.product.append('O14 odbcli call with an unknown parameter: exit %r, expected a server error naming violation unknown, got %r' % (code, (out + err).strip()[:100]))
        code, out, err = run_cli(main, global_args() + ['call', 'help', '--params-json', 'not json'])
        if code != 2:
            report.product.append('O14 odbcli call with malformed --params-json: exit %r, expected the usage error 2' % code)
    report.finish('odbcli_call')


def odbcli_auth() -> None:
    '''OS2: no credentials or a wrong password exit 1; the right login and password exit 0; --token is the alternative.'''
    report = Report()
    main = entry(report)
    if main is not None:
        code, out, err = run_cli(main, global_args(creds=False) + ['help'])
        if code != 1:
            report.product.append('OS2 odbcli help without login or token: exit %r, expected 1 (authentication, matrix C-K0); the server answers anonymous calls (see auth_token)' % code)
        code, out, err = run_cli(main, global_args(creds=False, login='nobody', password='wrong') + ['help'])
        if code != 1:
            report.product.append('OS2 odbcli help with a wrong login and password: exit %r, expected 1' % code)
        if live.token():
            code, out, err = run_cli(main, global_args(creds=True) + ['help'])
            if code != 0:
                report.product.append('OS2 odbcli help with the run credentials: exit %r %s' % (code, (out + err).strip()[:100]))
        else:
            report.state.append('OS2 odbcli with the right login and password: ' + NO_CREDS)
    report.finish('odbcli_auth')


def odbcli_surface() -> None:
    '''OS1: every live server command is an odbcli subcommand with all its arguments (parity against the live help).'''
    report = Report()
    main = entry(report)
    try:
        commands = base.live_commands()
    except live.LiveUnreachable as exc:
        report.env.append('help: not executed, production service unreachable: %s' % exc)
        commands = []
    wanted = sorted(set(commands) | {'backup_download_begin'})
    if main is not None:
        for command in wanted:
            sub = SUBCOMMAND.get(command, command.replace('_', '-'))
            code, out, err = run_cli(main, [sub, '--help'])
            if code != 0:
                report.product.append('OS1 server command %s has no odbcli subcommand %s (exit %r)%s' % (command, sub, code, '' if command in commands else ' - the command itself is not registered yet' ))
                continue
            names = base.command_params(command) if command in commands else []
            _help_names(report, main, sub, 'OS1 ' + command, names)
        code, out, err = run_cli(main, ['health', '--help'])
        if code != 0:
            report.product.append('OS1 odbcli has no health subcommand (O11)')
    report.info.append('gap: the matrix has no O row for odbcli download-begin (command backup_download_begin, decision 2 asks for every server command)')
    report.finish('odbcli_surface')
