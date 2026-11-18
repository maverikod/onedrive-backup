'''Interim live transport of the pipeline to the production service (replaced by the B4 client).

The service is production-only, so every live check talks to the production server named in
pipeline/endpoints.env (ONEDRIVE_BACKUP_URL) with one JSON-RPC request per command over mTLS.
The TLS material is the project own ignored certificate tree under mtls-certs/for-proxy (never
committed); each file can be overridden with ONEDRIVE_BACKUP_CA, ONEDRIVE_BACKUP_CLIENT_CERT and
ONEDRIVE_BACKUP_CLIENT_KEY. A service that cannot be reached raises LiveUnreachable, which the
checks report as an ENVIRONMENT result, separately from a product result.
'''

from __future__ import annotations

import base64
import json
import os
import ssl
import urllib.error
import urllib.request
from pathlib import Path

from pipeline.environment import PipelineEnvError, endpoint

ROOT = Path(__file__).resolve().parents[1]
CERT_TREE = ROOT / 'mtls-certs' / 'for-proxy'
BASE_ENDPOINT = 'ONEDRIVE_BACKUP_URL'
TOKEN_HEADER = 'X-API-Key'


class LiveUnreachable(RuntimeError):
    '''The production service cannot be reached from this pipeline run (environment RED).'''


def _tls_files() -> tuple[str, str, str]:
    return (os.environ.get('ONEDRIVE_BACKUP_CA') or str(CERT_TREE / 'ca' / 'ca.crt'),
            os.environ.get('ONEDRIVE_BACKUP_CLIENT_CERT') or str(CERT_TREE / 'issued' / 'onedrive-backup.crt'),
            os.environ.get('ONEDRIVE_BACKUP_CLIENT_KEY') or str(CERT_TREE / 'issued' / 'onedrive-backup.key'))


def _context() -> ssl.SSLContext:
    ca, cert, key = _tls_files()
    missing = [item for item in (ca, cert, key) if not Path(item).is_file()]
    if missing:
        raise LiveUnreachable('TLS material is not readable: ' + ', '.join(missing))
    try:
        context = ssl.create_default_context(cafile=ca)
        context.load_cert_chain(cert, key)
    except (ssl.SSLError, OSError) as exc:
        raise LiveUnreachable('cannot load the TLS material: %s: %s' % (type(exc).__name__, exc))
    return context


def base_url() -> str:
    '''Return the production service URL from endpoints.env for the resolved environment.'''
    try:
        return endpoint(BASE_ENDPOINT)
    except PipelineEnvError as exc:
        raise LiveUnreachable('no service endpoint: %s' % exc)


def token() -> str | None:
    '''Return the interim token T = base64(login:password) of the run credentials (decision D3), or None.'''
    given = os.environ.get('ONEDRIVE_BACKUP_TOKEN')
    if given:
        return given
    login, password = os.environ.get('ONEDRIVE_BACKUP_LOGIN'), os.environ.get('ONEDRIVE_BACKUP_PASSWORD')
    if login and password:
        return base64.b64encode((login + ':' + password).encode('utf-8')).decode('ascii')
    return None


def call(command: str, params: dict | None = None, timeout: int = 60) -> dict:
    '''Send one JSON-RPC request to /api/jsonrpc and return the decoded reply object.'''
    url = base_url().rstrip('/') + '/api/jsonrpc'
    body = json.dumps({'jsonrpc': '2.0', 'method': command, 'params': params or {}, 'id': 1}).encode('utf-8')
    headers = {'Content-Type': 'application/json'}
    if token():
        headers[TOKEN_HEADER] = token()
    request = urllib.request.Request(url, data=body, method='POST', headers=headers)
    context = _context()
    status = 200
    try:
        with urllib.request.urlopen(request, context=context, timeout=timeout) as reply:
            raw = reply.read()
    except urllib.error.HTTPError as exc:
        status, raw = exc.code, exc.read()
    except (urllib.error.URLError, OSError, ssl.SSLError) as exc:
        raise LiveUnreachable('POST %s failed: %s: %s' % (url, type(exc).__name__, exc))
    try:
        decoded = json.loads(raw)
    except ValueError:
        raise LiveUnreachable('POST %s answered HTTP %d with a body that is not JSON: %r' % (url, status, raw[:200]))
    if not isinstance(decoded, dict):
        raise LiveUnreachable('POST %s answered HTTP %d with a non-object JSON body' % (url, status))
    return decoded


def classify(reply: dict) -> tuple[str, object, str, object]:
    '''Return (kind, code, message, data); kind is success, command_error, rpc_error or malformed.'''
    error = reply.get('error')
    if isinstance(error, dict):
        return 'rpc_error', error.get('code'), str(error.get('message', '')), error.get('data') or {}
    result = reply.get('result')
    if isinstance(result, dict) and result.get('success') is False:
        detail = result.get('error') or {}
        return 'command_error', detail.get('code'), str(detail.get('message', '')), {}
    if isinstance(result, dict) and result.get('success') is True:
        return 'success', None, '', result.get('data', result)
    return 'malformed', None, json.dumps(reply)[:300], {}


def request(command: str, params: dict | None = None) -> tuple[str, object, str, object]:
    '''Call one command and classify the reply.'''
    return classify(call(command, params))


def service_state() -> str:
    '''Return S0 when the service refuses with 503 (scaffold, mount, repository or secrets), S1 on success.'''
    kind, code, message, _ = request('backup_snapshots', {})
    if kind == 'success':
        return 'S1'
    if kind == 'command_error' and code == 503:
        return 'S0'
    return 'unknown: %s %s %s' % (kind, code, message)
