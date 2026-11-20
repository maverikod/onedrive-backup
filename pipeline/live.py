'''Interim live transport of the pipeline to the production service (replaced by the B4 client).

The service is production-only, so every live check talks to the production server named in
pipeline/endpoints.env (ONEDRIVE_BACKUP_URL) with one JSON-RPC request per command over TLS. Revision 8 (10.15): the listener is
server-auth HTTPS and the CA is the only mandatory TLS file; a client certificate is OPTIONAL and ALL-OR-NONE (cert and key
together, https without them, mtls with them). The TLS material is the project own ignored certificate tree under
mtls-certs/for-proxy (never committed); each file can be overridden with ONEDRIVE_BACKUP_CA, ONEDRIVE_BACKUP_CLIENT_CERT and
ONEDRIVE_BACKUP_CLIENT_KEY. A service that cannot be reached raises LiveUnreachable, which the checks report as an ENVIRONMENT
result, separately from a product result.
'''

from __future__ import annotations

import json
import os
import ssl
import urllib.error
import urllib.request
from pathlib import Path

from pipeline import credentials
from pipeline.environment import PipelineEnvError, endpoint

ROOT = Path(__file__).resolve().parents[1]
CERT_TREE = ROOT / 'mtls-certs' / 'for-proxy'
BASE_ENDPOINT = 'ONEDRIVE_BACKUP_URL'
TOKEN_HEADER = 'X-API-Key'


class LiveUnreachable(RuntimeError):
    '''The production service cannot be reached from this pipeline run (environment RED).'''


def _tls_files() -> tuple[str, str | None, str | None]:
    '''Return (ca, cert, key); cert and key are both set (mtls) or both None (https): they are all-or-none (relation R26).'''
    ca = os.environ.get('ONEDRIVE_BACKUP_CA') or str(CERT_TREE / 'ca' / 'ca.crt')
    cert = os.environ.get('ONEDRIVE_BACKUP_CLIENT_CERT') or str(CERT_TREE / 'issued' / 'onedrive-backup.crt')
    key = os.environ.get('ONEDRIVE_BACKUP_CLIENT_KEY') or str(CERT_TREE / 'issued' / 'onedrive-backup.key')
    if not (Path(cert).is_file() and Path(key).is_file()):
        return ca, None, None
    return ca, cert, key


def _context(client_cert: bool = True) -> ssl.SSLContext:
    '''TLS context: the CA is mandatory; the client certificate pair is loaded only when it exists and client_cert is true.'''
    ca, cert, key = _tls_files()
    if not Path(ca).is_file():
        raise LiveUnreachable('TLS material is not readable: ' + ca)
    try:
        context = ssl.create_default_context(cafile=ca)
        if client_cert and cert and key:
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
    '''Return the X-API-Key value of the run, the optional run password as it is (row PX11), or None when none is configured.'''
    return credentials.token()


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
