'''Shared helpers of the B4 named checks (client parity, download, authentication, route surface).

User decisions of 2026-11-18 and 2026-11-19 (revision 8) that these checks encode: (1) the server API is the set of
mcp-proxy-adapter commands over JSON-RPC and the Python client is a thin wrapper over the adapter JsonRpcClient; (2) odbcli is a
console command built on that client; (3) download by a temporary uuid4 link and by the client through the adapter transfer service,
size and SHA256 verified; (4) REST /api/v1/* removed; (5) revision 8: the service is open for now (auth off), the later password mode
is the adapter static key sent as X-API-Key, switched on by configuration only; (6) the adapter-native routes are served, the
project filter is removed; (7) the live version equals VERSION.

The pipeline run holds at most ONE credential, the optional ONEDRIVE_BACKUP_PASSWORD, read through pipeline.credentials (a
git-ignored 0600 env file named by ONEDRIVE_BACKUP_CREDENTIALS_FILE, or the variable in the environment of the run). Nothing of it
is committed. An absent password is GREEN against the open service; an unusable credentials file is RED as STATE or ENVIRONMENT
(R17), never PRODUCT and never skipped.
'''

from __future__ import annotations

import http.client
import json
import ssl
import urllib.parse
from pathlib import Path

from pipeline import credentials, live
from pipeline.report import Report

ROOT = Path(__file__).resolve().parents[1]
PACKAGE_DIR = ROOT / 'client' / 'onedrive_backup_client'
CLIENT_DIR = ROOT / 'client'
TOKEN_HEADER = 'X-API-Key'
Q = chr(34)
ZERO_ID = '0' * 32
JSON_HEADERS = {'Content-Type': 'application/json'}
NO_CREDS = 'the run credentials are unusable: ' + (credentials.problem() or 'no problem found')
URL_PATTERN = '/downloads/<32 lowercase hex>/<filename>'
COMMANDS = ('help', 'info', 'backup_snapshots', 'backup_list_files', 'backup_prepare_download', 'backup_download_status',
            'backup_delete_export', 'backup_sites_list', 'backup_libraries_list', 'backup_discovery_status',
            'backup_download_begin')
FRAMEWORK_404 = b'{"detail":"Not Found"}'


def version() -> str:
    '''Return the VERSION file content, the single source of the release version.'''
    return (ROOT / 'VERSION').read_text(encoding='utf-8').strip()


def src_line(rel: str, needle: str) -> str:
    '''Return rel:line of the first line holding needle, or rel alone when it is absent.'''
    try:
        for number, text in enumerate((ROOT / rel).read_text(encoding='utf-8').splitlines(), 1):
            if needle in text:
                return '%s:%d' % (rel, number)
    except OSError:
        pass
    return rel


def http_request(method: str, path: str, body: bytes | None = None, headers: dict | None = None,
                 context: ssl.SSLContext | None = None) -> tuple[int, dict, bytes]:
    '''Send one HTTPS request to the production service; return (status, lower-cased headers, body).'''
    parts = urllib.parse.urlsplit(live.base_url())
    conn = http.client.HTTPSConnection(parts.hostname, parts.port or 443, context=context or live._context(), timeout=30)
    try:
        conn.request(method, path, body=body, headers=headers or {})
        reply = conn.getresponse()
        return reply.status, {k.lower(): v for k, v in reply.getheaders()}, reply.read()
    except (OSError, ssl.SSLError, http.client.HTTPException) as exc:
        raise live.LiveUnreachable('%s %s failed: %s: %s' % (method, path, type(exc).__name__, exc))
    finally:
        conn.close()


def auth_headers() -> dict:
    '''Return the X-API-Key header of the optional run password, or an empty mapping.'''
    token = live.token()
    return {TOKEN_HEADER: token} if token else {}


def probe(method: str, path: str, body: bytes | None = None, headers: dict | None = None, auth: bool = True):
    '''One request; the run token is added when auth is true and the run holds credentials.'''
    merged = dict(headers or {})
    if auth:
        merged.update(auth_headers())
    return http_request(method, path, body, merged)


def rpc(command: str, params: dict | None = None, token: str | None = None, extra: dict | None = None) -> tuple[int, object]:
    '''POST one JSON-RPC request with an explicit token (None sends no token header) and optional extra headers.'''
    headers = dict(JSON_HEADERS)
    if token is not None:
        headers[TOKEN_HEADER] = token
    if extra:
        headers.update(extra)
    body = json.dumps({'jsonrpc': '2.0', 'method': command, 'params': params or {}, 'id': 1}).encode('utf-8')
    status, _, raw = http_request('POST', '/api/jsonrpc', body, headers)
    try:
        return status, json.loads(raw)
    except ValueError:
        return status, None


def brief(raw: bytes) -> str:
    '''Short printable form of a response body.'''
    return raw[:100].decode('utf-8', 'replace').replace(chr(10), ' ')


def live_commands() -> list[str]:
    '''Return the command names the live service lists in help (adapter registry).'''
    status, decoded = rpc('help', {}, live.token())
    data = decoded.get('result', {}).get('data', {}) if isinstance(decoded, dict) else {}
    return sorted(data.get('commands', {})) if isinstance(data, dict) else []


def command_params(command: str) -> list[str]:
    '''Return the parameter names the live service documents for one command (help cmdname).'''
    status, decoded = rpc('help', {'cmdname': command}, live.token())
    try:
        return sorted(decoded['result']['data']['metadata']['parameters'])
    except (KeyError, TypeError):
        return []


UNKNOWN_SNAPSHOT_CANDIDATES = ('abcdef12', 'fedcba98', '0badc0de', '1badb002')
UNKNOWN_SITE_CANDIDATES = ('site-1', 'site-2', 'site-3')
UNKNOWN_FILES_KEYS = ('snapshot_id', 'items', 'total', 'offset', 'limit')


def baseline_snapshot(report: Report, label: str) -> str | None:
    '''Return the id of the newest catalog snapshot for an S1 baseline; None after a STATE finding when the catalog lists none.

    The matrix rows M4 and M5 (and O4 and O5 through params_ref) fix the baseline success for an EXISTING snapshot; the answer for a
    well-formed snapshot that does not exist is the separate case snapshot_id_unknown (revision 6, section 10.13), so a repository
    without a snapshot is a state for the baseline, never a verdict.
    '''
    kind, code, message, data = live.request('backup_snapshots', {})
    items = data.get('items', []) if kind == 'success' and isinstance(data, dict) else []
    if items:
        return str(items[0]['id'])
    report.state.append('%s: the catalog lists no snapshot (the baseline success of rows M4, M5, O4, O5 needs an existing snapshot; '
                        'the unknown-snapshot answer is the case snapshot_id_unknown, revision 6)' % label)
    return None


def unknown_snapshot_id() -> str:
    '''Return a well-formed snapshot id that no snapshot of the live catalog carries or abbreviates (case snapshot_id_unknown of rows M4, M5, O4, O5, C-K4, C-K5).'''
    kind, code, message, data = live.request('backup_snapshots', {'limit': 1000})
    items = data.get('items', []) if kind == 'success' and isinstance(data, dict) else []
    known = [str(item.get(key, '')).lower() for item in items if isinstance(item, dict) for key in ('id', 'short_id')]
    for candidate in UNKNOWN_SNAPSHOT_CANDIDATES:
        if not any(name and (name.startswith(candidate) or candidate.startswith(name)) for name in known):
            return candidate
    return 'f' * 64


def unknown_files_problems(data: object, snapshot_id: str) -> list[str]:
    '''Judge the M4 result of a well-formed unknown snapshot (revision 6, 10.13): {snapshot_id, items: [], total: 0, offset: 0, limit: 1000}.'''
    if not isinstance(data, dict) or sorted(data) != sorted(UNKNOWN_FILES_KEYS):
        return ['expected exactly the fields %s, got %s' % (list(UNKNOWN_FILES_KEYS), sorted(data) if isinstance(data, dict) else repr(data)[:80])]
    problems = []
    if data['snapshot_id'] != snapshot_id.lower():
        problems.append('snapshot_id %r differs from the request %r' % (data['snapshot_id'], snapshot_id.lower()))
    if data['items'] != []:
        problems.append('items %r is not the empty list' % (data['items'],))
    for key, wanted in (('total', 0), ('offset', 0), ('limit', 1000)):
        if type(data[key]) is not int or data[key] != wanted:
            problems.append('%s %r is not the integer %d' % (key, data[key], wanted))
    return problems


def baseline_site(report: Report, label: str) -> str | None:
    '''Return the id of an inventory site for an S1 baseline of backup_libraries_list (the first site that holds libraries, else the first site).

    The matrix row M9 fixes the baseline success for a site of the inventory; a well-formed site the inventory does not hold is the case
    site_id_invalid_3 and answers 404 SITE_NOT_FOUND, so an unknown site id is never a baseline input. None after a STATE finding when
    the inventory lists no site.
    '''
    kind, code, message, data = live.request('backup_sites_list', {'limit': 1000})
    sites = [str(item['site_id']) for item in (data.get('items', []) if kind == 'success' and isinstance(data, dict) else [])
             if isinstance(item, dict) and item.get('site_id')]
    for site in sites:
        k2, c2, m2, d2 = live.request('backup_libraries_list', {'site_id': site, 'limit': 1})
        if k2 == 'success' and isinstance(d2, dict) and d2.get('total'):
            return site
    if sites:
        return sites[0]
    report.state.append('%s: the discovery inventory lists no site (the baseline of row M9 needs a site of the inventory)' % label)
    return None


def unknown_site_id() -> str:
    '''Return a well-formed site id the live inventory does not hold (matrix case site_id_invalid_3, expect C404S).'''
    kind, code, message, data = live.request('backup_sites_list', {'limit': 1000})
    known = {str(item.get('site_id')) for item in (data.get('items', []) if kind == 'success' and isinstance(data, dict) else []) if isinstance(item, dict)}
    return next((site for site in UNKNOWN_SITE_CANDIDATES if site not in known), 'unknown-site-' + '0' * 8)



def site_cases(state) -> list[tuple[str, str, int, str, bool]]:
    """The M9 site_id cases that the client row C-K9 and the odbcli row O9 inherit through params_ref (revision 7, 10.14 (2) and 10.14.1).

    Each item is (case id, value, status code, message name, needs S1): the 300-character id passes the validation and no such site exists, so
    404 SITE_NOT_FOUND; the 301-character id and an id with a space are 400 INVALID_SITE_ID before the readiness gate; a well-formed site the
    inventory does not hold is 404 SITE_NOT_FOUND.
    """
    unknown = unknown_site_id() if state == 'S1' else UNKNOWN_SITE_CANDIDATES[0]
    return [('site_id_valid_1', 'q' * 300, 404, 'SITE_NOT_FOUND', True), ('site_id_invalid_1', 'q' * 301, 400, 'INVALID_SITE_ID', False),
            ('site_id_invalid_2', 'a b', 400, 'INVALID_SITE_ID', False), ('site_id_invalid_3', unknown, 404, 'SITE_NOT_FOUND', True)]
