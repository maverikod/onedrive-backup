'''UI-VUE named checks V1..V6: the Vue 3 SPA exercised through its real surface (nginx on the LAN, adapter commands over /api/jsonrpc).

Each function is the body of one pipeline/checks/check_<name>.py. The matrix (rows V1..V6, section 7.4, 8.3 UI-VUE, D3, D5, D7) states
what the SPA does; what it leaves open is listed in vuebase.GAPS and reported as GAP lines, never invented. Today the SPA does not exist,
so every check is RED [PRODUCT] for the absent SPA (and for the server HTML routes that the SPA replaces).
'''

from __future__ import annotations

import hashlib
import json
import urllib.parse
from pathlib import Path

from pipeline import b4base as base, b4server, cmdcases, credentials, live
from pipeline.report import Report
from pipeline.vuebase import ROOT, REFERENCE, SCRIPT_TAG, LEGACY_MARKERS, ASSET_LIMIT, deployed, gap, lan_rpc, lan_try, removed_ui, scan_secrets, spa_files, tracked_files

# Action table of section 7.4: one SPA action -> the adapter command and the parameters it must send (names; fixed values where stated).
ACTIONS = (
    ('V4 snapshot list (U5)', 'backup_snapshots', ('limit',), {'limit': 100}),
    ('V4 snapshot files (U6)', 'backup_list_files', ('snapshot_id', 'prefix', 'offset', 'limit'), {'limit': 100}),
    ('V4 export start (U7)', 'backup_prepare_download', ('snapshot_id', 'file_path'), {}),
    ('V4 export card (U8)', 'backup_download_status', ('export_id',), {}),
    ('V4 export delete (U10)', 'backup_delete_export', ('export_id',), {}),
    ('V4 sites page', 'backup_sites_list', (), {}),
    ('V4 libraries page', 'backup_libraries_list', (), {}),
    ('V4 discovery page', 'backup_discovery_status', (), {}),
    ('V4 help page (Q4)', 'help', (), {}),
    ('V4 info page (Q4)', 'info', (), {}),
)


def _same_origin(ref: str, host: str) -> str | None:
    '''Return the path of a same-origin asset reference, or None for data, anchors, scripts and other origins.'''
    parts = urllib.parse.urlsplit(ref)
    if parts.scheme in ('data', 'javascript', 'mailto') or ref.startswith('#') or (parts.scheme and parts.netloc != host):
        return None
    path = parts.path or '/'
    return path if path.startswith('/') else '/' + path


def _index_cases(report: Report, root: str, got: tuple[int, dict, bytes]) -> None:
    '''V1 cases on the index page served by the SPA endpoint.'''
    status, headers, body = got
    text = body.decode('utf-8', 'replace')
    if status != 200:
        report.product.append('V1 GET /: answered %d %s, expected 200 with the SPA index page' % (status, base.brief(body)))
        return
    if not headers.get('content-type', '').lower().startswith('text/html'):
        report.product.append('V1 GET /: content-type %r, expected text/html' % headers.get('content-type'))
    if not SCRIPT_TAG.search(text):
        report.product.append('V1 GET /: the page references no script, it is not a single page application')
    for marker in LEGACY_MARKERS:
        if marker in text.lower():
            report.product.append('V1 GET /: the page holds %r, it is the removed server HTML and not the SPA' % marker)
    if not headers.get('content-security-policy', '').strip():
        report.product.append('V1 GET /: no Content-Security-Policy header')
    if 'no-store' not in headers.get('cache-control', '').lower():
        report.product.append('V1 GET /: Cache-Control %r does not hold no-store' % headers.get('cache-control'))
    host = urllib.parse.urlsplit(root).netloc
    seen = 0
    for ref in REFERENCE.findall(text):
        parts = urllib.parse.urlsplit(ref)
        if parts.scheme in ('http', 'https') and parts.netloc != host:
            report.product.append('V1 GET /: the page loads %s from another origin, the runtime has no external dependency' % parts.netloc)
            continue
        path = _same_origin(ref, host)
        if path is None or seen >= ASSET_LIMIT:
            continue
        seen += 1
        asset = lan_try(report, 'V1 GET ' + path, root, 'GET', path)
        if asset is None:
            continue
        if asset[0] != 200 or asset[1].get('content-type', '').lower().startswith('text/html'):
            report.product.append('V1 GET %s: answered %d %s, expected 200 with the asset, not the index page' % (path, asset[0], asset[1].get('content-type')))


def vue_static_serve() -> None:
    '''V1 (+U1): the SPA is served by nginx on the LAN with CSP and no-store; the server HTML /ui is gone.'''
    report = Report()
    removed_ui(report, ('U1',))
    root = deployed(report, 'V1 SPA endpoint')
    if root is not None:
        got = lan_try(report, 'V1 GET /', root, 'GET', '/')
        if got is not None:
            _index_cases(report, root, got)
    gap(report, 'G2', 'V1 the SPA endpoint is served only after mTLS (7.4) or on the plain LAN (D5)')
    gap(report, 'G3', 'V1 the exact CSP and no-store values')
    gap(report, 'G4', 'V1 deep link, unknown path and removed /ui* answers through the SPA endpoint')
    report.finish('vue_static_serve')


def _denied(report: Report, root: str, label: str, token: str | None) -> None:
    got = lan_rpc(report, label, root, 'help', {}, token)
    if got is None:
        return
    status, decoded = got
    if status != 401:
        report.product.append('%s POST /api/jsonrpc help through the SPA endpoint: answered %d, expected 401 (the SPA shows the login menu on 401, D3)' % (label, status))
    elif not b4server._unauthorized(status, decoded):
        report.product.append('%s: 401 body %r, expected {error: {code: 401, type: authentication_error}}' % (label, decoded))


def _auth_transport(report: Report, root: str) -> None:
    '''V2 transport cases: the answers the SPA turns into the login menu or into a result, asserted through the SPA endpoint.'''
    _denied(report, root, 'V2 no token', None)
    _denied(report, root, 'V2 empty token', '')
    _denied(report, root, 'V2 a token that is not base64(login:password)', 'not-the-token')
    _denied(report, root, 'V2 a well-formed token of a wrong login and password', credentials.derive('nobody', 'wrong-password'))
    if not live.token():
        report.state.append('V2 the correct login runs a command: ' + base.NO_CREDS)
        return
    got = lan_rpc(report, 'V2 correct token', root, 'help', {}, live.token())
    if got is not None and not (got[0] == 200 and isinstance(got[1], dict) and got[1].get('result', {}).get('success') is True):
        report.product.append('V2 POST /api/jsonrpc help with the correct token T through the SPA endpoint: answered %d %s, expected 200 and success' % (got[0], str(got[1])[:100]))


def vue_auth() -> None:
    '''V2 (+U2, U3, U4): 401 shows the menu, a wrong password shows the menu, a correct login runs a command; the server login routes are gone.'''
    report = Report()
    removed_ui(report, ('U2', 'U3', 'U4'))
    root = deployed(report, 'V2 SPA endpoint')
    if root is not None:
        _auth_transport(report, root)
    gap(report, 'G7', 'V2 the rendered login menu on 401, after a wrong password, and the page that shows the result of a command after a correct login')
    gap(report, 'G1', 'V2 the SPA endpoint address the form posts to')
    report.finish('vue_auth')


def vue_command_contract() -> None:
    '''V3: the commands and parameters the SPA uses equal the live help list; the reference side is the live service.'''
    report = Report()
    spa_files(report, 'V3 SPA sources')
    try:
        names = base.live_commands()
    except live.LiveUnreachable as exc:
        report.env.append('V3 live help: not executed, production service unreachable: %s' % exc)
        names = None
    if names is not None:
        if names != sorted(base.COMMANDS):
            report.product.append('V3 live help lists %s, expected exactly the 11 commands %s (missing %s, unexpected %s)'
                                  % (len(names), sorted(base.COMMANDS), sorted(set(base.COMMANDS) - set(names)), sorted(set(names) - set(base.COMMANDS))))
        report.info.append('V3 reference side: %d live commands, parameters %s' % (len(names), {name: base.command_params(name) for name in names}))
    gap(report, 'G5', 'V3 the command and parameter set declared by the SPA equals the live help list (extra or missing command is RED)')
    report.finish('vue_command_contract')


def _actions_cases(report: Report) -> None:
    '''Reference side of V4: every command and parameter of the action table exists in the live help.'''
    try:
        names = base.live_commands()
    except live.LiveUnreachable as exc:
        report.env.append('V4 live help: not executed, production service unreachable: %s' % exc)
        return
    for label, command, params, fixed in ACTIONS:
        if command not in names:
            report.product.append('%s: the action calls %s, which the live help does not list' % (label, command))
            continue
        live_params = base.command_params(command)
        missing = [item for item in params if item not in live_params]
        if missing:
            report.product.append('%s: the live help of %s does not accept %s (accepts %s)' % (label, command, missing, live_params))


def vue_command_calls() -> None:
    '''V4 (+U5..U8, U10): each SPA action calls the expected command with the expected parameters and the page equals the command result.'''
    report = Report()
    removed_ui(report, ('U5', 'U6', 'U7', 'U8', 'U10'))
    _actions_cases(report)
    root = deployed(report, 'V4 SPA endpoint')
    if root is not None:
        spa_files(report, 'V4 SPA sources')
    gap(report, 'G7', 'V4 every action of the table performed in a headless browser and the commands it sends captured')
    gap(report, 'G9', 'V4 the page text equals the result of the same command through the Python client')
    gap(report, 'G10', 'vue_polling')
    report.finish('vue_command_calls')


def _s1_download(report: Report, root: str) -> None:
    '''V5 in S1: stage a small export, download it through the SPA endpoint link the way the page does, compare size and sha256 with the metadata.'''
    made = cmdcases._prepare_small(report, 'vue_download')
    if not made:
        return
    meta = made[2]
    export_id = meta.get('export_id', base.ZERO_ID)
    try:
        url = meta.get('url')
        if not (isinstance(url, str) and url == '/downloads/%s/%s' % (export_id, meta.get('filename'))):
            report.product.append('V5 backup_prepare_download: url %r, expected %s' % (url, base.URL_PATTERN))
            return
        got = lan_try(report, 'V5 GET ' + url, root, 'GET', url)
        if got is None:
            return
        digest = hashlib.sha256(got[2]).hexdigest()
        if got[0] != 200 or len(got[2]) != meta['size_bytes'] or digest != meta['sha256']:
            report.product.append('V5 GET %s through the SPA endpoint: answered %d with %d bytes sha256 %s, expected 200 and the metadata size %s sha256 %s'
                                  % (url, got[0], len(got[2]), digest[:12], meta['size_bytes'], meta['sha256'][:12]))
    finally:
        live.request('backup_delete_export', {'export_id': export_id})


def vue_download() -> None:
    '''V5 (+U9): the download link of an export downloads the file and its sha256 equals the metadata; the server HTML download route is gone.'''
    report = Report()
    removed_ui(report, ('U9',))
    root = deployed(report, 'V5 SPA endpoint')
    if root is not None:
        unknown = '/downloads/%s/x.bin' % base.ZERO_ID
        got = lan_try(report, 'V5 GET an unknown link', root, 'GET', unknown, base.auth_headers())
        if got is not None and got[0] != 404:
            report.product.append('V5 GET %s through the SPA endpoint with the token: answered %d %s, expected 404' % (unknown, got[0], base.brief(got[2])))
        state = b4server._try(report, 'service state', live.service_state)
        if state == 'S1':
            _s1_download(report, root)
        elif state is not None:
            report.state.append('V5 prepare, link and download of a staged export need an S1 service (host directory, container mount, restic password, login and password, finished inventory) but production answers %s' % state)
    gap(report, 'G8', 'V5 a tokenless browser GET of the link through the SPA endpoint')
    gap(report, 'G7', 'V5 the page of an export shows the link and the click downloads the file in a headless browser')
    report.finish('vue_download')


def vue_build() -> None:
    '''V6: the SPA build is reproducible, its artifacts hold no secret and its version equals VERSION.'''
    report = Report()
    found = spa_files(report, 'V6 SPA sources')
    tree = sorted({str(Path(item).parent) for item in found if Path(item).name == 'package.json'})
    below = [item for item in (tracked_files() or []) if any(item.startswith(d.rstrip('/') + '/') for d in tree if d != '.')]
    if below:
        scan_secrets(report, 'V6 secrets', below)
    for item in found:
        if Path(item).name == 'package.json':
            try:
                declared = json.loads((ROOT / item).read_text(encoding='utf-8')).get('version')
            except (OSError, ValueError):
                declared = None
            if declared != base.version():
                report.product.append('V6 %s: version %r, expected the VERSION file content %r' % (item, declared, base.version()))
    gap(report, 'G6', 'V6 two builds of the same source give the same artifacts, the built artifacts hold no secret, and the built SPA reports VERSION')
    report.finish('vue_build')
