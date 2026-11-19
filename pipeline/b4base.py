'''Shared helpers of the B4 named checks (client parity, download, authentication, route surface).

User decisions of 2026-11-18 that these checks encode: (1) the server API is the set of mcp-proxy-adapter
commands over JSON-RPC and the Python client is a thin wrapper over the adapter JsonRpcClient; (2) odbcli is a
console command built on that client; (3) download by a temporary uuid4 link and by the client through the
adapter transfer service, size and SHA256 verified; (4) REST /api/v1/* removed; (5) interim authentication
is login and password from the server configuration, carried as the token T = base64(login:password) in
the X-API-Key header (the dynamic adapter token is not in scope); (6) /ws stays closed; (7) the live version
equals VERSION.

The pipeline run holds the credentials only as ONEDRIVE_BACKUP_LOGIN and ONEDRIVE_BACKUP_PASSWORD, read through
pipeline.credentials (a git-ignored 0600 env file named by ONEDRIVE_BACKUP_CREDENTIALS_FILE, or the same two variables in the
environment of the run). Nothing of it is committed. A case that needs them and does not find them is RED as STATE or
ENVIRONMENT (R17), never PRODUCT and never skipped.
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
    '''Return the token header of the run credentials, or an empty mapping.'''
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


def baseline_snapshot(report: Report, label: str) -> str | None:
    '''Return the id of the newest catalog snapshot for an S1 baseline; None after a STATE finding when the catalog lists none.

    The matrix rows M4 and M5 (and O4 and O5 through params_ref) fix the baseline success for an existing snapshot and fix
    no answer for a well-formed unknown one (MATRIX GAP), so a repository without a snapshot is a state, never a verdict.
    '''
    kind, code, message, data = live.request('backup_snapshots', {})
    items = data.get('items', []) if kind == 'success' and isinstance(data, dict) else []
    if items:
        return str(items[0]['id'])
    report.state.append('%s: the catalog lists no snapshot (the matrix fixes the baseline success for an existing snapshot only; an unknown snapshot has no declared answer: MATRIX GAP rows M4, M5, O4, O5)' % label)
    return None
