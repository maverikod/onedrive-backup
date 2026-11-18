'''Shared helpers of the UI-VUE named checks (rows V1..V6 of the matrix, block UI-VUE).

The human client is a Vue 3 single page application served by nginx on the LAN (decision D5). Every action of it is an
adapter command over JSON-RPC POST /api/jsonrpc with the token T = base64(login:password) in X-API-Key (decisions D3, D7),
the same API the model, the Python client and odbcli use; /ws stays closed; a file is downloaded by the temporary uuid4
link /downloads/<export_id>/<filename>. The server HTML routes U1..U10 are removed with ui.py by the SPA (approval 5).

Findings are kept apart as in the B4 checks: PRODUCT (the SPA or the service breaks the contract, or the SPA is absent),
STATE (the case needs provisioned state or credentials) and ENVIRONMENT (the pipeline cannot reach or use what it needs).
A fourth kind, GAP, marks an assertion the approved matrix does not fix: it is never invented and never skipped, it names the
decision it waits for and keeps the check RED until the matrix fixes it.
'''

from __future__ import annotations

import http.client
import json
import re
import ssl
import subprocess
import urllib.parse
from pathlib import Path

from pipeline import b4base as base, b4server, credentials, live
from pipeline.environment import PipelineEnvError, endpoint
from pipeline.report import Report

ROOT = base.ROOT
LAN_BASE = 'ONEDRIVE_BACKUP_LAN_URL'
LEGACY_MARKERS = ('csrf', '/ui/login')
REFERENCE = re.compile(r"(?:src|href)\s*=\s*[\"']([^\"']+)[\"']", re.I)
SCRIPT_TAG = re.compile(r'<script[^>]*\ssrc\s*=', re.I)
KEY_MARKERS = ('BEGIN PRIVATE KEY', 'BEGIN RSA PRIVATE KEY', 'BEGIN EC PRIVATE KEY', 'BEGIN OPENSSL PRIVATE KEY')
SECRET_FILES = ('.env', '.key', '.pem', '.crt', '.crl')
ASSET_LIMIT = 20
ZERO = base.ZERO_ID

# Removed server HTML routes of the matrix rows U1..U10 (planned_change: removed with ui.py by the Vue SPA, D7, approval 5).
REMOVED_UI = {
    'U1': ('GET', '/ui'), 'U2': ('GET', '/ui/login'), 'U3': ('POST', '/ui/login'), 'U4': ('POST', '/ui/logout'),
    'U5': ('GET', '/ui/'), 'U6': ('GET', '/ui/snapshots/abcdef12'), 'U7': ('POST', '/ui/export'),
    'U8': ('GET', '/ui/exports/' + ZERO), 'U9': ('GET', '/ui/exports/%s/download' % ZERO),
    'U10': ('POST', '/ui/exports/%s/delete' % ZERO),
}

# MATRIX GAPS: what the approved matrix (sections 1-10, revision 4b) does not fix. Each is listed in the answer of the unit.
GAPS = {
    'G1': 'SPA address: ONEDRIVE_BACKUP_LAN_URL_DEV/_PROD are empty and declared pending in pipeline/endpoints.env; no nginx host, port or scheme is fixed (sections 8.1 D5, 8.2 Q1/OQ-3/OQ-6, 10)',
    'G2': 'LAN transport: which certificate nginx presents, which CA the pipeline trusts, and whether the LAN endpoint demands a browser client certificate (7.4 text for V1 says served only after mTLS, D5 says mTLS for the browser later, OQ-6)',
    'G3': 'headers: the exact Content-Security-Policy and no-store values nginx must send (V1 names only CSP and no-store; 7.4 only says the former default-src none must be widened for the SPA scripts)',
    'G4': 'routes: SPA deep-link behaviour (history or hash router, fallback to index.html) and what the LAN endpoint answers for the removed /ui* routes and for unknown paths (not stated anywhere)',
    'G5': 'SPA command manifest: where the SPA sources live (Q13 open) and in which format the commands and parameters it uses are declared, so V3 can compare them with the live help',
    'G6': 'SPA build: build command and tool (Node stage, Q13/OQ-6), artifact location, how the built SPA exposes its version, and what reproducible means (byte-identical artifacts, V6)',
    'G7': 'headless runner: which browser driver runs the SPA (planner TODO f5c80e13 names Playwright), where it runs (the pipeline venv has none), and the selectors or test ids of login form, menu and pages (V2, V4)',
    'G8': 'download authorization through nginx: OQ-5 is open (nginx adds X-API-Key to /downloads/ or the SPA uses fetch and blob), so the answer to a tokenless browser GET of the link is not fixed',
    'G9': 'page equals command result (V4): which fields of each command result a page must show and in which rendering, and which parameters the SPA sends for sites, libraries (site_id, query, paging) and discovery pages',
    'G10': 'vue_polling: 7.4 lists a vue_polling check (G4 polling) but the matrix has no V row and no registry entry for it, and Q11 says no push events while /ws is closed; the planner TODO fee58a27 polls the removed REST /api/v1 routes',
    'G11': 'answer of a removed server HTML route U1..U10 on the service: the matrix says removed but fixes no status; the checks reuse the REST rule (framework 404 {detail: Not Found})',
}


class LanError(RuntimeError):
    '''The SPA endpoint of the LAN does not answer the way a deployed nginx would.'''


def gap(report: Report, gap_id: str, case: str) -> None:
    '''Record a pending assertion blocked by a matrix gap; the check stays RED.'''
    report.gap.append('%s: not asserted, blocked by MATRIX GAP %s: %s' % (case, gap_id, GAPS[gap_id]))


def tracked_files() -> list[str] | None:
    '''Return the git-tracked files of the checkout, or None when git cannot list them.'''
    done = subprocess.run(['git', 'ls-files'], cwd=ROOT, capture_output=True, text=True)
    return done.stdout.splitlines() if done.returncode == 0 else None


def spa_files(report: Report, label: str) -> list[str]:
    '''Return the tracked Vue SPA files (*.vue and package.json); an empty list is a PRODUCT finding (no SPA exists).'''
    files = tracked_files()
    if files is None:
        report.env.append('%s: git cannot list the tracked files of the checkout' % label)
        return []
    found = [item for item in files if item.endswith('.vue') or Path(item).name == 'package.json']
    if not found:
        report.product.append('%s: the repository tracks no Vue SPA source (no *.vue file and no package.json): the frontend does not exist yet (block UI-VUE, Q13)' % label)
    return found


def deployed(report: Report, label: str) -> str | None:
    '''Return the SPA endpoint URL of this environment, or None with a PRODUCT finding when the SPA is not deployed.'''
    try:
        return endpoint(LAN_BASE)
    except PipelineEnvError as exc:
        report.product.append('%s: the SPA is not deployed, %s (nginx and the Vue SPA arrive with block UI-VUE)' % (label, exc))
        return None


def lan_request(root: str, method: str, path: str, headers: dict | None = None, body: bytes | None = None) -> tuple[int, dict, bytes]:
    '''One request to the SPA endpoint; return (status, lower-cased headers, body) or raise LanError (or live.LiveUnreachable without TLS material).'''
    parts = urllib.parse.urlsplit(root)
    if parts.scheme not in ('http', 'https') or not parts.hostname:
        raise LanError('the endpoint value is not an http(s) URL')
    context = live._context() if parts.scheme == 'https' else None
    conn = None
    try:
        if context is not None:
            conn = http.client.HTTPSConnection(parts.hostname, parts.port or 443, context=context, timeout=30)
        else:
            conn = http.client.HTTPConnection(parts.hostname, parts.port or 80, timeout=30)
        conn.request(method, parts.path.rstrip('/') + path, body=body, headers=headers or {})
        reply = conn.getresponse()
        return reply.status, {k.lower(): v for k, v in reply.getheaders()}, reply.read()
    except (OSError, ssl.SSLError, http.client.HTTPException) as exc:
        raise LanError('%s %s failed: %s: %s' % (method, path, type(exc).__name__, exc))
    finally:
        if conn is not None:
            conn.close()


def lan_try(report: Report, label: str, root: str, method: str, path: str, headers: dict | None = None, body: bytes | None = None):
    '''lan_request that turns a failure into a finding and returns None.'''
    try:
        return lan_request(root, method, path, headers, body)
    except LanError as exc:
        report.product.append('%s: the SPA endpoint does not answer: %s' % (label, exc))
    except live.LiveUnreachable as exc:
        report.env.append('%s: not executed, %s' % (label, exc))
    return None


def lan_rpc(report: Report, label: str, root: str, command: str, params: dict | None, token: str | None):
    '''POST one JSON-RPC command through the SPA endpoint the way the SPA does; return (status, decoded body or None) or None.'''
    headers = dict(base.JSON_HEADERS)
    if token is not None:
        headers[base.TOKEN_HEADER] = token
    body = json.dumps({'jsonrpc': '2.0', 'method': command, 'params': params or {}, 'id': 1}).encode('utf-8')
    got = lan_try(report, label, root, 'POST', '/api/jsonrpc', headers, body)
    if got is None:
        return None
    try:
        return got[0], json.loads(got[2])
    except ValueError:
        return got[0], None


def removed_ui(report: Report, rows: tuple[str, ...]) -> None:
    '''Rows U<n>: the server HTML route is removed from the service (framework 404), proven against the deployed service.'''
    for row in rows:
        method, path = REMOVED_UI[row]
        label = '%s %s %s' % (row, method, path)
        got = b4server._try(report, label, base.probe, method, path, b'' if method == 'POST' else None)
        if got is None or b4server._gated(report, label, got[0], True):
            continue
        if got[0] != 404 or got[2].strip() != base.FRAMEWORK_404:
            report.product.append('%s: answered %d %s, expected the framework 404 {detail: Not Found} (the server HTML route is removed with ui.py by the Vue SPA, D7, approval 5); still registered at %s'
                                  % (label, got[0], base.brief(got[2]), base.src_line('src/onedrive_api/ui.py', path.rstrip('/') or path)))


def scan_secrets(report: Report, label: str, files: list[str]) -> None:
    '''PRODUCT finding for a file that holds a run credential, a private key marker or is a key, certificate or env file; values are never printed.'''
    secrets = [item for item in credentials.secret_values() if item]
    for item in files:
        if Path(item).name.lower() == '.env' or item.lower().endswith(SECRET_FILES[1:]):
            report.product.append('%s: %s is a secret or certificate file inside the SPA tree' % (label, item))
            continue
        try:
            text = (ROOT / item).read_text(encoding='utf-8', errors='replace')
        except OSError:
            continue
        if any(marker in text for marker in KEY_MARKERS):
            report.product.append('%s: %s holds a private key marker' % (label, item))
        if any(value in text for value in secrets):
            report.product.append('%s: %s holds a run credential (login, password or token T)' % (label, item))
