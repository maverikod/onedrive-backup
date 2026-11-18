'''B4 named checks of the MCP Proxy peer: proxy_peer_auth (AU4) and proxy_trust_independent (AU5, relation R18).

Decision U2 of 2026-11-18: the MCP Proxy peer is admitted on mTLS alone, with NO token, on every route it reaches, whether or
not the api-credentials secret exists; the token T is required only from direct peers (odbcli, Python client, Vue, pipeline).
The decision uses the transport peer identity only, never request headers, and with no configured proxy identity nobody is
admitted without a token (fail closed). Findings are kept apart as PRODUCT, STATE and ENVIRONMENT.

proxy_peer_auth runs the real path of every MCP client: the MCP interface of the shared production proxy, no token from the
pipeline side. proxy_trust_independent starts DISPOSABLE instances of the deployed image on the host (own name, own network,
own CA, no production volume), one per secret state, and presents a peer that carries the configured proxy identity versus an
ordinary peer; it must run as root on the host in the manner of smoke_mtls. A missing prerequisite is RED [ENVIRONMENT].
'''

from __future__ import annotations

import json
import os
import secrets
import shutil
import subprocess
import sys
import tempfile
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

from pipeline import b4base as base, credentials, live
from pipeline.environment import PipelineEnvError, endpoint
from pipeline.report import Report

IMAGE_NAME = 'vasilyvz/onedrive-backup'
PROBE_SOURCE = base.ROOT / 'pipeline' / 'peer_probe.py'
START_SECONDS = 90


class McpError(RuntimeError):
    '''The MCP interface of the proxy could not be used.'''


def _message(text: str) -> dict:
    '''Return the JSON-RPC message of an MCP reply (plain JSON or one server-sent event).'''
    body = text.strip()
    if body.startswith('{'):
        return json.loads(body)
    for line in body.splitlines():
        if line.startswith('data:'):
            return json.loads(line[len('data:'):].strip())
    raise McpError('the reply holds no JSON message: %r' % body[:120])


class McpSession:
    '''Minimal MCP streamable-HTTP client: initialize, then tools/call. It sends no credentials of any kind.'''

    HEADERS = {'Content-Type': 'application/json', 'Accept': 'application/json, text/event-stream'}

    def __init__(self, url: str) -> None:
        self.url, self.sid, self.counter = url, None, 0

    def _post(self, body: dict) -> str:
        headers = dict(self.HEADERS)
        if self.sid:
            headers['Mcp-Session-Id'] = self.sid
        request = urllib.request.Request(self.url, data=json.dumps(body).encode('utf-8'), headers=headers, method='POST')
        try:
            with urllib.request.urlopen(request, timeout=90) as reply:
                self.sid = reply.headers.get('Mcp-Session-Id') or self.sid
                return reply.read().decode('utf-8', 'replace')
        except urllib.error.HTTPError as exc:
            raise McpError('HTTP %d %s' % (exc.code, exc.read()[:120].decode('utf-8', 'replace')))
        except (urllib.error.URLError, OSError, ValueError) as exc:
            raise McpError('%s: %s' % (type(exc).__name__, exc))

    def _call(self, method: str, params: dict) -> dict:
        self.counter += 1
        try:
            message = _message(self._post({'jsonrpc': '2.0', 'id': self.counter, 'method': method, 'params': params}))
        except ValueError as exc:
            raise McpError('the reply is not JSON: %s' % exc)
        if 'error' in message:
            raise McpError('%s: %s' % (method, str(message['error'])[:160]))
        return message.get('result') or {}

    def open(self) -> None:
        self._call('initialize', {'protocolVersion': '2025-03-26', 'capabilities': {}, 'clientInfo': {'name': 'pipeline', 'version': '0'}})
        self._post({'jsonrpc': '2.0', 'method': 'notifications/initialized'})

    def tool(self, name: str, arguments: dict):
        '''Call one MCP tool and return its JSON text decoded.'''
        result = self._call('tools/call', {'name': name, 'arguments': arguments})
        texts = [item.get('text', '') for item in result.get('content', []) if item.get('type') == 'text']
        if result.get('isError'):
            raise McpError('tool %s failed: %s' % (name, (texts or [''])[0][:160]))
        try:
            return json.loads(texts[0] if texts else '')
        except ValueError:
            raise McpError('tool %s returned a text that is not JSON: %r' % (name, (texts or [''])[0][:120]))


def _unwrap(reply) -> tuple[bool, object]:
    '''Return (success, data) of a call_server reply {success, result: {success, data}}.'''
    inner = reply.get('result') if isinstance(reply, dict) else None
    ok = isinstance(reply, dict) and reply.get('success') is True and isinstance(inner, dict) and inner.get('success') is True
    return ok, (inner.get('data') if isinstance(inner, dict) else None)


def _registered(session: McpSession, service: str):
    '''Return the list_servers entry of the service, or None; walks the pages.'''
    for page in range(1, 6):
        reply = session.tool('list_servers', {'page': page, 'page_size': 50})
        for entry in reply.get('servers', []) if isinstance(reply, dict) else []:
            if entry.get('server_id') == service:
                return entry
        pages = (reply.get('pagination') or {}).get('total_pages', 1) if isinstance(reply, dict) else 1
        if page >= pages:
            break
    return None


def proxy_peer_auth() -> None:
    '''AU4: through the MCP Proxy, with no token from the pipeline side, the service executes commands, and it is registered with its command list.'''
    report = Report()
    try:
        service = endpoint('ONEDRIVE_BACKUP_ID')
        session = McpSession(endpoint('MCP_PROXY_MCP_ENDPOINT'))
        session.open()
    except (PipelineEnvError, McpError) as exc:
        report.env.append('AU4 the MCP interface of the proxy cannot be used: %s' % exc)
        report.finish('proxy_peer_auth')
        return

    def call(command: str, params: dict):
        try:
            return session.tool('call_server', {'server_id': service, 'copy_number': 1, 'command': command, 'params': params})
        except McpError as exc:
            report.env.append('AU4 call_server(%s, %s): %s' % (service, command, exc))
            return None
    reply = call('help', {})
    if reply is not None:
        ok, data = _unwrap(reply)
        if not ok or not isinstance(data, dict):
            report.product.append('AU4 call_server(%s, help) with no token: %s, expected success (the proxy peer is admitted on mTLS alone, R18)' % (service, str(reply)[:200]))
        else:
            version = (data.get('tool_info') or {}).get('version')
            names = sorted(data.get('commands', {}))
            if version != base.version():
                report.product.append('AU4 help through the proxy: tool_info.version %r, expected VERSION %r' % (version, base.version()))
            if names != sorted(base.COMMANDS):
                report.product.append('AU4 help through the proxy lists %s, expected exactly the 11 commands of rows M1..M11' % names)
    reply = call('info', {'page': 1})
    if reply is not None:
        ok, data = _unwrap(reply)
        if not ok or not isinstance(data, dict) or data.get('page') != 1:
            report.product.append('AU4 call_server(%s, info, page=1) with no token: %s, expected success with page 1' % (service, str(reply)[:200]))
    try:
        entry = _registered(session, service)
    except McpError as exc:
        report.env.append('AU4 list_servers: %s' % exc)
    else:
        if entry is None:
            report.product.append('AU4 the proxy registry does not list %s: its registration read of /commands or its heartbeat of /health was refused' % service)
        else:
            report.info.append('AU4 registered as %s copy %s at %s' % (entry.get('server_id'), entry.get('copy_number'), entry.get('server_url')))
    try:
        status, decoded = base.rpc('help', {}, None)
    except live.LiveUnreachable as exc:
        report.env.append('AU1 control: %s' % exc)
    else:
        if status != 401:
            report.product.append('AU4 control: the same request from a direct peer without token answered %d, expected 401 (otherwise the proxy path proves nothing)' % status)
    report.info.append('AU4 routes /commands, /health, /downloads/* and /api/transfer/downloads for the proxy peer are asserted on disposable instances by proxy_trust_independent')
    report.finish('proxy_peer_auth')


class HarnessError(RuntimeError):
    '''A prerequisite of the disposable instance is missing or broke (ENVIRONMENT).'''


class ServiceDidNotStart(HarnessError):
    '''The deployed image did not come up in a secret state it must handle (PRODUCT).'''


def image() -> str:
    return '%s:%s' % (IMAGE_NAME, base.version())


def _sh(args: list[str], timeout: int = 180, check: bool = True) -> subprocess.CompletedProcess:
    try:
        done = subprocess.run(args, capture_output=True, text=True, timeout=timeout)
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise HarnessError('%s: %s' % (args[0], exc))
    if check and done.returncode != 0:
        raise HarnessError('%s %s failed: %s' % (args[0], args[1] if len(args) > 1 else '', (done.stderr or done.stdout).strip()[:300]))
    return done


def prerequisites() -> list[str]:
    '''Return what is missing for a disposable instance on this machine (empty when it can run).'''
    problems = []
    if os.geteuid() != 0:
        problems.append('not root: run it as root on the host, in the manner of smoke_mtls (bind-mount ownership, docker)')
    for tool in ('docker', 'openssl'):
        if shutil.which(tool) is None:
            problems.append('%s is not installed' % tool)
    if not problems and subprocess.run(['docker', 'image', 'inspect', image()], capture_output=True).returncode != 0:
        problems.append('the deployed image %s is not on this host' % image())
    return problems


class Disposable:
    '''One disposable instance of the deployed image: own network, own CA, one proxy-identity peer and one ordinary peer.'''

    def __init__(self, label: str, secret: str, proxy_listed: bool) -> None:
        self.secret, self.proxy_listed = secret, proxy_listed
        self.name = 'odbpt%d%s' % (os.getpid(), label)
        self.proxy, self.peer, self.net = self.name + '-proxy', self.name + '-peer', self.name + '-net'
        self.work = Path(tempfile.mkdtemp(prefix=self.name + '-'))
        self.token: str | None = None
        self.requests = 0
        self.hash_problem: str | None = None

    def __enter__(self) -> 'Disposable':
        try:
            self._build()
        except BaseException:
            self.cleanup()
            raise
        return self

    def __exit__(self, *args) -> None:
        self.cleanup()

    def cleanup(self) -> None:
        for name in (self.name, self.proxy, self.peer):
            subprocess.run(['docker', 'rm', '-f', name], capture_output=True)
        subprocess.run(['docker', 'network', 'rm', self.net], capture_output=True)
        shutil.rmtree(self.work, ignore_errors=True)

    def _openssl(self, *args: str) -> None:
        _sh(['openssl'] + list(args), timeout=60)

    def _certs(self) -> None:
        w = self.work
        ca_key, ca_crt = w / 'ca' / 'ca.key', w / 'config' / 'certs' / 'ca.crt'
        rsa = 'rsa:' + '2048'
        self._openssl('req', '-x509', '-newkey', rsa, '-sha256', '-days', '2', '-nodes', '-subj', '/CN=odbpt-root', '-keyout', str(ca_key), '-out', str(ca_crt))
        for who, subject, ext, key, crt in (('server', '/CN=' + self.name, 'subjectAltName=DNS:%s,DNS:localhost\nextendedKeyUsage=serverAuth\nkeyUsage=digitalSignature,keyEncipherment\n' % self.name,
                                            w / 'config' / 'certs' / 'server.key', w / 'config' / 'certs' / 'server.crt'),
                                           ('client', '/CN=odbpt-client', 'extendedKeyUsage=clientAuth\nkeyUsage=digitalSignature\n',
                                            w / 'probe' / 'client.key', w / 'probe' / 'client.crt')):
            csr, extfile = w / (who + '.csr'), w / (who + '.ext')
            extfile.write_text(ext)
            self._openssl('req', '-newkey', rsa, '-sha256', '-nodes', '-subj', subject, '-keyout', str(key), '-out', str(csr))
            self._openssl('x509', '-req', '-in', str(csr), '-CA', str(ca_crt), '-CAkey', str(ca_key), '-CAcreateserial', '-days', '2', '-sha256', '-extfile', str(extfile), '-out', str(crt))
        shutil.copy(ca_crt, w / 'config' / 'certs' / 'trust-bundle.pem')
        shutil.copy(ca_crt, w / 'config' / 'certs' / 'proxy-ca.crt')
        shutil.copy(ca_crt, w / 'probe' / 'ca.crt')
        shutil.copy(PROBE_SOURCE, w / 'probe' / 'peer_probe.py')

    def _config(self) -> None:
        w = self.work
        cfg = json.loads((base.ROOT / 'config' / 'server.json').read_text(encoding='utf-8'))
        cfg['registration']['enabled'] = False
        cfg['registration']['auto_on_startup'] = False
        cfg['proxy_trust'] = {'hosts': [self.proxy] if self.proxy_listed else []}
        (w / 'config' / 'server.json').write_text(json.dumps(cfg), encoding='utf-8')
        shutil.copy(base.ROOT / 'config' / 'backup.json', w / 'config' / 'backup.json')
        path = w / 'secrets' / 'api-credentials'
        if self.secret == 'present':
            login, password = 'smoke', secrets.token_hex(12)
            path.write_text('%s:%s\n' % (login, password), encoding='utf-8')
            self.token = credentials.derive(login, password)
        elif self.secret == 'empty':
            path.write_text('', encoding='utf-8')

    def _modes(self) -> None:
        for path in [self.work] + sorted(self.work.rglob('*')):
            path.chmod(0o755 if path.is_dir() else 0o644)
        (self.work / 'data').chmod(0o777)

    def _admin_hash(self) -> None:
        out = self.work / 'config' / 'admin-password.hash'
        code = ('import os, sys; from pathlib import Path; from onedrive_api.admin_password import password_hash; out = Path(sys.argv[1]); '
                'out.write_text(password_hash(sys.argv[2]) + chr(10)); out.chmod(0o600); os.chown(out, 1000, 1000)')
        done = subprocess.run([sys.executable, '-c', code, str(out), 'DisposableTestPasswordOnly2026!'], capture_output=True, text=True,
                              env=dict(os.environ, PYTHONPATH=str(base.ROOT / 'src')))
        self.hash_problem = None if done.returncode == 0 else done.stderr.strip()[-200:]

    def _peer(self, name: str) -> None:
        _sh(['docker', 'run', '-d', '--name', name, '--network', self.net, '--entrypoint', 'sleep',
             '--mount', 'type=bind,source=%s,target=/probe,readonly' % (self.work / 'probe'), image(), '3600'])

    def _build(self) -> None:
        for part in ('config/certs', 'data', 'secrets', 'probe', 'ca'):
            (self.work / part).mkdir(parents=True)
        self._certs()
        self._config()
        self._modes()
        self._admin_hash()
        _sh(['docker', 'network', 'create', self.net])
        self._peer(self.proxy)
        self._peer(self.peer)
        _sh(['docker', 'run', '-d', '--name', self.name, '--network', self.net,
             '--mount', 'type=bind,source=%s,target=/config,readonly' % (self.work / 'config'),
             '--mount', 'type=bind,source=%s,target=/data' % (self.work / 'data'),
             '--mount', 'type=bind,source=%s,target=/secrets,readonly' % (self.work / 'secrets'), image()])
        self._wait_ready()

    def _running(self) -> bool:
        done = _sh(['docker', 'inspect', self.name], check=False)
        try:
            return bool(json.loads(done.stdout)[0]['State']['Running'])
        except (ValueError, KeyError, IndexError):
            return False

    def _wait_ready(self) -> None:
        import time
        deadline = time.monotonic() + START_SECONDS
        while time.monotonic() < deadline:
            if not self._running():
                logs = _sh(['docker', 'logs', '--tail', '12', self.name], check=False)
                raise ServiceDidNotStart('the service container exited in secret state %r: %s' % (self.secret, (logs.stdout + logs.stderr).strip()[-300:]))
            try:
                if self.probe(self.peer, [{'id': 'health', 'method': 'GET', 'path': '/health', 'headers': {}}])['health']['status'] == 200:
                    return
            except HarnessError:
                pass
            time.sleep(2)
        raise ServiceDidNotStart('the service did not answer /health within %d s in secret state %r' % (START_SECONDS, self.secret))

    def address(self, container: str) -> str:
        done = _sh(['docker', 'inspect', container])
        return json.loads(done.stdout)[0]['NetworkSettings']['Networks'][self.net]['IPAddress']

    def spoof(self) -> dict:
        '''Headers of an ordinary peer that name the proxy identity (they must grant nothing).'''
        address = self.address(self.proxy)
        return {'X-Forwarded-For': address, 'Forwarded': 'for=%s;host=%s' % (address, self.proxy), 'X-Real-IP': address, 'Host': self.proxy}

    def probe(self, source: str, requests: list[dict]) -> dict:
        '''Run the requests from the named peer container; return {id: {status, body}}.'''
        self.requests += 1
        name = 'req-%d.json' % self.requests
        (self.work / 'probe' / name).write_text(json.dumps(requests), encoding='utf-8')
        (self.work / 'probe' / name).chmod(0o644)
        done = _sh(['docker', 'exec', source, 'python3', '/probe/peer_probe.py', self.name, '/probe/' + name], timeout=180)
        try:
            return {item['id']: item for item in json.loads(done.stdout)}
        except (ValueError, KeyError, TypeError):
            raise HarnessError('the peer probe printed no JSON list: %r' % done.stdout[:120])


def _requests(token: str | None = None, extra: dict | None = None) -> list[dict]:
    '''The route set one peer presents: command execution, batch, transfer, download link, health and the command list.'''
    one = json.dumps({'jsonrpc': '2.0', 'method': 'help', 'params': {}, 'id': 1})
    post, plain = {'Content-Type': 'application/json'}, {}
    for headers in (post, plain):
        if token is not None:
            headers[base.TOKEN_HEADER] = token
        headers.update(extra or {})
    transfer = json.dumps({'source_path': '/x', 'filename': 'x.bin', 'compression': 'identity'})
    link = '/downloads/%s/x.bin' % base.ZERO_ID
    return [{'id': 'jsonrpc', 'method': 'POST', 'path': '/api/jsonrpc', 'headers': post, 'body': one},
            {'id': 'batch', 'method': 'POST', 'path': '/api/jsonrpc/batch', 'headers': post, 'body': '[' + one + ']'},
            {'id': 'transfer', 'method': 'POST', 'path': '/api/transfer/downloads', 'headers': post, 'body': transfer},
            {'id': 'dl_get', 'method': 'GET', 'path': link, 'headers': plain},
            {'id': 'dl_head', 'method': 'HEAD', 'path': link, 'headers': plain},
            {'id': 'health', 'method': 'GET', 'path': '/health', 'headers': plain},
            {'id': 'commands', 'method': 'GET', 'path': '/commands', 'headers': plain}]


def _success(item: dict) -> bool:
    return item['status'] == 200 and 'success":true' in item['body'].replace(' ', '')


def _admitted(report: Report, tag: str, got: dict) -> None:
    '''The peer is admitted WITHOUT a token on every route: no answer of the token gate (401), commands run.'''
    if not _success(got['jsonrpc']):
        report.product.append('%s POST /api/jsonrpc help without token: answered %d %s, expected 200 and success' % (tag, got['jsonrpc']['status'], got['jsonrpc']['body'][:90]))
    for rid, label in (('batch', 'POST /api/jsonrpc/batch'), ('transfer', 'POST /api/transfer/downloads'), ('dl_get', 'GET /downloads/<id>/<name>'), ('dl_head', 'HEAD /downloads/<id>/<name>')):
        if got[rid]['status'] in (0, 401):
            report.product.append('%s %s without token: answered %d %s, expected a request that passed the token gate' % (tag, label, got[rid]['status'], got[rid]['body'][:90]))
    for rid, label in (('health', 'GET /health'), ('commands', 'GET /commands')):
        if got[rid]['status'] != 200:
            report.product.append('%s %s: answered %d, expected 200' % (tag, label, got[rid]['status']))


def _denied(report: Report, tag: str, got: dict) -> None:
    '''The peer is refused by the token gate (401, authentication_error) on every protected route; /health and /commands stay public.'''
    item = got['jsonrpc']
    if item['status'] != 401 or 'authentication_error' not in item['body']:
        report.product.append('%s POST /api/jsonrpc help: answered %d %s, expected 401 authentication_error' % (tag, item['status'], item['body'][:90]))
    for rid, label in (('batch', 'POST /api/jsonrpc/batch'), ('transfer', 'POST /api/transfer/downloads'), ('dl_get', 'GET /downloads/<id>/<name>'), ('dl_head', 'HEAD /downloads/<id>/<name>')):
        if got[rid]['status'] != 401:
            report.product.append('%s %s: answered %d %s, expected 401' % (tag, label, got[rid]['status'], got[rid]['body'][:90]))
    for rid, label in (('health', 'GET /health'), ('commands', 'GET /commands')):
        if got[rid]['status'] != 200:
            report.product.append('%s %s: answered %d, expected 200 (public path)' % (tag, label, got[rid]['status']))


def _plan_present(report: Report, box: Disposable) -> None:
    state = '[secret present]'
    _admitted(report, 'AU4 %s proxy-identity peer' % state, box.probe(box.proxy, _requests()))
    _denied(report, 'AU1 %s direct peer without token' % state, box.probe(box.peer, _requests()))
    _denied(report, 'AU1 %s direct peer without token, spoofed proxy headers' % state, box.probe(box.peer, _requests(None, box.spoof())))
    _denied(report, 'AU2 %s direct peer with a wrong token' % state, box.probe(box.peer, _requests('not-the-token')))
    if not _success(box.probe(box.peer, _requests(box.token))['jsonrpc']):
        report.product.append('AU3 %s direct peer with the correct token T: POST /api/jsonrpc help did not succeed' % state)


def _plan_unprovisioned(state: str):
    '''Secret absent or malformed: the proxy peer is still admitted, every direct peer gets 401 (no valid T exists).'''
    def plan(report: Report, box: Disposable) -> None:
        _admitted(report, 'AU5 %s proxy-identity peer' % state, box.probe(box.proxy, _requests()))
        _denied(report, 'AU5 %s direct peer without token' % state, box.probe(box.peer, _requests()))
        _denied(report, 'AU5 %s direct peer without token, spoofed proxy headers' % state, box.probe(box.peer, _requests(None, box.spoof())))
        _denied(report, 'AU5 %s direct peer with the formerly valid token T' % state, box.probe(box.peer, _requests(credentials.derive('smoke', 'formerly-valid'))))
    return plan


def _plan_fail_closed(report: Report, box: Disposable) -> None:
    state = '[secret absent, no proxy identity configured]'
    _denied(report, 'AU5 %s peer carrying the former proxy name' % state, box.probe(box.proxy, _requests()))
    _denied(report, 'AU5 %s ordinary peer' % state, box.probe(box.peer, _requests()))


INSTANCES = (('a', 'present', True, _plan_present), ('b', 'absent', True, _plan_unprovisioned('[secret absent]')),
             ('c', 'absent', False, _plan_fail_closed), ('d', 'empty', True, _plan_unprovisioned('[secret empty]')))


def proxy_trust_independent() -> None:
    '''AU5, R18: the proxy peer is admitted on mTLS alone whether or not the api-credentials secret exists; direct peers get 401; with no configured proxy identity nobody is admitted without a token.'''
    report = Report()
    problems = prerequisites()
    for item in problems:
        report.env.append('AU5 a disposable instance cannot be started here: ' + item)
    if not problems:
        for label, secret, listed, plan in INSTANCES:
            try:
                with Disposable(label, secret, listed) as box:
                    plan(report, box)
                    if box.hash_problem:
                        report.info.append('instance %s: the disposable admin hash could not be written (%s); the service started without it' % (label, box.hash_problem))
            except ServiceDidNotStart as exc:
                report.product.append('AU5 instance %s (secret %s, proxy identity %s): %s' % (label, secret, 'configured' if listed else 'not configured', exc))
            except HarnessError as exc:
                report.env.append('AU5 instance %s: %s' % (label, exc))
    report.finish('proxy_trust_independent')
