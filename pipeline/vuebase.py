'''Shared helpers of the UI-VUE named checks (rows V1..V8 of the matrix, blocks UI-VUE, TRANSPORT-REV8 and UI-ROUTES).

The human client is a Vue 3 single page application MOUNTED AS STATIC FILES BY THE SERVICE ITSELF (revision 8, 10.15.6) on the same
origin as /api/jsonrpc and /downloads, over server-auth HTTPS at the LAN URL of pipeline/endpoints.env; there is no nginx, no second
image and no browser client certificate. The service is open for now, so every action is an adapter command over JSON-RPC POST
/api/jsonrpc without a credential (an optional key goes in X-API-Key only after a 401); /ws is native; a file is downloaded by the
temporary uuid4 link /downloads/<export_id>/<filename>. The server HTML routes U1..U10 are removed with ui.py by the SPA (approval 5).

Findings are kept apart as in the B4 checks: PRODUCT (the SPA or the service breaks the contract, or the SPA is absent),
STATE (the case needs provisioned state) and ENVIRONMENT (the pipeline cannot reach or use what it needs).
Section 10.18 (approved 2026-11-20) names the routes, the nav ids, the test ids and the export, logout and poll controls; the headless driver of
decision G7 (Playwright for Python, pinned in pipeline/requirements.txt, Chromium and Node 22 on the verification host) asserts them
(pipeline.vuebrowser, pipeline.vueroutes, pipeline.vuebuild); a missing driver is an ENVIRONMENT finding.
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
SPA_FILES = {'/assets/app.js': ('javascript',), '/assets/app.css': ('css',), '/command-manifest.json': ('json',)}
CSP_EXPECTED = {'default-src': "'none'", 'script-src': "'self'", 'style-src': "'self'", 'img-src': "'self' data:", 'font-src': "'self'",
                'connect-src': "'self'", 'base-uri': "'none'", 'form-action': "'none'"}
CSP_FORBIDDEN = ("'unsafe-inline'", "'unsafe-eval'", '*', 'http:', 'https:')
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


class LanError(RuntimeError):
    '''The SPA endpoint of the LAN does not answer the way the service mount must.'''


def tracked_files() -> list[str] | None:
    '''Return the git-tracked files of the checkout, or None when git cannot list them.'''
    done = subprocess.run(['git', '-c', 'safe.directory=%s' % ROOT, 'ls-files'], cwd=ROOT, capture_output=True, text=True)
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
        report.product.append('%s: the SPA is not served at the LAN URL, %s (the service mounts the SPA, revision 8)' % (label, exc))
        return None


def lan_request(root: str, method: str, path: str, headers: dict | None = None, body: bytes | None = None) -> tuple[int, dict, bytes]:
    '''One request to the SPA endpoint; return (status, lower-cased headers, body) or raise LanError (or live.LiveUnreachable without TLS material).'''
    parts = urllib.parse.urlsplit(root)
    if parts.scheme not in ('http', 'https') or not parts.hostname:
        raise LanError('the endpoint value is not an http(s) URL')
    context = live._context(client_cert=False) if parts.scheme == 'https' else None
    conn: http.client.HTTPConnection | None = None
    try:
        if context is not None:
            conn = http.client.HTTPSConnection(parts.hostname, parts.port or 443, context=context, timeout=30)
        else:
            conn = http.client.HTTPConnection(parts.hostname, parts.port or 80, timeout=30)
        conn.request(method, urllib.parse.quote(parts.path.rstrip('/') + path, safe='/%?=&'), body=body, headers=headers or {})
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
    '''Rows U<n> (revision 8, G4, 10.15.9.3 and the reconciliation identity.reconciliations.removed_routes_mount_statuses): the removed server HTML route is not served by the mount.

    A GET answers 404 from the mount. A non-GET method (POST, PUT, DELETE) on the mount answers 404 or 405 (Starlette StaticFiles
    answers 405 to a method it does not serve). Never 2xx, never 3xx, never 401, never the index page or the legacy HTML, no Set-Cookie.'''
    for row in rows:
        method, path = REMOVED_UI[row]
        label = '%s %s %s' % (row, method, path)
        got = b4server._try(report, label, base.probe, method, path, b'' if method == 'POST' else None, None, False)
        if got is None:
            continue
        status, headers, body = got
        text = body.decode('utf-8', 'replace').lower()
        admitted = (404,) if method == 'GET' else (404, 405)
        if status not in admitted:
            report.product.append('%s: answered %d %s, expected %s from the SPA mount (the server HTML route is removed with ui.py by the Vue SPA, never 2xx, 3xx or 401)'
                                  % (label, status, base.brief(body), ' or '.join(str(item) for item in admitted)))
        if '<script' in text or 'id="app"' in text or any(marker in text for marker in LEGACY_MARKERS):
            report.product.append('%s: the body is the SPA index page or the legacy server HTML, expected the plain answer of the mount' % label)
        if 'set-cookie' in headers or 'location' in headers:
            report.product.append('%s: the answer carries %s, expected no cookie and no redirect' % (label, 'Set-Cookie' if 'set-cookie' in headers else 'Location'))


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
            report.product.append('%s: %s holds the run password' % (label, item))
