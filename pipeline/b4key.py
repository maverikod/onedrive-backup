'''B4 named checks on a DISPOSABLE instance of the deployed image: smoke_https (PX6) and auth_key_optional (AU6), revision 8.

Revision 8 (10.15): the listener is server-auth HTTPS from the adapter configuration alone (server.protocol https, no client
certificate), the service is open (auth.use_token false) and the later password mode is the adapter static key switched on by
CONFIGURATION ONLY. Both checks start `docker run --rm`-style instances of the deployed image on the host as root (own name, own
CA, own temporary directory, a port published on 127.0.0.1 only, no production volume, never the production service), in the
manner of the former smoke_mtls. A missing prerequisite (root, docker, openssl, the image) is RED [ENVIRONMENT], never skipped.
The disposable instance proves that the switch is config-only: no code differs between the open instance and the keyed one.
'''

from __future__ import annotations

import http.client
import json
import os
import secrets
import shutil
import socket
import ssl
import subprocess
import tempfile
import time
from pathlib import Path

from pipeline import b4base as base, b4client, b4cli, b4proxy, live
from pipeline.b4proxy import HarnessError, ServiceDidNotStart, _sh, image, prerequisites
from pipeline.report import Report

READY_SECONDS = b4proxy.START_SECONDS
KEY_ENV = 'ONEDRIVE_BACKUP_API_KEY'


def _free_port() -> int:
    with socket.socket() as sock:
        sock.bind(('localhost', 0))
        return sock.getsockname()[1]


class Instance:
    '''One disposable HTTPS instance of the deployed image; key=None is the open service, a string is the static key mode.'''

    def __init__(self, label: str, key: str | None) -> None:
        self.key = key
        self.name = 'odbsh%d%s' % (os.getpid(), label)
        self.port = _free_port()
        self.work = Path(tempfile.mkdtemp(prefix=self.name + '-'))
        self.url = ''.join(('https', '://', 'localhost', ':', str(self.port)))
        self.ca = self.work / 'config' / 'certs' / 'ca.crt'

    def __enter__(self) -> 'Instance':
        try:
            self._build()
        except BaseException:
            self.cleanup()
            raise
        return self

    def __exit__(self, *args) -> None:
        self.cleanup()

    def cleanup(self) -> None:
        subprocess.run(['docker', 'rm', '-f', self.name], capture_output=True)
        shutil.rmtree(self.work, ignore_errors=True)

    def _openssl(self, *args: str) -> None:
        _sh(['openssl'] + list(args), timeout=60)

    def _certs(self) -> None:
        w = self.work
        ca_key = w / 'ca' / 'ca.key'
        rsa = 'rsa:' + '2048'
        self._openssl('req', '-x509', '-newkey', rsa, '-sha256', '-days', '2', '-nodes', '-subj', '/CN=odbsh-root', '-keyout', str(ca_key), '-out', str(self.ca))
        key, crt, csr, ext = w / 'config' / 'certs' / 'server.key', w / 'config' / 'certs' / 'server.crt', w / 'server.csr', w / 'server.ext'
        ext.write_text('subjectAltName=DNS:localhost,DNS:onedrive-backup\nextendedKeyUsage=serverAuth\nkeyUsage=digitalSignature,keyEncipherment\n')
        self._openssl('req', '-newkey', rsa, '-sha256', '-nodes', '-subj', '/CN=localhost', '-keyout', str(key), '-out', str(csr))
        self._openssl('x509', '-req', '-in', str(csr), '-CA', str(self.ca), '-CAkey', str(ca_key), '-CAcreateserial', '-days', '2', '-sha256', '-extfile', str(ext), '-out', str(crt))
        shutil.copy(self.ca, w / 'config' / 'certs' / 'trust-bundle.pem')
        shutil.copy(self.ca, w / 'config' / 'certs' / 'proxy-ca.crt')

    def _config(self) -> None:
        '''The ONLY difference to the deployed configuration is configuration: protocol https, no proxy_trust, the auth block.'''
        cfg = json.loads((base.ROOT / 'config' / 'server.json').read_text(encoding='utf-8'))
        cfg['server']['protocol'] = 'https'
        cfg.pop('proxy_trust', None)
        cfg['registration']['enabled'] = False
        cfg['registration']['auto_on_startup'] = False
        if self.key is None:
            cfg['auth'] = {'use_token': False, 'use_roles': False, 'tokens': {}, 'roles': {}}
        else:
            cfg['auth'] = {'use_token': True, 'use_roles': False, 'tokens': {self.key: ['admin']}, 'roles': {}}
            cfg['security'] = {'enabled': False, 'public_paths': ['/commands'], 'tokens': {'api': '${%s}' % KEY_ENV}}
        (self.work / 'config' / 'server.json').write_text(json.dumps(cfg), encoding='utf-8')
        shutil.copy(base.ROOT / 'config' / 'backup.json', self.work / 'config' / 'backup.json')

    def _build(self) -> None:
        for part in ('config/certs', 'data', 'secrets', 'ca'):
            (self.work / part).mkdir(parents=True)
        self._certs()
        self._config()
        for path in [self.work] + sorted(self.work.rglob('*')):
            path.chmod(0o755 if path.is_dir() else 0o644)
        (self.work / 'data').chmod(0o777)
        command = ['docker', 'run', '-d', '--name', self.name, '-p', ':'.join((socket.gethostbyname('localhost'), str(self.port), '8050'))]
        if self.key is not None:
            command += ['-e', KEY_ENV + '=' + self.key]
        command += ['--mount', 'type=bind,source=%s,target=/config,readonly' % (self.work / 'config'),
                    '--mount', 'type=bind,source=%s,target=/data' % (self.work / 'data'),
                    '--mount', 'type=bind,source=%s,target=/secrets,readonly' % (self.work / 'secrets'), image()]
        _sh(command)
        self._wait_ready()

    def _running(self) -> bool:
        done = _sh(['docker', 'inspect', self.name], check=False)
        try:
            return bool(json.loads(done.stdout)[0]['State']['Running'])
        except (ValueError, KeyError, IndexError):
            return False

    def _wait_ready(self) -> None:
        deadline = time.monotonic() + READY_SECONDS
        while time.monotonic() < deadline:
            if not self._running():
                logs = _sh(['docker', 'logs', '--tail', '12', self.name], check=False)
                raise ServiceDidNotStart('the container exited with server.protocol https and %s: %s'
                                         % ('the static key' if self.key else 'auth off', (logs.stdout + logs.stderr).strip()[-300:]))
            try:
                if self.request('GET', '/health')[0] == 200:
                    return
            except (OSError, ssl.SSLError, http.client.HTTPException):
                pass
            time.sleep(2)
        raise ServiceDidNotStart('the service did not answer /health over server-auth HTTPS within %d s' % READY_SECONDS)

    def context(self) -> ssl.SSLContext:
        return ssl.create_default_context(cafile=str(self.ca))

    def request(self, method: str, path: str, body: bytes | None = None, headers: dict | None = None) -> tuple[int, bytes]:
        '''One request WITHOUT a client certificate; return (status, body).'''
        conn = http.client.HTTPSConnection('localhost', self.port, context=self.context(), timeout=20)
        try:
            conn.request(method, path, body=body, headers=headers or {})
            reply = conn.getresponse()
            return reply.status, reply.read()
        finally:
            conn.close()

    def rpc(self, command: str, params: dict | None = None, key: str | None = None) -> tuple[int, object]:
        headers = dict(base.JSON_HEADERS)
        if key is not None:
            headers[base.TOKEN_HEADER] = key
        status, raw = self.request('POST', '/api/jsonrpc', json.dumps({'jsonrpc': '2.0', 'method': command, 'params': params or {}, 'id': 1}).encode('utf-8'), headers)
        try:
            return status, json.loads(raw)
        except ValueError:
            return status, None


def _success(decoded) -> bool:
    return isinstance(decoded, dict) and isinstance(decoded.get('result'), dict) and decoded['result'].get('success') is True


def _start(report: Report, case: str, label: str, key: str | None):
    '''Return a started Instance context manager entered, or None after a finding.'''
    box = Instance(label, key)
    try:
        return box.__enter__(), box
    except ServiceDidNotStart as exc:
        report.product.append('%s: %s' % (case, exc))
    except (HarnessError, OSError, ssl.SSLError) as exc:
        report.env.append('%s: %s' % (case, exc))
    return None, box


def smoke_https_instance(report: Report) -> None:
    '''PX6 cases on an open disposable instance: health over TLS without a client certificate, plain HTTP refused, an untrusting client fails, snapshots 503 (scaffold).'''
    entered, box = _start(report, 'smoke_https instance', 'o', None)
    if entered is None:
        return
    try:
        status, raw = box.request('GET', '/health')
        if status != 200:
            report.product.append('PX6 health over TLS without a client certificate: answered %d, expected 200' % status)
        try:
            plain = http.client.HTTPConnection('localhost', box.port, timeout=10)
            plain.request('GET', '/health')
            content = plain.getresponse().read()
            if content:
                report.product.append('PX6 a plain HTTP request to the TLS port got content %r, expected a refusal or a closed connection' % content[:60])
        except (OSError, http.client.HTTPException):
            pass
        try:
            ssl.create_default_context().wrap_socket(socket.create_connection(('localhost', box.port), timeout=10), server_hostname='localhost')
            report.product.append('PX6 a client that does not trust the project CA completed the TLS handshake, expected a verification failure')
        except ssl.SSLError:
            pass
        except OSError as exc:
            report.env.append('PX6 untrusting client: %s' % exc)
        status, decoded = box.rpc('backup_snapshots', {})
        error = (decoded or {}).get('result', {}).get('error', {}) if isinstance(decoded, dict) else {}
        if not (status == 200 and isinstance(decoded, dict) and decoded.get('result', {}).get('success') is False and error.get('code') == 503):
            report.product.append('PX6 backup_snapshots without a credential on the empty scaffold instance: answered %d %s, expected the command error 503 (scaffold, no 401 exists)' % (status, str(decoded)[:100]))
    finally:
        box.cleanup()


def smoke_https() -> None:
    '''PX6: scripts/smoke-https.sh exists, parses and exits 0 as root on the host; the pipeline repeats its contract on an open disposable instance.'''
    report = Report()
    script = base.ROOT / 'scripts' / 'smoke-https.sh'
    if not script.is_file():
        report.product.append('PX6 scripts/smoke-https.sh does not exist (smoke-mtls.sh is renamed and rewritten for server-auth HTTPS, PP6)')
    else:
        syntax = subprocess.run(['bash', '-n', str(script)], capture_output=True, text=True)
        if syntax.returncode != 0:
            report.product.append('PX6 bash -n scripts/smoke-https.sh: %s' % syntax.stderr.strip()[:200])
    problems = prerequisites()
    for item in problems:
        report.env.append('PX6 a disposable instance cannot be started here: ' + item)
    if not problems:
        if script.is_file():
            done = subprocess.run(['bash', str(script)], cwd=base.ROOT, capture_output=True, text=True, timeout=900)
            if done.returncode != 0:
                report.product.append('PX6 bash scripts/smoke-https.sh exited %d: %s' % (done.returncode, (done.stderr or done.stdout).strip()[-200:]))
        smoke_https_instance(report)
    report.finish('smoke_https')


def _key_cases(report: Report, box: Instance, key: str) -> None:
    status, decoded = box.rpc('help', {})
    if status != 401:
        report.product.append('AU6 no key on the keyed instance: answered %d, expected 401' % status)
    status, decoded = box.rpc('help', {}, 'not-the-key')
    if status != 401:
        report.product.append('AU6 a wrong key: answered %d, expected 401' % status)
    status, decoded = box.rpc('help', {}, key)
    if status != 200 or not _success(decoded):
        report.product.append('AU6 the correct X-API-Key: answered %d %s, expected 200 and help success' % (status, str(decoded)[:100]))
    seen: list[str] = []
    module = b4client.load_client(report)
    if module is not None:
        try:
            client = module.BackupClient(url=box.url, ca=str(box.ca), password=key, timeout=30)
        except Exception as exc:
            report.product.append('AU6 BackupClient(url, ca, password) without cert and key: %s: %s' % (type(exc).__name__, exc))
        else:
            value, exc = b4client.drive(client.help)
            if exc is not None or not value:
                report.product.append('AU6 the Python client configured with the key: help %s' % (exc or 'returned nothing'))
    main = b4cli.entry(report)
    if main is not None:
        code, out, err = b4cli.run_cli(main, ['--url', box.url, '--ca', str(box.ca), '--password', key, 'help'])
        seen += [out, err]
        if code != 0:
            report.product.append('AU6 odbcli --password <key> help: exit %r, expected 0' % (code,))
        os.environ['ONEDRIVE_BACKUP_PASSWORD'] = key
        try:
            code, out, err = b4cli.run_cli(main, ['--url', box.url, '--ca', str(box.ca), 'help'])
        finally:
            os.environ.pop('ONEDRIVE_BACKUP_PASSWORD', None)
        seen += [out, err]
        if code != 0:
            report.product.append('AU6 odbcli with the key from ONEDRIVE_BACKUP_PASSWORD: exit %r, expected 0' % (code,))
    if any(key in text for text in seen):
        report.product.append('AU6 the key appears in the stdout or stderr of odbcli (never printed)')


def _open_service_without_key(report: Report) -> None:
    '''The same client WITHOUT a configured key against the open production service sends no auth header and succeeds.'''
    module = b4client.load_client(report)
    if module is None:
        return
    ca, cert, key = live._tls_files()
    kwargs = {'url': live.base_url(), 'ca': ca, 'timeout': 30}
    if cert and key:
        kwargs.update(cert=cert, key=key)
    try:
        client = module.BackupClient(**kwargs)
    except Exception as exc:
        report.product.append('AU6 BackupClient without a password: %s: %s' % (type(exc).__name__, exc))
        return
    value, exc = b4client.drive(client.help)
    if exc is not None or not value:
        report.product.append('AU6 the client without a configured key against the open service: help %s, expected success with no auth header (auth is off)' % (exc or 'returned nothing'))


def auth_key_optional() -> None:
    '''AU6 (PP-D1b): the optional key path is config-only; a keyed disposable instance answers 401 without a key and runs with it; the clients carry the key and never print it.'''
    report = Report()
    problems = prerequisites()
    for item in problems:
        report.env.append('AU6 a disposable instance cannot be started here: ' + item)
    if not problems:
        key = secrets.token_hex(16)
        entered, box = _start(report, 'AU6 keyed instance', 'k', key)
        if entered is not None:
            try:
                _key_cases(report, box, key)
            finally:
                box.cleanup()
    _open_service_without_key(report)
    report.finish('auth_key_optional')
