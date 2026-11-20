'''UI-VUE named checks V1..V6: the Vue 3 SPA exercised through its real surface (the service mount over HTTPS on the LAN URL, adapter commands over /api/jsonrpc).

Each function is the body of one pipeline/checks/check_<name>.py. The matrix (rows V1..V6, sections 7.4, 8.3 UI-VUE, 10.11/10.12 as replaced by 10.15.6
and 10.15.9) states what the SPA does; what needs the headless browser driver is listed in vuebase.GAPS and reported as GAP lines, never invented.
While the SPA does not exist every check is RED [PRODUCT] for the absent SPA; the browser cases then name that they were not executed.
'''

from __future__ import annotations

import hashlib
import json
import urllib.parse
from pathlib import Path

import re

from pipeline import b4base as base, b4server, cmdcases, live, vuebrowser, vuebuild, vueroutes
from pipeline.report import Report
from pipeline.vuebase import (ROOT, REFERENCE, SCRIPT_TAG, LEGACY_MARKERS, ASSET_LIMIT, CSP_EXPECTED, CSP_FORBIDDEN, SPA_FILES, deployed, lan_rpc, lan_try,
                              removed_ui, scan_secrets, spa_files, tracked_files)

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


META_CSP = re.compile(r'<meta[^>]+http-equiv\s*=\s*["\']content-security-policy["\'][^>]*content\s*=\s*(?:"([^"]*)"|\'([^\']*)\')', re.I)
APP_MOUNT = re.compile(r'<div[^>]+id\s*=\s*["\']app["\']', re.I)


def _csp(report: Report, text: str) -> None:
    '''V1 (PP4, 10.18.6): the mount element has the id app; the CSP is a meta tag of index.html and its directive set EQUALS the approved one, with no unsafe or wildcard source.

    The content attribute is captured quote-matched: a CSP value holds single quotes (the keywords 'none' and 'self'), so a pattern that stops at the first quote of either kind can never match a valid policy.'''
    if not APP_MOUNT.search(text):
        report.product.append('V1 GET /: index.html has no mount element with id app (<div id="app">, 10.18.6)')
    found = META_CSP.search(text)
    if not found:
        report.product.append('V1 GET /: index.html carries no <meta http-equiv="Content-Security-Policy"> tag (the CSP is a meta tag, nginx headers cannot exist)')
        return
    directives = {}
    for part in (found.group(1) if found.group(1) is not None else found.group(2)).split(';'):
        words = part.split()
        if words:
            directives[words[0]] = ' '.join(words[1:])
    if directives != CSP_EXPECTED:
        report.product.append('V1 GET /: the meta CSP is %r, expected exactly %r' % (directives, CSP_EXPECTED))
    for source in CSP_FORBIDDEN:
        if any(source in value.split() for value in directives.values()):
            report.product.append('V1 GET /: the meta CSP holds the forbidden source %s' % source)


def _assets(report: Report, root: str) -> None:
    '''V1 (G4, PP-AUTH4): the fixed finite file set is served with the right content type; an unknown path is the mount 404, never the index.'''
    for path, kinds in SPA_FILES.items():
        for method in ('GET', 'HEAD'):
            got = lan_try(report, 'V1 %s %s' % (method, path), root, method, path)
            if got is None:
                continue
            if got[0] != 200 or not any(kind in got[1].get('content-type', '').lower() for kind in kinds):
                report.product.append('V1 %s %s: answered %d with content-type %r, expected 200 with a %s content type' % (method, path, got[0], got[1].get('content-type'), kinds[0]))
    got = lan_try(report, 'V1 GET an unknown path', root, 'GET', '/no/such/path')
    if got is not None and (got[0] != 404 or b'<script' in got[2].lower()):
        report.product.append('V1 GET /no/such/path: answered %d %s, expected the mount 404 (hash routing, no history fallback, never index.html)' % (got[0], base.brief(got[2])))


def _index_cases(report: Report, root: str, got: tuple[int, dict, bytes]) -> None:
    '''V1 cases on the index page served by the service mount.'''
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
    _csp(report, text)
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
        if path not in SPA_FILES and path != '/':
            report.product.append('V1 GET /: the page references %s, outside the fixed file set %s (public_paths are exact: a new asset name needs a matrix revision)' % (path, sorted(SPA_FILES)))
    _assets(report, root)


def index_served(report: Report, label: str, root: str) -> bool:
    '''True when the SPA index page is served at the LAN URL; otherwise a PRODUCT finding (the SPA is absent, V1) and False.'''
    index = lan_try(report, label + ' GET /', root, 'GET', '/')
    if index is None:
        return False
    if index[0] != 200 or not SCRIPT_TAG.search(index[2].decode('utf-8', 'replace')):
        report.product.append('%s: the SPA index page is not served at the LAN URL (GET / answered %d, V1): the page cases are not executed' % (label, index[0]))
        return False
    return True


def with_driver(report: Report, label: str, root: str, *cases) -> None:
    '''Run the headless browser cases (case(report, driver)) against the deployed SPA.

    No SPA index at the LAN URL is a PRODUCT finding (the cases are not executed, V1); a missing Playwright or Chromium is an ENVIRONMENT finding.'''
    if not index_served(report, label, root):
        return
    why = vuebrowser.problem()
    if why:
        report.env.append('%s: %s' % (label, why))
        return
    try:
        with vuebrowser.Driver(root) as drv:
            for case in cases:
                case(report, drv)
    except live.LiveUnreachable as exc:
        report.env.append('%s: not executed, %s' % (label, exc))
    except Exception as exc:
        report.env.append('%s: the headless run failed: %s: %s' % (label, type(exc).__name__, str(exc)[:300]))


def vue_static_serve() -> None:
    '''V1 (+U1): the SPA is mounted by the service over HTTPS on the LAN URL, no client certificate, CSP by meta tag; the server HTML /ui is gone.'''
    report = Report()
    removed_ui(report, ('U1',))
    root = deployed(report, 'V1 SPA endpoint')
    if root is not None:
        got = lan_try(report, 'V1 GET /', root, 'GET', '/')
        if got is not None:
            _index_cases(report, root, got)
        head = lan_try(report, 'V1 HEAD /', root, 'HEAD', '/')
        if head is not None and head[0] != 200:
            report.product.append('V1 HEAD /: answered %d, expected 200 (the mount serves GET and HEAD)' % head[0])
    report.finish('vue_static_serve')


def _open(report: Report, root: str, label: str, token: str | None) -> None:
    '''V2 (revision 8): through the SPA endpoint the open service runs a command with no credential and with a credential header of any value.'''
    got = lan_rpc(report, label, root, 'help', {}, token)
    if got is None:
        return
    status, decoded = got
    if status != 200 or not (isinstance(decoded, dict) and decoded.get('result', {}).get('success') is True):
        report.product.append('%s POST /api/jsonrpc help through the SPA endpoint: answered %d %s, expected 200 and success (the service is open, no login form exists while it is open)' % (label, status, str(decoded)[:100]))


def vue_auth() -> None:
    '''V2 (+U2, U3, U4): no login form while the service is open; a key field only after a 401, with the ids of 10.18.6 and both submissions; logout always present; the server login routes are gone.'''
    report = Report()
    removed_ui(report, ('U2', 'U3', 'U4'))
    root = deployed(report, 'V2 SPA endpoint')
    if root is not None:
        _open(report, root, 'V2 no credential', None)
        _open(report, root, 'V2 an X-API-Key value of any kind', 'any-value-at-all')
        with_driver(report, 'V2 browser', root, lambda rep, drv: vuebrowser.open_cases(rep, drv), vuebrowser.key_after_401, vueroutes.auth_ids)
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
    root = deployed(report, 'V3 SPA endpoint')
    if root is not None:
        vuebuild.manifest_cases(report, root)
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
    '''V4 + V8 (+U5..U8, U10): each SPA action calls the expected command with the expected parameters, the page equals the command result, and every route, nav id and test id of 10.18 exists.'''
    report = Report()
    removed_ui(report, ('U5', 'U6', 'U7', 'U8', 'U10'))
    _actions_cases(report)
    root = deployed(report, 'V4 SPA endpoint')
    if root is not None:
        spa_files(report, 'V4 SPA sources')
        with_driver(report, 'V4 browser', root, vuebrowser.table_cases, vuebrowser.page_equals_result, vueroutes.nav_cases, vueroutes.route_cases)
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
        if 'set-cookie' in got[1]:
            report.product.append('V5 GET %s: the answer carries Set-Cookie, expected none' % url)
        if got[0] != 200 or len(got[2]) != meta['size_bytes'] or digest != meta['sha256']:
            report.product.append('V5 GET %s through the SPA endpoint: answered %d with %d bytes sha256 %s, expected 200 and the metadata size %s sha256 %s'
                                  % (url, got[0], len(got[2]), digest[:12], meta['size_bytes'], meta['sha256'][:12]))
    finally:
        live.request('backup_delete_export', {'export_id': export_id})


def vue_download() -> None:
    '''V5 (+U9): the download link of an export downloads the file and its sha256 equals the metadata; in S1 the browser starts an export, shows its card, downloads it by the plain link and deletes it (10.18.4); the server HTML download route is gone.'''
    report = Report()
    removed_ui(report, ('U9',))
    root = deployed(report, 'V5 SPA endpoint')
    if root is not None:
        index_served(report, 'V5 download page', root)
        unknown = '/downloads/%s/x.bin' % base.ZERO_ID
        got = lan_try(report, 'V5 GET an unknown link', root, 'GET', unknown)
        if got is not None and got[0] != 404:
            report.product.append('V5 GET %s through the SPA endpoint without a credential: answered %d %s, expected 404 (unknown well-formed id; the service is open)' % (unknown, got[0], base.brief(got[2])))
        state = b4server._try(report, 'service state', live.service_state)
        if state == 'S1':
            _s1_download(report, root)
            with_driver(report, 'V5 browser', root, lambda rep, drv: vueroutes.export_cases(rep, drv, root))
        elif state is not None:
            report.state.append('V5 prepare, link and download of a staged export need an S1 service (host directory, container mount, restic password, finished inventory) but production answers %s' % state)
    report.finish('vue_download')


def vue_polling() -> None:
    '''V7 (R25, R28, 10.18.5): the discovery page polls every 30 s and stops on a 401; logout sends nothing of any method afterwards; the card of a final export never polls.'''
    report = Report()
    root = deployed(report, 'V7 SPA endpoint')
    if root is not None:
        with_driver(report, 'V7 browser', root, vuebrowser.polling, vueroutes.logout_cases, vueroutes.export_poll_case)
    report.finish('vue_polling')


def _service_build(report: Report) -> None:
    '''V6 (G6 as replaced, PP2): the SPA is built by a Node stage of the EXISTING service Dockerfile; no second image, no web image; Node 22 pinned; fixed no-hash file names.'''
    dockerfile = (ROOT / 'docker' / 'Dockerfile').read_text(encoding='utf-8')
    for needle, why in ((''.join(('node', ':22')), 'a Node 22 build stage'), ('npm ci', 'npm ci in the build stage'), ('npm run build', 'npm run build in the build stage'), ('/app/web', 'the dist copied to /app/web')):
        if needle not in dockerfile:
            report.product.append('V6 docker/Dockerfile: %s is missing (%s, one image carries the SPA)' % (needle, why))
    tracked = tracked_files() or []
    second = [item for item in tracked if 'onedrive-backup-web' in item or Path(item).name.lower() in ('dockerfile.web', 'nginx.conf')]
    if second:
        report.product.append('V6 a second image or nginx artefact is tracked: %s (no second image, no nginx, revision 8)' % second)
    version_file = ROOT / 'frontend' / '.node-version'
    if not version_file.is_file() or not version_file.read_text(encoding='utf-8').strip().startswith('22'):
        report.product.append('V6 frontend/.node-version must exist and pin Node major 22')
    if 'frontend/package-lock.json' not in tracked:
        report.product.append('V6 frontend/package-lock.json is not tracked (the lockfile makes the build reproducible)')
    config = next((ROOT / 'frontend' / name for name in ('vite.config.ts', 'vite.config.js') if (ROOT / 'frontend' / name).is_file()), None)
    text = config.read_text(encoding='utf-8') if config else ''
    for needle in ('assets/app.js', 'assets/app.css', 'inlineDynamicImports'):
        if needle not in text:
            report.product.append('V6 frontend/vite.config: %s is missing (PP-AUTH4: fixed file names without content hashes, one chunk)' % needle)


def vue_build() -> None:
    '''V6: the SPA build is in the service Dockerfile, reproducible, its artifacts hold no secret and its version equals VERSION.'''
    report = Report()
    found = spa_files(report, 'V6 SPA sources')
    _service_build(report)
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
    vuebuild.build_cases(report)
    report.finish('vue_build')
