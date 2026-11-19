'''B4 named checks of odbcli: the console command installed with the client and built on it (decision 2).

odbcli contract these checks hold the implementation to (tester reading of matrix rows O1..O15, OS1, OS2):
  client/pyproject.toml [project.scripts] odbcli = <module>:<function>; the function is main(argv=None) -> int.
  global options before the subcommand: --url --ca --cert --key --timeout --login --password --token; each also
  readable from the environment is not required. Subcommands: help [CMDNAME], info [--page N], snapshots [--limit],
  files SNAPSHOT_ID [--prefix --offset --limit], prepare SNAPSHOT_ID [--path], status EXPORT_ID, delete EXPORT_ID,
  sites [--limit --offset --query], libraries SITE_ID [--limit --offset], discovery-status, health,
  fetch EXPORT_ID --output PATH [--force] [--delete-after], download SNAPSHOT_ID --output PATH [--path] [--force]
  [--keep-export], call COMMAND [--params-json JSON], download-link EXPORT_ID, and download-begin EXPORT_ID for the
  command backup_download_begin (row O16, revision 4).
  stdout is JSON; exit 0 on success, 1 on a server error or an authentication failure (rows O6, O7, O15, O16), 2 on a usage error.
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

from pipeline import b4base as base, b4client, cmdcases, credentials, live
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
ODBCLI_ONLY = ('health', 'fetch', 'download', 'call', 'download-link')
BEGIN_KEYS = ('transfer_id', 'filename', 'size_bytes', 'checksum_algorithm', 'checksum_value', 'compression', 'expires_at', 'transport')
BAD_IDS = (('uppercase hex', 'ABCDEF01' * 4), ('31 characters', '0' * 31), ('33 characters', '0' * 33), ('empty', ''),
           ('non-hex', 'g' * 32))


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


def _baseline_args(report: Report, sub: str, label: str, state) -> list[str] | None:
    '''Files and prepare on an S1 service take the newest catalog snapshot (rows M4, M5, O4, O5) and libraries a site of the inventory (row M9;
    the id site-1 is the unknown site of the case site_id_invalid_3, 404 SITE_NOT_FOUND); None after a STATE finding when there is none.'''
    if sub in ('files', 'prepare') and state == 'S1':
        snapshot = base.baseline_snapshot(report, '%s baseline odbcli %s' % (label, sub))
        return None if snapshot is None else [snapshot]
    if sub == 'libraries' and state == 'S1':
        site = base.baseline_site(report, '%s baseline odbcli %s' % (label, sub))
        return None if site is None else [site]
    return BASELINE.get(sub, [])


def _unknown_snapshot(report: Report, main, sub: str, label: str, state) -> None:
    '''Case snapshot_id_unknown of rows O4 and O5 (revision 6, section 10.13): files of a well-formed unknown snapshot exit 0 with the JSON of M4
    ({snapshot_id, items: [], total: 0, offset: 0, limit: 1000}); prepare exits 1 with the 404 on stderr. It needs no snapshot, only state S1.'''
    if state is None:
        return
    if state != 'S1':
        report.state.append('%s snapshot_id_unknown odbcli %s needs an S1 service but production answers %s' % (label, sub, state))
        return
    snapshot_id = base.unknown_snapshot_id()
    code, out, err = run_cli(main, global_args() + [sub, snapshot_id])
    if sub == 'prepare':
        if code == 0:
            try:
                live.request('backup_delete_export', {'export_id': json.loads(out).get('export_id', base.ZERO_ID)})
            except (ValueError, AttributeError):
                pass
        problems = [] if code == 1 and '404' in err else ['exit %r stderr %r, expected exit 1 and a stderr naming 404' % (code, err.strip()[:100])]
    else:
        try:
            data = json.loads(out)
        except ValueError:
            data = None
        problems = base.unknown_files_problems(data, snapshot_id) if code == 0 else ['exit %r %s, expected exit 0 and the JSON of M4' % (code, (out + err).strip()[:100])]
    for problem in problems:
        report.product.append('%s snapshot_id_unknown odbcli %s %s: %s (revision 6)' % (label, sub, snapshot_id, problem))
    if not problems:
        report.info.append('%s snapshot_id_unknown conformant: odbcli %s of the unknown snapshot %s' % (label, sub, snapshot_id))


def _baseline(report: Report, main, sub: str, label: str, state) -> None:
    args = _baseline_args(report, sub, label, state)
    if args is None:
        return
    code, out, err = run_cli(main, global_args() + [sub] + args)
    if state is None:
        report.env.append('%s baseline odbcli %s: not executed, production service unreachable' % (label, sub))
    elif code == 0:
        try:
            data = json.loads(out)
        except ValueError:
            report.product.append('%s baseline odbcli %s: exit 0 but stdout is not JSON: %r' % (label, sub, out[:80]))
        else:
            if sub == 'prepare' and isinstance(data, dict):
                live.request('backup_delete_export', {'export_id': data.get('export_id', base.ZERO_ID)})
            if sub in ('help', 'health'):
                missing = [name for name in base.live_commands() if name not in out]
                if missing:
                    report.product.append('%s baseline odbcli %s: the JSON output omits the live commands %s' % (label, sub, missing))
    elif state == 'S0' and sub in NEEDS_S1 and '503' in (out + err):
        report.state.append('%s baseline odbcli %s: needs an S1 service but production answers S0 (503)' % (label, sub))
    elif sub in ('status', 'delete', 'download-link') and state in ('S0', 'S1') and code == 1 and '404' in err:
        # rows O6, O7, O15: exit 1 and stderr text for a server error; R6 and the M6 case S0_unknown_export_404: the zero id is a well-formed unknown id, 404
        if state == 'S0':
            report.state.append('%s baseline odbcli %s: the success baseline needs a prepared export on an S1 service; S0 answers the matrix case S0_unknown_export_404 (exit 1, 404)' % (label, sub))
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
        if sub in ('files', 'prepare'):
            _unknown_snapshot(report, main, sub, label, state)
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


def _subcommands(main) -> list[str] | None:
    '''Return the subcommand names odbcli lists in its own help, or None when it lists none.'''
    code, out, err = run_cli(main, ['--help'])
    found = re.search(r'[{]([a-z0-9_,-]+)[}]', out + err)
    return sorted(found.group(1).split(',')) if found else None


def odbcli_surface() -> None:
    '''OS1 (revision 4, 10.1): the odbcli subcommands cover EVERY live server command (11) with all arguments; a live command without a subcommand, or a subcommand with no live command other than the odbcli-only O11-O15, is RED.'''
    report = Report()
    main = entry(report)
    try:
        commands = base.live_commands()
    except live.LiveUnreachable as exc:
        report.env.append('help: not executed, production service unreachable: %s' % exc)
        commands = []
    if commands and commands != sorted(base.COMMANDS):
        report.product.append('OS1 the live help lists %d commands %s, expected exactly the 11 commands of rows M1..M11 %s' % (len(commands), commands, sorted(base.COMMANDS)))
    wanted = {command: SUBCOMMAND.get(command, command.replace('_', '-')) for command in commands}
    if main is not None:
        listed = _subcommands(main)
        if listed is None:
            report.product.append('OS1 odbcli --help does not list its subcommands, so the parity with the live commands cannot be established')
        else:
            missing = sorted(set(wanted.values()) - set(listed))
            extra = sorted(set(listed) - set(wanted.values()) - set(ODBCLI_ONLY))
            if missing:
                report.product.append('OS1 live server commands without an odbcli subcommand: %s' % missing)
            if extra:
                report.product.append('OS1 odbcli subcommands with no live server command (only the odbcli-only O11-O15 %s are allowed): %s' % (list(ODBCLI_ONLY), extra))
        for command, sub in wanted.items():
            code, out, err = run_cli(main, [sub, '--help'])
            if code != 0:
                report.product.append('OS1 server command %s: odbcli %s --help exit %r, expected 0' % (command, sub, code))
                continue
            _help_names(report, main, sub, 'OS1 ' + command, base.command_params(command))
        for sub in ODBCLI_ONLY:
            code, out, err = run_cli(main, [sub, '--help'])
            if code != 0:
                report.product.append('OS1 odbcli-only subcommand %s: --help exit %r, expected 0 (rows O11-O15)' % (sub, code))
    report.finish('odbcli_surface')


def _no_secret(report: Report, label: str, out: str, err: str) -> None:
    '''Neither the login, the password nor the token appears in stdout or stderr (O16 contract; the values are never printed).'''
    if any(secret and (secret in out or secret in err) for secret in credentials.secret_values()):
        report.product.append('%s: the login, the password or the token appears in stdout or stderr (forbidden in every case)' % label)


def _begin_success(report: Report, main) -> None:
    '''O16 success on an S1 service: one JSON object of the M11 shape, exit 0, empty stderr, the export itself is kept.'''
    made = cmdcases._prepare_small(report, 'odbcli_download_begin')
    if not made:
        return
    snapshot_id, path, meta = made
    export_id = meta.get('export_id', base.ZERO_ID)
    try:
        code, out, err = run_cli(main, global_args() + ['download-begin', export_id])
        _no_secret(report, 'O16 baseline', out, err)
        if code != 0 or err.strip():
            report.product.append('O16 baseline odbcli download-begin: exit %r stderr %r, expected exit 0 and an empty stderr' % (code, err.strip()[:100]))
            return
        try:
            data = json.loads(out)
        except ValueError:
            report.product.append('O16 baseline: stdout is not exactly one JSON object: %r' % out[:80])
            return
        missing = [key for key in BEGIN_KEYS if key not in data] if isinstance(data, dict) else list(BEGIN_KEYS)
        if missing:
            report.product.append('O16 baseline: the JSON object lacks %s of the M11 result' % missing)
            return
        if data['checksum_algorithm'] != 'sha256' or data['checksum_value'] != meta.get('sha256') or data['compression'] != 'identity':
            report.product.append('O16 baseline: checksum_algorithm %r checksum_value %r compression %r differ from sha256, the export sha256 and identity' % (data['checksum_algorithm'], data['checksum_value'], data['compression']))
        if data['size_bytes'] != meta.get('size_bytes') or data['filename'] != meta.get('filename') or not isinstance(data['transport'], dict) or data['transport'].get('chunk_method') != 'GET':
            report.product.append('O16 baseline: size_bytes, filename or transport.chunk_method differ from the export metadata and GET')
        kind, code2, message, status_data = live.request('backup_download_status', {'export_id': export_id})
        if kind != 'success':
            report.product.append('O16 baseline: the export was deleted or broken by download-begin (status answers %s %s)' % (kind, code2))
    finally:
        live.request('backup_delete_export', {'export_id': export_id})


def odbcli_download_begin() -> None:
    '''O16 (revision 4, 10.1): odbcli download-begin EXPORT_ID for the command backup_download_begin (M11); argparse 2, server refusal 1, success one JSON object, no secret printed.'''
    report = Report()
    main = entry(report)
    if main is not None:
        _help_names(report, main, 'download-begin', 'O16', ['export_id'])
        _usage_cases(report, main, 'download-begin', 'O16', ['id'])
        code, out, err = run_cli(main, global_args() + ['download-begin', base.ZERO_ID, 'extra-argument'])
        if code != 2:
            report.product.append('O16 odbcli download-begin with a second positional argument: exit %r, expected the usage error 2' % code)
        for label, value in BAD_IDS:
            code, out, err = run_cli(main, global_args() + ['download-begin', value])
            _no_secret(report, 'O16 %s' % label, out, err)
            if code != 1 or out.strip() or not (err.strip() and ('400' in err or '32602' in err)):
                report.product.append('O16 odbcli download-begin %s: exit %r stdout %r stderr %r, expected exit 1, empty stdout and a stderr naming the refusal 400 or -32602' % (label, code, out.strip()[:40], err.strip()[:100]))
        try:
            state = live.service_state()
        except live.LiveUnreachable as exc:
            report.env.append('production service unreachable: %s' % exc)
            state = None
        code, out, err = run_cli(main, global_args() + ['download-begin', base.ZERO_ID])
        _no_secret(report, 'O16 unknown export', out, err)
        # O16 unknown_export (revision 4b, 10.10): a well-formed unknown id is 404 in S0 and in S1; R6, the S0 gate is not consulted
        if state is not None and (code != 1 or out.strip() or '404' not in err):
            report.product.append('O16 odbcli download-begin of an unknown export on an %s service: exit %r stdout %r stderr %r, expected exit 1, empty stdout and 404' % (state, code, out.strip()[:40], err.strip()[:100]))
        if state == 'S1':
            _begin_success(report, main)
        elif state is not None:
            report.state.append('O16 baseline odbcli download-begin of a prepared export needs an S1 service (host directory, container mount, restic password, login and password, finished inventory) but production answers %s' % state)
    report.finish('odbcli_download_begin')