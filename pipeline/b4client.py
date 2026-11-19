'''B4 named checks of the Python client: a THIN WRAPPER over the mcp-proxy-adapter JsonRpcClient (decision 1).

Client contract these checks hold the implementation to (the tester reading of matrix rows C-K0..C-K15):
  from onedrive_backup_client import BackupClient, ClientError, ClientAuthenticationError
  BackupClient(url, ca, cert, key, timeout, login=None, password=None, token=None)
  one method per server command, named exactly like the command (help, info, backup_snapshots, ...,
  backup_download_begin), taking the parameters of the matrix row and returning the unpacked result data;
  call(command, params=None) and raw_call(command, params_map) (non-validating send for negative cases);
  fetch(export_id, output, *, overwrite=False, delete_after=False) and download(snapshot_id, output,
  file_path=None, *, overwrite=False, delete_after=True) over the adapter transfer service;
  download_link(export_id) -> the url of the staged export, fetch_link(export_id, output, *, overwrite=False,
  delete_after=False) -> plain-link download with the same size and SHA256 verification;
  ClientError carries .code and .data of the server error; ClientAuthenticationError (a ClientError) is raised on 401.
A method may be a plain function or a coroutine function; both are driven here.
'''

from __future__ import annotations

import ast
import asyncio
import hashlib
import importlib
import inspect
import os
import sys
import tempfile
from pathlib import Path

from pipeline import b4base as base, cmdcases, credentials, live, matrix
from pipeline.b4base import NO_CREDS, PACKAGE_DIR, ROOT
from pipeline.report import Report

OWN_TRANSPORT = ('urllib.request', 'urllib.error', 'http.client', 'ssl', 'socket', 'requests', 'httpx', 'aiohttp')
CTOR = ('url', 'ca', 'cert', 'key', 'timeout', 'login', 'password', 'token')
UNIFIED = 'execute_command_unified'
PKG = 'client/onedrive_backup_client'


def thin_wrapper(report: Report) -> None:
    '''Static findings: the package owns no transport and is built on JsonRpcClient.execute_command_unified.'''
    uses_client = uses_unified = False
    for path in sorted(PACKAGE_DIR.glob('*.py')):
        tree = ast.parse(path.read_text(encoding='utf-8'))
        for node in ast.walk(tree):
            names = []
            if isinstance(node, ast.Import):
                names = [alias.name for alias in node.names]
            elif isinstance(node, ast.ImportFrom):
                names = [(node.module or '') + '.' + alias.name for alias in node.names]
                uses_client = uses_client or ((node.module or '').startswith('mcp_proxy_adapter') and any(a.name == 'JsonRpcClient' for a in node.names))
            elif isinstance(node, ast.Attribute) and node.attr == UNIFIED:
                uses_unified = True
            for name in names:
                if any(name == own or name.startswith(own + '.') for own in OWN_TRANSPORT):
                    report.product.append('%s/%s:%d imports %s: the client owns its own transport, it must be a thin wrapper over mcp_proxy_adapter JsonRpcClient (decision 1)' % (PKG, path.name, node.lineno, name))
    if not uses_client:
        report.product.append('%s: no import of JsonRpcClient from mcp_proxy_adapter.client.jsonrpc_client (decision 1); BackupClient is declared at %s' % (PKG, base.src_line(PKG + '/api.py', 'class BackupClient')))
    if not uses_unified:
        report.product.append('%s: no call of JsonRpcClient.%s (a method per command must be execute_command_unified(command, params))' % (PKG, UNIFIED))


def load_client(report: Report):
    '''Import the client package from the checkout; None after a finding.'''
    if str(base.CLIENT_DIR) not in sys.path:
        sys.path.insert(0, str(base.CLIENT_DIR))
    try:
        module = importlib.import_module('onedrive_backup_client')
        getattr(module, 'BackupClient')
    except (ImportError, AttributeError) as exc:
        report.product.append('%s/__init__.py: cannot use the client contract: %s: %s' % (PKG, type(exc).__name__, exc))
        return None
    for name in ('ClientError', 'ClientAuthenticationError'):
        if not hasattr(module, name):
            report.product.append('%s/__init__.py: the package exports no %s (C-K0: 401 is ClientAuthenticationError)' % (PKG, name))
    return module


def make_client(module, report: Report, creds: bool = True):
    '''Build BackupClient against production with keyword arguments of the contract; None after a finding.'''
    ca, cert, key = live._tls_files()
    kwargs = {'url': live.base_url(), 'ca': ca, 'cert': cert, 'key': key, 'timeout': 30}
    if creds and credentials.token():
        login, password = credentials.load()
        kwargs.update(login=login, password=password)
    params = inspect.signature(module.BackupClient).parameters
    missing = [name for name in CTOR if name not in params]
    if missing:
        report.product.append('%s: BackupClient%s has no parameter %s (C-K0: login, password and token are accepted)' % (base.src_line(PKG + '/api.py', 'def __init__'), '', missing))
        kwargs = {k: v for k, v in kwargs.items() if k in params}
    try:
        return module.BackupClient(**kwargs)
    except Exception as exc:
        report.product.append('BackupClient(%s) failed: %s: %s' % (', '.join(sorted(kwargs)), type(exc).__name__, exc))
        return None


def drive(func, *args, **kwargs):
    '''Call a client method; coroutines are run to completion. Return (value, None) or (None, exception).'''
    try:
        out = func(*args, **kwargs)
        if inspect.isawaitable(out):
            out = asyncio.run(out)
        return out, None
    except Exception as exc:
        return None, exc


def error_code(exc):
    return getattr(exc, 'code', None)


def violation(exc):
    data = getattr(exc, 'data', None)
    return data.get('violation') if isinstance(data, dict) else None


def _state(report: Report):
    try:
        return live.service_state()
    except live.LiveUnreachable as exc:
        report.env.append('production service unreachable: %s' % exc)
        return None


def _row(row_id: str) -> dict:
    return next(item for item in matrix.load()['rows'] if item['id'] == row_id)


def client_cmd(command: str, row_id: str, name: str) -> None:
    '''client_cmd_<command>: the client method of one server command, its signature and its negative cases through raw_call.'''
    report = Report()
    row = _row(row_id)
    module = load_client(report)
    client = make_client(module, report) if module else None
    if client is None:
        report.finish(name)
        return
    method = getattr(client, command, None)
    if not callable(method):
        report.product.append('%s: BackupClient has no method %s (one method per server command, named like the command)' % (base.src_line(PKG + '/api.py', 'class BackupClient'), command))
    else:
        got = sorted(p for p in inspect.signature(method).parameters if p not in ('self', 'timeout'))
        want = sorted(row['params'])
        if got != want:
            report.product.append('%s.%s parameters %s differ from the matrix row %s parameters %s' % ('BackupClient', command, got, row_id, want))
    raw = getattr(client, 'raw_call', None)
    state = _state(report)
    for case in row['cases']:
        cid = case['id']
        if not (cid == 'unknown_param' or cid.startswith('omit_')):
            continue
        label = '%s %s via raw_call' % (row_id, cid)
        if not callable(raw):
            report.product.append('%s: BackupClient has no raw_call(command, params_map) (C-K15)' % label)
            break
        if state is None:
            report.env.append('%s: not executed, production service unreachable' % label)
            continue
        sent = cmdcases.params_for(row, case)
        value, exc = drive(raw, command, sent)
        want_violation = 'unknown' if cid == 'unknown_param' else 'missing'
        if exc is None or error_code(exc) != -32602 or violation(exc) != want_violation:
            report.product.append('%s(%s): expected ClientError code -32602 violation=%s, got %s' % (label, sent, want_violation, 'success %r' % (value,) if exc is None else '%s code=%r violation=%r' % (type(exc).__name__, error_code(exc), violation(exc))))
    if callable(method) and state is not None:
        sent = {k: cmdcases.BASE[k] for k, spec in row['params'].items() if spec['required']}
        for key, finder in (('snapshot_id', base.baseline_snapshot), ('site_id', base.baseline_site)):
            if state == 'S1' and key in sent:
                sent[key] = finder(report, '%s baseline %s' % (row_id, command))
        skipped = any(item is None for item in sent.values())
        value, exc = (None, None) if skipped else drive(method, **sent)
        if skipped:
            pass
        elif exc is None:
            if value is None:
                report.product.append('%s baseline: the method returned None, expected the unpacked result data' % row_id)
            elif command == 'backup_prepare_download' and isinstance(value, dict):
                live.request('backup_delete_export', {'export_id': value.get('export_id', base.ZERO_ID)})
        elif 'export_id' in row['params'] and error_code(exc) == 404 and state in ('S0', 'S1'):
            # R4/R6 and the M6 case S0_unknown_export_404: the zero export id is a well-formed unknown id, answered 404 without the scaffold gate
            if state == 'S0':
                report.state.append('%s baseline success %s(%s): needs a prepared export on an S1 service; S0 answers the matrix case S0_unknown_export_404 (404 %s)' % (row_id, command, sent, str(exc)[:60]))
        elif error_code(exc) == 503 and state == 'S0' and 'export_id' not in row['params']:
            report.state.append('%s baseline %s(%s): needs an S1 service but production answers S0 (503 %s)' % (row_id, command, sent, str(exc)[:80]))
        else:
            report.product.append('%s baseline %s(%s): raised %s code=%r %s' % (row_id, command, sent, type(exc).__name__, error_code(exc), str(exc)[:100]))
        if callable(method) and row_id in ('M4', 'M5'):
            _unknown_snapshot(report, method, command, row_id, state)
    report.finish(name)


def _unknown_snapshot(report: Report, method, command: str, row_id: str, state) -> None:
    '''Case snapshot_id_unknown of rows C-K4 and C-K5 (revision 6, section 10.13): files of a well-formed unknown snapshot returns the M4 object
    {snapshot_id, items: [], total: 0, offset: 0, limit: 1000}; prepare raises ClientError 404 Snapshot not found. It needs no snapshot, only state S1.'''
    if state != 'S1':
        report.state.append('%s snapshot_id_unknown %s needs an S1 service but production answers %s' % (row_id, command, state))
        return
    snapshot_id = base.unknown_snapshot_id()
    value, exc = drive(method, snapshot_id=snapshot_id)
    if command == 'backup_list_files':
        problems = base.unknown_files_problems(value, snapshot_id) if exc is None else ['raised %s code=%r %s, expected the result object' % (type(exc).__name__, error_code(exc), str(exc)[:100])]
    else:
        if exc is None and isinstance(value, dict):
            live.request('backup_delete_export', {'export_id': value.get('export_id', base.ZERO_ID)})
        wanted = exc is not None and error_code(exc) == 404 and 'snapshot not found' in str(exc).lower()
        problems = [] if wanted else ['returned %r, expected ClientError code 404 Snapshot not found' % (value,) if exc is None else 'raised %s code=%r %s, expected ClientError code 404 Snapshot not found' % (type(exc).__name__, error_code(exc), str(exc)[:100])]
    for problem in problems:
        report.product.append('%s snapshot_id_unknown %s(%s): %s (revision 6)' % (row_id, command, snapshot_id, problem))
    if not problems:
        report.info.append('%s snapshot_id_unknown conformant: %s of the unknown snapshot %s' % (row_id, command, snapshot_id))


def client_auth() -> None:
    '''C-K0: constructor with login/password/token; 401 is ClientAuthenticationError; the thin-wrapper contract.'''
    report = Report()
    thin_wrapper(report)
    module = load_client(report)
    if module:
        bare = make_client(module, report, creds=False)
        if bare is not None and _state(report) is not None:
            value, exc = drive(getattr(bare, 'help', lambda: (_ for _ in ()).throw(AttributeError('no help method'))))
            if exc is None:
                report.product.append('C-K0 client without login or token: help succeeded, expected ClientAuthenticationError on 401 (the server does not enforce the token yet, see auth_token)')
            elif not isinstance(exc, getattr(module, 'ClientAuthenticationError', ())):
                report.product.append('C-K0 client without login or token: raised %s, expected ClientAuthenticationError' % type(exc).__name__)
        if live.token():
            good = make_client(module, report, creds=True)
            if good is not None:
                value, exc = drive(getattr(good, 'help', None) or (lambda: (_ for _ in ()).throw(AttributeError('no help method'))))
                if exc is not None:
                    report.product.append('C-K0 client with the run credentials: help raised %s: %s' % (type(exc).__name__, str(exc)[:120]))
        else:
            report.state.append('C-K0 the client with login and password executes a command: ' + NO_CREDS)
    report.finish('client_auth')


def client_call_raw() -> None:
    '''C-K14/C-K15: call(command, params) and the non-validating raw_call for negative cases.'''
    report = Report()
    thin_wrapper(report)
    module = load_client(report)
    client = make_client(module, report) if module else None
    if client is not None and _state(report) is not None:
        for need in ('call', 'raw_call'):
            if not callable(getattr(client, need, None)):
                report.product.append('BackupClient has no %s method (C-K14/C-K15)' % need)
        if callable(getattr(client, 'call', None)):
            value, exc = drive(client.call, 'help')
            if exc is not None or not value:
                report.product.append('C-K14 call(help): expected the help data, got %s' % (exc or value))
            value, exc = drive(client.call, 'no_such_command')
            if exc is None or error_code(exc) not in (-32601, 404):
                report.product.append('C-K14 call(no_such_command): expected ClientError for an unregistered command, got %s' % (exc or value))
        if callable(getattr(client, 'raw_call', None)):
            for params, want in (({'cmdname': 5}, 'type'), ({'no_such_param': 1}, 'unknown')):
                value, exc = drive(client.raw_call, 'help', params)
                if exc is None or error_code(exc) != -32602 or violation(exc) != want:
                    report.product.append('C-K15 raw_call(help, %s): expected ClientError -32602 violation=%s, got %s' % (params, want, exc or value))
    report.finish('client_call_raw')


def client_fetch_integrity() -> None:
    '''C-K12/R9: fetch refuses an existing output before any network call; size and SHA256 are verified before the atomic replace.'''
    report = Report()
    thin_wrapper(report)
    module = load_client(report)
    if module:
        params = inspect.signature(module.BackupClient.fetch).parameters if hasattr(module.BackupClient, 'fetch') else {}
        for need in ('export_id', 'output', 'overwrite', 'delete_after'):
            if need not in params:
                report.product.append('%s: BackupClient.fetch has no parameter %s (C-K12)' % (base.src_line(PKG + '/api.py', 'def fetch'), need))
        try:
            bogus = module.BackupClient(**{k: v for k, v in dict(url=live.base_url(), ca=live._tls_files()[0], cert=live._tls_files()[1], key=live._tls_files()[2], timeout=1).items() if k in inspect.signature(module.BackupClient).parameters})
        except Exception as exc:
            report.product.append('R9 BackupClient cannot be built offline for the pre-network check: %s: %s' % (type(exc).__name__, exc))
            report.finish('client_fetch_integrity')
            return
        with tempfile.TemporaryDirectory() as work:
            target = Path(work) / 'existing.bin'
            target.write_bytes(b'keep')
            value, exc = drive(bogus.fetch, '0' * 32, str(target))
            if exc is None or not isinstance(exc, getattr(module, 'ClientError', Exception)) or target.read_bytes() != b'keep':
                report.product.append('R9 fetch onto an existing output without overwrite: expected ClientError before any network call and the file untouched, got %s' % (exc or value))
        state = _state(report)
        if state == 'S1':
            report.state.append('C-K12 tampered size and SHA256 are RED on the client side: the S1 integrity case has no executor until an S1 service exists')
        elif state is not None:
            report.state.append('C-K12 verification of size and SHA256 before os.replace needs a staged export (S1) but production answers %s' % state)
    report.finish('client_fetch_integrity')


def _s1_or_state(report: Report, what: str) -> bool:
    state = _state(report)
    if state == 'S1':
        return True
    if state is not None:
        report.state.append('%s needs an S1 service (host directory, container mount, restic password, login and password, finished inventory) but production answers %s' % (what, state))
    return False


def client_download() -> None:
    '''C-K13 method 2: download(snapshot_id, output, file_path, overwrite, delete_after) through the adapter transfer service.'''
    report = Report()
    thin_wrapper(report)
    module = load_client(report)
    if module:
        params = inspect.signature(module.BackupClient.download).parameters if hasattr(module.BackupClient, 'download') else {}
        for need in ('snapshot_id', 'output', 'file_path', 'overwrite', 'delete_after'):
            if need not in params:
                report.product.append('%s: BackupClient.download has no parameter %s (C-K13)' % (base.src_line(PKG + '/api.py', 'def download'), need))
        try:
            names = base.live_commands()
        except live.LiveUnreachable as exc:
            report.env.append('help: not executed, production service unreachable: %s' % exc)
            names = None
        if names is not None and 'backup_download_begin' not in names:
            report.product.append('C-K13 the download goes prepare -> backup_download_begin -> JsonRpcClient.download_file, but help lists no backup_download_begin: %s' % names)
        if _s1_or_state(report, 'C-K13 download by transfer'):
            client = make_client(module, report)
            made = cmdcases._prepare_small(report, 'client_download')
            if client is not None and made:
                snapshot_id, path, meta = made
                live.request('backup_delete_export', {'export_id': meta['export_id']})
                with tempfile.TemporaryDirectory() as work:
                    out = Path(work) / 'got.bin'
                    value, exc = drive(client.download, snapshot_id, str(out), path)
                    data = out.read_bytes() if out.exists() else b''
                    if exc is not None or hashlib.sha256(data).hexdigest() != meta['sha256'] or len(data) != meta['size_bytes']:
                        report.product.append('C-K13 download(%s, %s): %s, size %d sha %s, expected size %s sha %s' % (snapshot_id, path, exc or 'ok', len(data), hashlib.sha256(data).hexdigest()[:12], meta['size_bytes'], meta['sha256'][:12]))
    report.finish('client_download')


def client_download_link() -> None:
    '''C-K13 method 1: download_link(export_id) and fetch_link(...) over the plain /downloads link, verified.'''
    report = Report()
    thin_wrapper(report)
    module = load_client(report)
    if module:
        for need in ('download_link', 'fetch_link'):
            if not hasattr(module.BackupClient, need):
                report.product.append('%s: BackupClient has no %s (C-K13, method 1 of decision 3)' % (base.src_line(PKG + '/api.py', 'class BackupClient'), need))
        if _s1_or_state(report, 'C-K13 download by the temporary link'):
            client = make_client(module, report)
            made = cmdcases._prepare_small(report, 'client_download_link')
            if client is not None and made and hasattr(client, 'fetch_link'):
                snapshot_id, path, meta = made
                with tempfile.TemporaryDirectory() as work:
                    out = Path(work) / 'got.bin'
                    value, exc = drive(client.fetch_link, meta['export_id'], str(out), delete_after=True)
                    data = out.read_bytes() if out.exists() else b''
                    if exc is not None or hashlib.sha256(data).hexdigest() != meta['sha256']:
                        report.product.append('C-K13 fetch_link(%s): %s, expected sha %s' % (meta['export_id'], exc or 'sha mismatch', meta['sha256'][:12]))
    report.finish('client_download_link')


def client_download_transfer() -> None:
    '''M11: backup_download_begin registers one transfer session of a staged export (checksum equals the export metadata).'''
    report = Report()
    thin_wrapper(report)
    try:
        names = base.live_commands()
    except live.LiveUnreachable as exc:
        report.env.append('help: not executed, production service unreachable: %s' % exc)
        names = None
    if names is not None and 'backup_download_begin' not in names:
        report.product.append('M11 help lists %s: backup_download_begin is not registered' % names)
    if _s1_or_state(report, 'M11 transfer session of a staged export'):
        made = cmdcases._prepare_small(report, 'client_download_transfer')
        if made:
            kind, code, message, data = live.request('backup_download_begin', {'export_id': made[2]['export_id']})
            ok = kind == 'success' and isinstance(data, dict) and data.get('checksum_value') == made[2]['sha256'] and data.get('compression') == 'identity' and data.get('checksum_algorithm') == 'sha256'
            if not ok:
                report.product.append('M11 backup_download_begin: expected sha256 identity session with checksum equal to the metadata, got %s' % (data if kind == 'success' else (kind, code, message)))
            live.request('backup_delete_export', {'export_id': made[2]['export_id']})
    report.finish('client_download_transfer')
