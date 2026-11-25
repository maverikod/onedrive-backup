'''B4 named check of the MCP Proxy path: proxy_peer_auth (AU4, revision 8) and the disposable-instance harness helpers.

Revision 8 (10.15.9): there is no mTLS, no token and no peer admission; the MCP Proxy is an ordinary caller of an open service.
proxy_peer_auth runs the real path of every MCP client: the MCP interface of the shared production proxy, no credential from the
pipeline side; call_server(onedrive-backup, help) and (info, page=1) succeed. The harness helpers (image, _sh, prerequisites)
serve auth_key_optional (pipeline.b4key), which starts a DISPOSABLE instance of the deployed image on the host as root, in the
manner of smoke_https. Findings are kept apart as PRODUCT, STATE and ENVIRONMENT.
'''

from __future__ import annotations

import json
import os
import shutil
import subprocess
import urllib.error
import urllib.parse
import urllib.request

from pipeline import b4base as base
from pipeline.environment import PipelineEnvError, endpoint
from pipeline.report import Report

IMAGE_NAME = 'vasilyvz/onedrive-backup'
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
    '''AU4: through the MCP Proxy, with no credential from the pipeline side, the service executes commands, and it is registered with its command list.'''
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
            report.product.append('AU4 call_server(%s, help) with no credential: %s, expected success (the service is open, the proxy is an ordinary caller, AU4)' % (service, str(reply)[:200]))
        else:
            version = (data.get('tool_info') or {}).get('version')
            names = sorted(data.get('commands', {}))
            if version != base.version():
                report.product.append('AU4 help through the proxy: tool_info.version %r, expected VERSION %r' % (version, base.version()))
            if names != sorted(base.COMMANDS):
                report.product.append('AU4 help through the proxy lists %s, expected exactly the %d commands of the inventory' % (names, len(base.COMMANDS)))
    reply = call('info', {'page': 1})
    if reply is not None:
        ok, data = _unwrap(reply)
        if not ok or not isinstance(data, dict) or data.get('page') != 1:
            report.product.append('AU4 call_server(%s, info, page=1) with no credential: %s, expected success with page 1' % (service, str(reply)[:200]))
    try:
        entry = _registered(session, service)
    except McpError as exc:
        report.env.append('AU4 list_servers: %s' % exc)
    else:
        if entry is None:
            report.product.append('AU4 the proxy registry does not list %s: its registration read of /commands or its heartbeat of /health was refused' % service)
        else:
            report.info.append('AU4 registered as %s copy %s at %s' % (entry.get('server_id'), entry.get('copy_number'), entry.get('server_url')))
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
        problems.append('not root: run it as root on the host, in the manner of smoke_https (bind-mount ownership, docker)')
    for tool in ('docker', 'openssl'):
        if shutil.which(tool) is None:
            problems.append('%s is not installed' % tool)
    if not problems and subprocess.run(['docker', 'image', 'inspect', image()], capture_output=True).returncode != 0:
        problems.append('the deployed image %s is not on this host' % image())
    return problems
