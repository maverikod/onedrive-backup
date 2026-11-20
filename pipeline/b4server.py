'''B4 named checks of the server side: REST removal, anonymous access (auth is off, revision 8), the adapter-native route set,
download link, transfer.

Every check talks to the production service named in pipeline/endpoints.env over TLS; the client certificate pair is used only when
the pipeline tree holds it (https without, mtls with). Findings are kept apart:
PRODUCT (the deployed service or its code breaks the contract), STATE (the case needs state or credentials the
owner has not provisioned) and ENVIRONMENT (the pipeline cannot reach the service).
'''

from __future__ import annotations

import hashlib
import json
import re

from pipeline import b4base as base, cmdcases, live
from pipeline.b4base import JSON_HEADERS, ZERO_ID, Q
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
    '''Revision 8 (AU1): the service is open, there is no token gate; a 401 is a PRODUCT finding of the caller, never a STATE.'''
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


# The adapter-native HTTP routes of mcp-proxy-adapter 8.11.20 (research report 129d1156, R2; app_factory_routes.py and public_downloads.py of the
# wheel). Revision 8 removes the project route filter, so every one of them is served; any other route is a project-owned addition.
NATIVE_PATHS = (
    '/health', '/commands', '/heartbeat', '/api/jsonrpc', '/api/jsonrpc/batch', '/api/async', '/tools/{tool_name}',
    '/api/transfer/uploads', '/api/transfer/uploads/{transfer_id}', '/api/transfer/uploads/{transfer_id}/chunks',
    '/api/transfer/uploads/{transfer_id}/complete', '/api/transfer/downloads', '/api/transfer/downloads/{transfer_id}',
    '/api/transfer/downloads/{transfer_id}/chunks', '/downloads/{file_id}/{filename}',
)


def adapter_native_surface() -> None:
    '''F1..F11 (revision 8, 10.15.9.3 PP-D1c): the live route set equals the adapter-native set plus the SPA mount; any other route is RED.'''
    report = Report()

    def expect(label, method, path, statuses, body=None, headers=None):
        got = _try(report, label, base.probe, method, path, body, headers)
        if got is None:
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
        extra = sorted(set(paths) - set(NATIVE_PATHS))
        if extra:
            report.product.append('F-surface: the live route set holds %s, which are not adapter-native routes of the pinned adapter: a project-owned route (RED, PP-D1c of revision 8)' % extra)
        absent = sorted(set(NATIVE_PATHS) - set(paths))
        if absent:
            report.product.append('F8-F11: the adapter-native routes %s are not served: the project route filter %s still hides them (10.15.2 (3): removed, nothing replaces it)'
                                  % (absent, base.src_line(SERVER, 'ALLOWED_ROUTES')))
    else:
        report.info.append('F8, F9: route presence is not provable without /openapi.json (F5 is RED)')
    report.info.append('the WebSocket /ws and the SPA StaticFiles mount are not part of /openapi.json: the mount is asserted by vue_static_serve, /ws is native and no longer asserted closed (F10, F11 retired)')
    report.finish('adapter_native_surface')


def _ok(decoded) -> bool:
    '''True for a JSON-RPC success reply of the adapter.'''
    return isinstance(decoded, dict) and isinstance(decoded.get('result'), dict) and decoded['result'].get('success') is True


def auth_token() -> None:
    '''AU1, AU2 (revision 8, 10.15.9.2): auth is off, an anonymous caller executes and a credential header of any value is not interpreted; AU3 is retired.'''
    report = Report()
    cfg = base.src_line('config/server.json', 'use_token')
    cases = [('AU1 no credential', None, None), ('AU2 an empty X-API-Key value', '', None), ('AU2 an X-API-Key value of any kind', 'any-value-at-all', None),
             ('AU2 an Authorization Bearer header of any value', None, {'Authorization': 'Bearer any-value-at-all'})]
    for label, token, extra in cases:
        got = _try(report, label, base.rpc, 'help', {}, token, extra)
        if got is None:
            continue
        status, decoded = got
        if status != 200 or not _ok(decoded):
            report.product.append('%s POST /api/jsonrpc help: answered %d %s, expected 200 and success: the service is open and interprets no credential (auth.use_token must be false, now at %s)'
                                  % (label, status, str(decoded)[:100], cfg))
            continue
        names = sorted((decoded['result'].get('data') or {}).get('commands', {}))
        if names != sorted(COMMANDS):
            report.product.append('%s: help lists %d commands %s, expected exactly the 11 of rows M1..M11' % (label, len(names), names))
    one = json.dumps({'jsonrpc': '2.0', 'method': 'help', 'params': {}, 'id': 1}).encode('utf-8')
    transfer = json.dumps({'source_path': '/x', 'filename': 'x.bin', 'compression': 'identity'}).encode('utf-8')
    for label, method, path, body, wanted in (('AU1 POST /api/jsonrpc/batch without a credential', 'POST', '/api/jsonrpc/batch', b'[' + one + b']', (200,)),
                                              ('AU1 GET /downloads/<id>/<name> without a credential', 'GET', '/downloads/%s/x.bin' % ZERO_ID, None, (404,)),
                                              ('AU1 POST /api/transfer/downloads without a credential', 'POST', '/api/transfer/downloads', transfer, (400, 403, 404, 422))):
        got = _try(report, label, base.probe, method, path, body, JSON_HEADERS if body else None, False)
        if got is not None and got[0] not in wanted:
            report.product.append('%s: answered %d %s, expected %s (no 401 exists, the service is open; auth.use_token at %s)' % (label, got[0], base.brief(got[2]), ' or '.join(map(str, wanted)), cfg))
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
    probes = (('F8 GET a link without a credential', 'GET', '/downloads/%s/x.bin' % ZERO_ID, False, (404,)),
              ('F8 HEAD a link without a credential', 'HEAD', '/downloads/%s/x.bin' % ZERO_ID, False, (404,)))
    for label, method, path, auth, statuses in probes:
        got = _try(report, label, base.probe, method, path, None, None, auth)
        if got is not None and got[0] not in statuses:
            report.product.append('%s: answered %d %s, expected 404 (the service is open, AU1: an unknown export id is 404, never a 401 gate; the route filter hides or gates it, see %s)' % (label, got[0], base.brief(got[2]), base.src_line(SERVER, 'allowed')))
    for label, path in (('unknown export id', '/downloads/%s/x.bin' % ZERO_ID), ('malformed export id', '/downloads/not-an-id/x.bin'),
                        ('uppercase export id', '/downloads/%s/x.bin' % ('ABCDEF01' * 4))):
        got = _try(report, 'F8 GET ' + label, base.probe, 'GET', path)
        if got is not None and not _gated(report, 'F8 GET ' + label, got[0], True) and got[0] != 404:
            report.product.append('F8 GET %s without a credential: answered %d, expected 404' % (label, got[0]))
    state = _try(report, 'service state', live.service_state)
    if state == 'S1':
        _try(report, 'download_link S1', _s1_download, report)
    elif state is not None:
        report.state.append('M5/M6/F8 prepare, url field and GET of a staged export need an S1 service (host directory, container mount, restic password, finished inventory) but production answers %s' % state)
    report.finish('download_link')
