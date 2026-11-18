'''B4 named checks of the server side: REST removal, authentication, routes, download link, transfer, mTLS.

Every check talks to the production service named in pipeline/endpoints.env over mTLS. Findings are kept apart:
PRODUCT (the deployed service or its code breaks the contract), STATE (the case needs state or credentials the
owner has not provisioned) and ENVIRONMENT (the pipeline cannot reach the service).
'''

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import socket
import ssl
import subprocess
import tempfile
import urllib.parse

from pipeline import b4base as base, cmdcases, live
from pipeline.b4base import JSON_HEADERS, NO_CREDS, ZERO_ID, Q
from pipeline.environment import PipelineEnvError, endpoint
from pipeline.report import Report

SERVER = 'src/onedrive_api/server.py'
REST = (
    ('H1', 'GET', '/api/v1/health', None), ('H2', 'GET', '/api/v1/discovery/status', None),
    ('H3', 'GET', '/api/v1/sites', None), ('H4', 'GET', '/api/v1/sites/{site_id}/libraries', None),
    ('H5', 'GET', '/api/v1/snapshots', None), ('H6', 'GET', '/api/v1/snapshots/{snapshot_id}/files', None),
    ('H7', 'POST', '/api/v1/exports', b'{"snapshot_id": "abcdef12"}'),
    ('H8', 'GET', '/api/v1/exports/{export_id}', None), ('H9', 'GET', '/api/v1/exports/{export_id}/status', None),
    ('H10', 'DELETE', '/api/v1/exports/{export_id}', None),
)
FILL = {'site_id': 'site-1', 'snapshot_id': 'abcdef12', 'export_id': ZERO_ID}
COMMANDS = base.COMMANDS
UPGRADE = {'Connection': 'Upgrade', 'Upgrade': 'websocket', 'Sec-WebSocket-Version': '13',
           'Sec-WebSocket-Key': 'dGhlIHNhbXBsZSBub25jZQ=='}
URL_RE = re.compile('^/downloads/[0-9a-f]{32}/[^/]+$')


def _fill(path: str) -> str:
    for key, value in FILL.items():
        path = path.replace('{%s}' % key, value)
    return path


def _try(report: Report, label: str, func, *args, **kwargs):
    '''Run one live step; an unreachable service becomes an ENVIRONMENT finding and None is returned.'''
    try:
        return func(*args, **kwargs)
    except live.LiveUnreachable as exc:
        report.env.append('%s: not executed, production service unreachable: %s' % (label, exc))
        return None


def _gated(report: Report, label: str, status: int, auth: bool) -> bool:
    '''True (and a STATE finding) when 401 is the token gate and the run has no credentials to pass it.'''
    if status == 401 and not (auth and live.token()):
        report.state.append('%s: answered 401 and %s, so the case cannot see past the token gate' % (label, base.NO_CREDS))
        return True
    return False


def rest_removed() -> None:
    '''H1..H10: every /api/v1/* route answers 404 (decision 4, D2); downloads are /downloads and the adapter transfer.'''
    report = Report()
    for row, method, template, body in REST:
        path = _fill(template)
        label = '%s %s %s' % (row, method, path)
        got = _try(report, label, base.probe, method, path, body, JSON_HEADERS if body else None)
        if got is None or _gated(report, label, got[0], True):
            continue
        if got[0] != 404 or got[2].strip() != base.FRAMEWORK_404:
            needle = '@app.%s(%s%s%s)' % (method.lower(), Q, template, Q)
            report.product.append('%s: answered %d %s, expected the framework 404 {detail: Not Found} (REST is removed, decision D2); still registered at %s'
                                  % (label, got[0], base.brief(got[2]), base.src_line(SERVER, needle)))
    report.info.append('%d REST routes probed' % len(REST))
    report.finish('rest_removed')


def _ws_cases(report: Report, prefix: str) -> None:
    '''F10 (revision 4, 10.2): exact statuses and no tolerance.

    Plain GET /ws answers 404 with the run token and 401 without it (the token gate of AU1). A WebSocket Upgrade handshake
    answers 403 with and without the token (refused by the ASGI server itself), never 101: no handshake completes.
    '''
    for label, headers in (('GET /ws', {}), ('GET /ws with a WebSocket Upgrade handshake', UPGRADE)):
        for auth in (False, True):
            tag = '%s %s %s' % (prefix, label, 'with token' if auth else 'without token')
            if auth and not live.token():
                report.state.append('%s: needs the token T: %s' % (tag, NO_CREDS))
                continue
            wanted = 403 if headers is UPGRADE else (404 if auth else 401)
            got = _try(report, tag, base.probe, 'GET', '/ws', None, headers, auth)
            if got is not None and got[0] != wanted:
                report.product.append('%s: answered %d %s, expected exactly %d (the /ws route stays closed, F10; never 101)'
                                      % (tag, got[0], base.brief(got[2]), wanted))


def ws_closed() -> None:
    '''F10: /ws stays closed (decision 6, adapter bug c0438b53): plain GET 404 with the token and 401 without it, the Upgrade handshake 403 with and without the token, never 101.'''
    report = Report()
    _ws_cases(report, 'F10')
    report.finish('ws_closed')


def _openapi(report: Report):
    got = _try(report, 'F5 GET /openapi.json', base.probe, 'GET', '/openapi.json')
    if got is None:
        return None
    if got[0] != 200:
        report.product.append('F5 GET /openapi.json: answered %d %s, expected 200 with the route schema (live HTTP route proof for F8, F9, F11)'
                              % (got[0], base.brief(got[2])))
        return None
    try:
        return sorted(json.loads(got[2]).get('paths', {}))
    except ValueError:
        report.product.append('F5 GET /openapi.json: body is not JSON')
        return None


def surface_framework_routes() -> None:
    '''F1..F11: framework routes of the adapter plus the returned download routes; /ws, uploads and REST stay closed.'''
    report = Report()

    def expect(label, method, path, statuses, body=None, headers=None):
        got = _try(report, label, base.probe, method, path, body, headers)
        if got is None or _gated(report, label, got[0], True):
            return None
        if got[0] not in statuses:
            report.product.append('%s: answered %d %s, expected %s' % (label, got[0], base.brief(got[2]), ' or '.join(map(str, statuses))))
            return None
        return got
    one = json.dumps({'jsonrpc': '2.0', 'method': 'help', 'params': {}, 'id': 1}).encode('utf-8')
    expect('F1 POST /api/jsonrpc', 'POST', '/api/jsonrpc', (200,), one, JSON_HEADERS)
    expect('F2 POST /api/jsonrpc/batch', 'POST', '/api/jsonrpc/batch', (200,), b'[' + one + b']', JSON_HEADERS)
    got = expect('F3 GET /health', 'GET', '/health', (200,))
    if got is not None and json.loads(got[2]).get('version') != base.version():
        report.product.append('F3 GET /health: version %r differs from VERSION %r (decision 7)' % (json.loads(got[2]).get('version'), base.version()))
    got = expect('F4 GET /commands', 'GET', '/commands', (200,))
    if got is not None:
        names = sorted(json.loads(got[2]).get('commands', {}))
        if names != sorted(COMMANDS):
            report.product.append('F4 GET /commands: lists %s, expected exactly the 11 commands of rows M1..M11, missing %s, unexpected %s'
                                  % (len(names), sorted(set(COMMANDS) - set(names)), sorted(set(names) - set(COMMANDS))))
    expect('F6 GET /docs', 'GET', '/docs', (200,))
    expect('F7 GET /redoc', 'GET', '/redoc', (200,))
    paths = _openapi(report)
    if paths is not None:
        for row, wanted in (('F8', '/downloads/{file_id}/{filename}'), ('F9', '/api/transfer/downloads')):
            if not any(p == wanted or p.startswith(wanted) for p in paths):
                report.product.append('%s: the route schema has no %s (decision 3: the download routes are returned to the filter at %s)'
                                      % (row, wanted, base.src_line(SERVER, 'allowed')))
        for row, forbidden in (('F10', '/ws'), ('F11', '/api/transfer/uploads'), ('H1-H10', '/api/v1')):
            found = [p for p in paths if p.startswith(forbidden)]
            if found:
                report.product.append('%s: the route schema still holds %s' % (row, found))
    else:
        report.info.append('F8, F9: route presence is not provable without /openapi.json (F5 is RED); the behaviour of both routes is asserted by download_link and transfer_confinement')
    _ws_cases(report, 'F10')
    for label, method, path in (('F11 GET /api/transfer/uploads', 'GET', '/api/transfer/uploads'),
                                ('F11 POST /api/transfer/uploads', 'POST', '/api/transfer/uploads')):
        expect(label, method, path, (404,), b'{}' if method == 'POST' else None, JSON_HEADERS if method == 'POST' else None)
    report.finish('surface_framework_routes')


def _proxy_identity() -> tuple[str, str]:
    '''Return the MCP Proxy host name from endpoints.env and its address from DNS (the name when DNS cannot resolve it).'''
    try:
        host = urllib.parse.urlsplit(endpoint('MCP_PROXY_URL')).hostname or ''
    except PipelineEnvError:
        host = ''
    try:
        return host, socket.gethostbyname(host)
    except OSError:
        return host, host


def spoof_header_sets() -> list[tuple[str, dict]]:
    '''Request headers that name the MCP Proxy; a direct peer carrying them gains nothing (R18: transport peer only).'''
    name, address = _proxy_identity()
    single = (('X-Forwarded-For', {'X-Forwarded-For': address}), ('Forwarded', {'Forwarded': 'for=%s;host=%s' % (address, name)}),
              ('X-Real-IP', {'X-Real-IP': address}), ('Host', {'Host': name}))
    merged: dict = {}
    for _, headers in single:
        merged.update(headers)
    return list(single) + [('all four', merged)]


def _unauthorized(status: int, decoded) -> bool:
    error = decoded.get('error') if isinstance(decoded, dict) else None
    return status == 401 and isinstance(error, dict) and error.get('code') == 401 and error.get('type') == 'authentication_error'


def auth_token() -> None:
    '''AU1..AU3, scope = the DIRECT peer (R18): no token, an empty token, spoofed proxy headers and a wrong token answer 401; the right token T runs the command.'''
    report = Report()
    cfg = base.src_line('config/server.json', 'use_token')
    denied = [('AU1 no token', None, None), ('AU1 empty X-API-Key value', '', None)]
    denied += [('AU1 no token and spoofed %s' % label, None, headers) for label, headers in spoof_header_sets()]
    denied += [('AU2 a wrong token', 'not-the-token', None), ('AU2 a wrong token and spoofed headers', 'not-the-token', spoof_header_sets()[-1][1])]
    for label, token, extra in denied:
        got = _try(report, label, base.rpc, 'help', {}, token, extra)
        if got is None:
            continue
        status, decoded = got
        if status != 401:
            report.product.append('%s POST /api/jsonrpc help: answered %d, expected 401 (a direct peer needs the token T, R18; auth.use_token at %s)' % (label, status, cfg))
        elif not _unauthorized(status, decoded):
            report.product.append('%s: 401 body %r, expected {error: {code: 401, type: authentication_error}}' % (label, decoded))
    one = json.dumps({'jsonrpc': '2.0', 'method': 'help', 'params': {}, 'id': 1}).encode('utf-8')
    transfer = json.dumps({'source_path': '/x', 'filename': 'x.bin', 'compression': 'identity'}).encode('utf-8')
    for label, method, path, body in (('AU1 POST /api/jsonrpc/batch without token', 'POST', '/api/jsonrpc/batch', b'[' + one + b']'),
                                      ('AU1 GET /downloads/<id>/<name> without token', 'GET', '/downloads/%s/x.bin' % ZERO_ID, None),
                                      ('AU1 POST /api/transfer/downloads without token', 'POST', '/api/transfer/downloads', transfer)):
        got = _try(report, label, base.probe, method, path, body, JSON_HEADERS if body else None, False)
        if got is not None and got[0] != 401:
            report.product.append('%s: answered %d %s, expected 401 (every direct request needs the token T)' % (label, got[0], base.brief(got[2])))
    if live.token():
        got = _try(report, 'AU3 correct token', base.rpc, 'help', {}, live.token())
        if got is not None and not (got[0] == 200 and isinstance(got[1], dict) and got[1].get('result', {}).get('success') is True):
            report.product.append('AU3 POST /api/jsonrpc help with the correct token T: answered %d %s, expected 200 and success' % (got[0], str(got[1])[:120]))
    else:
        report.state.append('AU3 the correct token T = base64(login:password) executes the command: ' + NO_CREDS)
    report.finish('auth_token')


def _config_transfer(report: Report) -> None:
    path = base.ROOT / 'config' / 'server.json'
    transfer = json.loads(path.read_text(encoding='utf-8')).get('transfer')
    where = base.src_line('config/server.json', 'transfer')
    if not isinstance(transfer, dict):
        report.product.append('F9 config/server.json has no transfer section: the adapter transfer service must be configured (allowed_directories = the exports directory only, max_file_size_bytes >= 10 GiB, session_ttl_seconds = 86400)')
        return
    dirs = transfer.get('allowed_directories')
    if not (isinstance(dirs, list) and len(dirs) == 1 and str(dirs[0]).rstrip('/').endswith('/exports')):
        report.product.append('F9 %s transfer.allowed_directories is %r, expected exactly the exports directory' % (where, dirs))
    if not (isinstance(transfer.get('max_file_size_bytes'), int) and transfer['max_file_size_bytes'] >= 10 * 1024 ** 3):
        report.product.append('F9 %s transfer.max_file_size_bytes is %r, expected an integer >= 10 GiB (max export size)' % (where, transfer.get('max_file_size_bytes')))
    if transfer.get('session_ttl_seconds') != 86400:
        report.product.append('F9 %s transfer.session_ttl_seconds is %r, expected 86400' % (where, transfer.get('session_ttl_seconds')))


def transfer_confinement() -> None:
    '''M11/F9: a transfer download of a file outside the exports directory is refused; the service is configured for exports only.'''
    report = Report()
    _config_transfer(report)
    for label, source in (('absolute path outside exports', '/etc/passwd'), ('traversal out of exports', '/data/exports/../secrets/restic-password')):
        body = json.dumps({'source_path': source, 'filename': 'x.bin', 'compression': 'identity'}).encode('utf-8')
        got = _try(report, label, base.probe, 'POST', '/api/transfer/downloads', body, JSON_HEADERS)
        if got is None or _gated(report, label, got[0], True):
            continue
        status = got[0]
        if status == 404:
            report.product.append('M11/F9 POST /api/transfer/downloads source_path=%s: answered 404 %s, the transfer download route is not served (filter at %s); expected a refusal 400, 403 or 422 from the confinement' % (source, base.brief(got[2]), base.src_line(SERVER, 'allowed')))
        elif status < 400:
            report.product.append('M11/F9 POST /api/transfer/downloads source_path=%s: answered %d, the file outside the exports directory was registered' % (source, status))
        elif status not in (400, 403, 422):
            report.product.append('M11/F9 POST /api/transfer/downloads source_path=%s: answered %d, expected 400, 403 or 422' % (source, status))
    try:
        names = base.live_commands()
    except live.LiveUnreachable as exc:
        report.env.append('help: not executed, production service unreachable: %s' % exc)
        names = None
    if names is not None and 'backup_download_begin' not in names:
        report.product.append('M11 help lists %s: the command backup_download_begin is not registered (it registers the transfer session of one export)' % names)
    report.finish('transfer_confinement')


def _s1_download(report: Report) -> None:
    made = cmdcases._prepare_small(report, 'download_link')
    if not made:
        return
    snapshot_id, path, meta = made
    export_id = meta.get('export_id', ZERO_ID)
    try:
        url = meta.get('url')
        if not (isinstance(url, str) and URL_RE.fullmatch(url) and url == '/downloads/%s/%s' % (export_id, meta.get('filename'))):
            report.product.append('M5 backup_prepare_download: url %r, expected %s equal to /downloads/<export_id>/<filename>' % (url, base.URL_PATTERN))
            return
        kind, code, message, status_data = live.request('backup_download_status', {'export_id': export_id})
        if kind != 'success' or status_data.get('url') != url:
            report.product.append('M6 backup_download_status: url %r differs from the prepare url %r' % (status_data.get('url') if isinstance(status_data, dict) else status_data, url))
        got = base.probe('GET', url)
        if got[0] != 200 or len(got[2]) != meta['size_bytes'] or hashlib.sha256(got[2]).hexdigest() != meta['sha256']:
            report.product.append('F8 GET %s: answered %d with %d bytes sha256 %s, expected 200 and the metadata size %s sha256 %s' % (url, got[0], len(got[2]), hashlib.sha256(got[2]).hexdigest()[:12], meta['size_bytes'], meta['sha256'][:12]))
        head = base.probe('HEAD', url)
        if head[0] != 200:
            report.product.append('F8 HEAD %s: answered %d, expected 200' % (url, head[0]))
        wrong = base.probe('GET', '/downloads/%s/other-name.bin' % export_id)
        if wrong[0] != 404:
            report.product.append('F8 GET with a filename other than the metadata name: answered %d, expected 404' % wrong[0])
    finally:
        live.request('backup_delete_export', {'export_id': export_id})
    after = base.probe('GET', url)
    if after[0] != 404:
        report.product.append('F8 GET %s after backup_delete_export: answered %d, expected 404' % (url, after[0]))


def download_link() -> None:
    '''Method 1 of decision 3: the temporary uuid4 link /downloads/<export_id>/<filename> of a staged export.'''
    report = Report()
    probes = (('F8 GET a link without a token', 'GET', '/downloads/%s/x.bin' % ZERO_ID, False, (401,)),
              ('F8 HEAD a link without a token', 'HEAD', '/downloads/%s/x.bin' % ZERO_ID, False, (401,)))
    for label, method, path, auth, statuses in probes:
        got = _try(report, label, base.probe, method, path, None, None, auth)
        if got is not None and got[0] not in statuses:
            report.product.append('%s: answered %d %s, expected 401 (the adapter token gate covers /downloads, M5 contract; the route is not served: filter at %s)' % (label, got[0], base.brief(got[2]), base.src_line(SERVER, 'allowed')))
    for label, path in (('unknown export id', '/downloads/%s/x.bin' % ZERO_ID), ('malformed export id', '/downloads/not-an-id/x.bin'),
                        ('uppercase export id', '/downloads/%s/x.bin' % ('ABCDEF01' * 4))):
        got = _try(report, 'F8 GET ' + label, base.probe, 'GET', path)
        if got is not None and not _gated(report, 'F8 GET ' + label, got[0], True) and got[0] != 404:
            report.product.append('F8 GET %s with the token: answered %d, expected 404' % (label, got[0]))
    state = _try(report, 'service state', live.service_state)
    if state == 'S1':
        _try(report, 'download_link S1', _s1_download, report)
    elif state is not None:
        report.state.append('M5/M6/F8 prepare, url field and GET of a staged export need an S1 service (host directory, container mount, restic password, login and password, finished inventory) but production answers %s' % state)
    report.finish('download_link')


def _attempt(context: ssl.SSLContext) -> str:
    '''Return refused: ... when the TLS or HTTP exchange fails, otherwise served: <status>.'''
    try:
        status, _, _ = base.http_request('GET', '/health', None, None, context)
        return 'served: %d' % status
    except live.LiveUnreachable as exc:
        return 'refused: %s' % exc


def mtls_auth() -> None:
    '''PX10 (R7, R18): no client certificate and an untrusted one are refused for every peer, the trusted pair is served; mTLS alone does not admit a direct peer.'''
    report = Report()
    ca, cert, key = live._tls_files()
    if not all(os.path.isfile(item) for item in (ca, cert, key)):
        report.env.append('TLS material is not readable: %s' % [ca, cert, key])
        report.finish('mtls_auth')
        return
    bare = ssl.create_default_context(cafile=ca)
    if not _attempt(bare).startswith('refused'):
        report.product.append('a client without a certificate was served: %s' % _attempt(bare))
    work = tempfile.mkdtemp(prefix='b4mtls')
    try:
        if shutil.which('openssl') is None:
            report.env.append('openssl is not installed: the untrusted-certificate case cannot be built')
        else:
            done = subprocess.run(['openssl', 'req', '-x509', '-newkey', 'rsa:' + '2048', '-nodes', '-keyout', work + '/k.pem', '-out', work + '/c.pem', '-subj', '/CN=untrusted-b4', '-days', '1'], capture_output=True, text=True)
            if done.returncode != 0:
                report.env.append('openssl could not make the untrusted certificate: ' + done.stderr.strip()[:120])
            else:
                other = ssl.create_default_context(cafile=ca)
                other.load_cert_chain(work + '/c.pem', work + '/k.pem')
                if not _attempt(other).startswith('refused'):
                    report.product.append('a client with an untrusted certificate was served: %s' % _attempt(other))
    finally:
        shutil.rmtree(work, ignore_errors=True)
    good = _try(report, 'trusted pair', _attempt, live._context())
    if good is not None and good != 'served: 200':
        report.product.append('the trusted client pair got %s, expected served: 200' % good)
    got = _try(report, 'trusted pair without token', base.rpc, 'help', {}, None)
    if got is not None and got[0] != 401:
        report.product.append('the trusted client pair without the token T on POST /api/jsonrpc: answered %d, expected 401 (mTLS is mandatory for every peer, the token T for a direct peer, R7)' % got[0])
    report.finish('mtls_auth')
