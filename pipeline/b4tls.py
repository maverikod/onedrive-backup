'''Revision 8 named checks of the transport: tls_server_auth (PX10) and adapter_only_transport (AU5).

tls_server_auth is live against the production service: server-auth HTTPS, no client certificate is requested or checked.
adapter_only_transport is static: the project owns no network, TLS, route-filter, middleware or authentication code; the transport is
the adapter configuration alone (decision 2026-11-19: "Только на базе адаптера", "Убрать всё сразу"), the project CLAUDE.md standards
carry the revision 8 text, and the SPA is mounted by exactly one StaticFiles mount. Findings are kept apart as PRODUCT, STATE and
ENVIRONMENT.
'''

from __future__ import annotations

import ast
import http.client
import socket
import ssl
import urllib.parse

from pipeline import b4base as base, live
from pipeline.environment import PipelineEnvError, endpoint
from pipeline.report import Report

LAN_BASE = 'ONEDRIVE_BACKUP_LAN_URL'
ALIAS = 'onedrive-backup'
SRC = base.ROOT / 'src'


def _target(report: Report, label: str, name: str) -> tuple[str, int] | None:
    '''Return (host, port) of an endpoint, or None after a PRODUCT finding (the endpoint is not served) or ENVIRONMENT finding.'''
    try:
        parts = urllib.parse.urlsplit(endpoint(name))
    except PipelineEnvError as exc:
        report.product.append('%s: %s' % (label, exc))
        return None
    return parts.hostname or '', parts.port or 443


def _health(context: ssl.SSLContext, host: str, port: int, name: str | None = None) -> str:
    '''GET /health over TLS; return "200" or a one-line description of the refusal. name is the host name the certificate must match.'''
    try:
        with socket.create_connection((host, port), timeout=20) as sock:
            with context.wrap_socket(sock, server_hostname=name or host) as tls:
                conn = http.client.HTTPSConnection(host, port, timeout=20)
                conn.sock = tls
                conn.request('GET', '/health')
                return str(conn.getresponse().status)
    except (OSError, ssl.SSLError, http.client.HTTPException) as exc:
        hint = ' (the listener closed the connection after the handshake: it still demands a client certificate)' if isinstance(exc, (BrokenPipeError, ConnectionResetError)) else ''
        return '%s: %s%s' % (type(exc).__name__, str(exc)[:110], hint)


def tls_server_auth() -> None:
    '''PX10 (revision 8): a handshake WITHOUT a client certificate succeeds, the certificate matches the LAN IP and the docker alias, TLS below 1.2 and plain HTTP are refused, a certificate offered anyway changes nothing.'''
    report = Report()
    try:
        bare = live._context(client_cert=False)
    except live.LiveUnreachable as exc:
        report.env.append('PX10 the project CA is not readable: %s' % exc)
        report.finish('tls_server_auth')
        return
    targets = [('service URL', _target(report, 'PX10 the service URL', 'ONEDRIVE_BACKUP_URL')), ('LAN URL', _target(report, 'PX10 the LAN URL (host 8443 -> container 8050)', LAN_BASE))]
    service = targets[0][1]
    for label, target in targets:
        if target is None:
            continue
        got = _health(bare, target[0], target[1])
        if got != '200':
            report.product.append('PX10 (1) TLS without a client certificate to the %s %s:%d: %s, expected GET /health 200 (server.protocol must be https, no client certificate requested)' % (label, target[0], target[1], got))
    if service is not None:
        lan = _target(report, 'PX10 the LAN URL', LAN_BASE)
        for name in (ALIAS, lan[0] if lan else ALIAS):
            got = _health(bare, service[0], service[1], name)
            if got != '200':
                report.product.append('PX10 (2) the server certificate verified against the project CA for the name %s: %s, expected 200 (SAN must hold the alias %s and the LAN IP of the LAN URL)' % (name, got, ALIAS))
        old = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
        try:
            old.minimum_version = ssl.TLSVersion.TLSv1
            old.maximum_version = ssl.TLSVersion.TLSv1_1
            old.check_hostname = False
            old.verify_mode = ssl.CERT_NONE
        except (ValueError, ssl.SSLError):
            report.info.append('PX10 (3) this OpenSSL cannot offer TLS below 1.2: the case is not constructible here')
        else:
            got = _health(old, service[0], service[1])
            if got == '200':
                report.product.append('PX10 (3) a TLS 1.0/1.1 handshake was served, expected a refusal (TLS >= 1.2 only)')
        try:
            with socket.create_connection(service, timeout=10) as sock:
                sock.sendall(b'GET /health HTTP/1.0\r\n\r\n')
                data = sock.recv(200)
        except OSError:
            data = b''
        if b'HTTP/' in data:
            report.product.append('PX10 (4) a plain HTTP request to the TLS port got an HTTP answer %r, expected a refusal or a closed connection' % data[:40])
        ca, cert, key = live._tls_files()
        if cert and key:
            with_cert = _health(live._context(client_cert=True), service[0], service[1])
            without = _health(bare, service[0], service[1])
            if with_cert != without:
                report.product.append('PX10 (5) a client certificate offered anyway changes the answer: with %s, without %s' % (with_cert, without))
    report.finish('tls_server_auth')


# Names whose use in project Python is project-owned transport, TLS, route-filter, middleware or authentication code.
FORBIDDEN_NAMES = ('ProxyTrustMiddleware', 'ALLOWED_ROUTES', 'add_middleware', 'SSLContext', 'CERT_REQUIRED', 'verify_client', 'b64encode',
                   'secure_auth', 'api_token', 'tls_server_settings', '_validate_mtls_config', 'CREDENTIALS_FILE_ENV', 'DEFAULT_CREDENTIALS_FILE')
FORBIDDEN_STRINGS = ('api-credentials', 'proxy_trust')


def _docstrings(tree: ast.AST) -> set[int]:
    found: set[int] = set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)) and node.body:
            first = node.body[0]
            if isinstance(first, ast.Expr) and isinstance(first.value, ast.Constant) and isinstance(first.value.value, str):
                found.add(id(first.value))
    return found


def _scan_file(path, report: Report) -> int:
    '''Report forbidden project-owned transport code in one module; return the number of StaticFiles mounts it makes.'''
    rel = path.relative_to(base.ROOT)
    try:
        tree = ast.parse(path.read_text(encoding='utf-8'))
    except (OSError, SyntaxError) as exc:
        report.env.append('%s: cannot be parsed: %s' % (rel, exc))
        return 0
    skip = _docstrings(tree)
    mounts = 0
    for node in ast.walk(tree):
        name = node.id if isinstance(node, ast.Name) else node.attr if isinstance(node, ast.Attribute) else node.name if isinstance(node, (ast.FunctionDef, ast.ClassDef)) else None
        if name in FORBIDDEN_NAMES:
            report.product.append('%s:%d: project-owned transport/TLS/auth code %s (revision 8: removed, nothing replaces it, the adapter configuration decides)' % (rel, node.lineno, name))
        elif isinstance(node, ast.Constant) and isinstance(node.value, str) and id(node) not in skip and any(item in node.value for item in FORBIDDEN_STRINGS):
            report.product.append('%s:%d: the string %r names a removed transport/auth input' % (rel, node.lineno, node.value[:50]))
        elif isinstance(node, ast.Assign) and any(isinstance(t, ast.Attribute) and t.attr == 'routes' for t in node.targets):
            report.product.append('%s:%d: a route filter (assignment to .routes) is project-owned transport code' % (rel, node.lineno))
        elif isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and node.func.attr == 'mount':
            mounts += 1
    return mounts


# The project CLAUDE.md standards text of revision 8 (10.15.9.5 (1)-(4), (6)); item (5) is asserted by data_dir_defaults D4.
CLAUDE_NEW = (
    'After image build, run python -m pipeline smoke_https.',
    'Transport is HTTPS with server authentication only, set exclusively by the mcp-proxy-adapter config (server.protocol https, server certificate from the project CA); there is no client certificate, no nginx and no project-owned network, TLS, route-filter, middleware or authentication code.',
    'When the service is exposed outside the LAN the SAME adapter config switches to mtls (trusted CA, one server/client certificate pair, revocation by MCP Proxy).',
    'The service port is published on the LAN ({lan} -> container port 8050; the MCP Proxy reaches it by the docker alias onedrive-backup).',
    'Authentication is off for now (adapter auth.use_token false).',
    'The Vue 3 + Vite + TypeScript SPA (frontend/) is built by a Node stage of the service Dockerfile and mounted as static files by the service itself on the same origin as /api/jsonrpc; there is no second image.',
    'Python client exposes the complete adapter command (JSON-RPC) surface and verifies downloaded file size and SHA256 before atomically replacing the output.',
)
CLAUDE_OLD = ('smoke_mtls', 'mTLS uses trusted CA and one server/client certificate pair; revocation policy is managed by MCP Proxy. FastAPI is restricted to the internal Docker network.',
              'complete application REST surface')


def adapter_only_transport() -> None:
    '''AU5 (revision 8, PP-D1a): no project-owned transport/TLS/auth code in src/, exactly one StaticFiles mount, and the CLAUDE.md standards text of revision 8.'''
    report = Report()
    mounts = 0
    for path in sorted(SRC.rglob('*.py')):
        mounts += _scan_file(path, report)
    if mounts != 1:
        report.product.append('src/: %d app.mount call(s), expected exactly ONE StaticFiles mount of the SPA (the only admitted project hooks are command registration, set_public_download_resolver, the transfer config and that mount)' % mounts)
    text = (base.ROOT / 'CLAUDE.md').read_text(encoding='utf-8')
    lan = _target(report, 'CLAUDE.md standards: the LAN URL', LAN_BASE)
    for line in CLAUDE_NEW:
        line = line.replace('{lan}', ''.join(('https', '://', lan[0], ':', str(lan[1]))) if lan else '{lan}')
        if line not in text:
            report.product.append('CLAUDE.md: the revision 8 standards text is missing: %r' % line[:90])
    for line in CLAUDE_OLD:
        if line in text:
            report.product.append('CLAUDE.md: the superseded standards text is still present: %r' % line[:90])
    report.finish('adapter_only_transport')
