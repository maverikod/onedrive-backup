'''Headless browser driver of the UI-VUE checks (decision G7, revision 8 10.15.6): Playwright for Python and its Chromium.

Chromium runs headless with HTTPS errors NOT ignored: the certificate of the LAN URL is first verified in Python against the project
CA (pipeline.live) and its public key is the only one the browser is told to accept (--ignore-certificate-errors-spki-list), so the
page is loaded over a verified server-auth TLS connection. Tracing, video and screenshots are off and nothing is written to disk.
Every scenario here follows the hash links the SPA itself shows, records the JSON-RPC calls the page sends and asserts them against the action
table of section 10.11.10 (G9). The routes, nav ids, test ids and the export, logout and card-poll controls of section 10.18 are driven by pipeline.vueroutes.
'''

from __future__ import annotations

import base64
import hashlib
import json
import secrets
import socket
import ssl
import subprocess
import urllib.parse
from pathlib import Path

from typing import Any
from pipeline import live
from pipeline.report import Report

# Section 10.11.10 action table: command -> (keys always sent, keys sent only when set, fixed values).
ACTIONS = {
    'backup_snapshots': (('limit',), (), {'limit': 100}),
    'backup_list_files': (('snapshot_id', 'prefix', 'offset', 'limit'), (), {'limit': 100}),
    'backup_prepare_download': (('snapshot_id',), ('file_path',), {}),
    'backup_download_status': (('export_id',), (), {}),
    'backup_delete_export': (('export_id',), (), {}),
    'backup_sites_list': (('limit', 'offset'), ('query',), {'limit': 100}),
    'backup_libraries_list': (('site_id', 'limit', 'offset'), (), {'limit': 100}),
    'backup_discovery_status': ((), (), {}),
    'help': ((), ('cmdname',), {}),
    'info': ((), ('page',), {}),
}
POLL_COMMANDS = ('backup_discovery_status', 'backup_download_status')
# 10.18.7 (4), probe of 2026-11-20 on the deployed 0.3.20: help, help cmdname, info, backup_snapshots, backup_list_files, backup_sites_list,
# backup_libraries_list and backup_discovery_status, called twice 2 s apart on the quiescent service, differ in NO field, so no field is volatile.
VOLATILE: tuple[str, ...] = ()
PAGE_LIMIT = 12
SETTLE_MS = 600


def problem() -> str | None:
    '''Return why the driver cannot run (package or Chromium missing), or None when it can.'''
    try:
        from playwright.sync_api import sync_playwright  # type: ignore[import-not-found]  # the gate mypy environment lacks the pinned playwright package
    except ImportError as exc:
        return 'the playwright package is not importable in the pipeline environment (%s); install pipeline/requirements.txt' % exc
    try:
        with sync_playwright() as driver:
            if not Path(driver.chromium.executable_path).exists():
                return 'Chromium is not installed for Playwright: run python -m playwright install --with-deps chromium'
    except Exception as exc:
        return 'Playwright cannot start: %s: %s' % (type(exc).__name__, str(exc)[:200])
    return None


def _spki(root: str) -> str:
    '''SPKI sha256 (base64) of the server certificate of root, taken from a connection verified against the project CA.'''
    parts = urllib.parse.urlsplit(root)
    context = live._context(client_cert=False)
    try:
        with socket.create_connection((parts.hostname, parts.port or 443), timeout=15) as raw:
            with context.wrap_socket(raw, server_hostname=parts.hostname) as tls:
                der = tls.getpeercert(binary_form=True)
    except (OSError, ssl.SSLError) as exc:
        raise live.LiveUnreachable('the certificate of %s is not verified by the project CA: %s: %s' % (root, type(exc).__name__, exc))
    pub = subprocess.run(['openssl', 'x509', '-pubkey', '-noout'], input=ssl.DER_cert_to_PEM_cert(der or b''), capture_output=True, text=True, check=True).stdout
    key = subprocess.run(['openssl', 'pkey', '-pubin', '-outform', 'DER'], input=pub.encode(), capture_output=True, check=True).stdout
    return base64.b64encode(hashlib.sha256(key).digest()).decode()


class Driver:
    '''One headless Chromium for a check run.'''

    def __init__(self, root: str) -> None:
        self.root = root.rstrip('/')
        self.play: Any = None
        self.browser: Any = None

    def __enter__(self) -> 'Driver':
        from playwright.sync_api import sync_playwright  # type: ignore[import-not-found]  # the gate mypy environment lacks the pinned playwright package
        self.play = sync_playwright().start()
        self.browser = self.play.chromium.launch(headless=True, args=['--ignore-certificate-errors-spki-list=' + _spki(self.root)])
        return self

    def __exit__(self, *_exc: object) -> None:
        if self.browser:
            self.browser.close()
        if self.play:
            self.play.stop()


class Session:
    '''A fresh browser context and page that records the JSON-RPC calls, other origins, errors and credential-bearing requests.'''

    def __init__(self, drv: Driver, clock: bool = False) -> None:
        self.drv = drv
        self.context = drv.browser.new_context(ignore_https_errors=False, service_workers='block')
        self.page = self.context.new_page()
        self.calls: list[dict] = []
        self.external: list[str] = []
        self.errors: list[str] = []
        self.keyed: list[str] = []
        self.override: int | None = None
        self.hold = False
        self.held: list = []
        self._by_request: dict = {}
        self.origin = urllib.parse.urlsplit(drv.root).netloc
        if clock:
            self.page.clock.install()
        self.page.on('request', self._request)
        self.page.on('response', self._response)
        self.page.on('pageerror', lambda exc: self.errors.append(str(exc)[:200]))
        self.page.on('console', lambda msg: self.errors.append(msg.text[:200]) if msg.type == 'error' else None)
        self.page.route('**/api/jsonrpc', self._route)

    def _request(self, request) -> None:
        parts = urllib.parse.urlsplit(request.url)
        if parts.scheme in ('http', 'https') and parts.netloc != self.origin:
            self.external.append(parts.netloc)
        if request.headers.get('x-api-key') and parts.path not in ('/api/jsonrpc',) and not parts.path.startswith('/downloads/'):
            self.keyed.append(parts.path)
        if parts.path == '/api/jsonrpc' and request.method == 'POST':
            try:
                body = json.loads(request.post_data or 'null')
            except ValueError:
                body = None
            body = body if isinstance(body, dict) else {}
            entry = {'method': body.get('method'), 'params': body.get('params'), 'key': request.headers.get('x-api-key'), 'status': None, 'reply': None}
            self.calls.append(entry)
            self._by_request[request] = entry

    def _response(self, response) -> None:
        entry = self._by_request.get(response.request)
        if entry is None:
            return
        entry['status'] = response.status
        try:
            entry['reply'] = json.loads(response.text())
        except Exception:
            entry['reply'] = None

    def _route(self, route) -> None:
        entry = self._by_request.get(route.request)
        if self.override is not None:
            if entry is not None:
                entry['status'] = self.override
            route.fulfill(status=self.override, content_type='application/json', body='{"detail": "Unauthorized"}')
        elif self.hold and entry is not None and entry['method'] in POLL_COMMANDS:
            self.held.append(route)
        else:
            route.continue_()

    def release(self) -> None:
        '''Let every held request go on to the service.'''
        held, self.held = self.held, []
        for route in held:
            route.continue_()

    def go(self, route: str = '') -> None:
        '''Open the index page (route empty) or one hash route and wait for the page to settle.'''
        self.page.goto(self.drv.root + '/' + route, wait_until='networkidle', timeout=30000)
        self.page.wait_for_timeout(SETTLE_MS)

    def links(self) -> list[str]:
        '''Hash links (a[href^="#"]) of the current page, without the bare anchor.'''
        found = self.page.eval_on_selector_all('a[href^="#"]', 'els => els.map(e => e.getAttribute("href"))')
        return sorted({item for item in found if item and item not in ('#', '#/')})

    def password_fields(self) -> int:
        return self.page.locator('input[type=password]:visible').count()

    def storage(self) -> tuple[int, int]:
        '''(localStorage entries, sessionStorage entries) of the page.'''
        return tuple(self.page.evaluate('[window.localStorage.length, window.sessionStorage.length]'))

    def close(self) -> None:
        self.context.close()


def routes(drv: Driver) -> list[str]:
    '''The index route and the hash links reachable from the index page (at most PAGE_LIMIT pages).'''
    with_index = Session(drv)
    try:
        with_index.go()
        found = with_index.links()
    finally:
        with_index.close()
    return [''] + found[:PAGE_LIMIT - 1]


def call_problems(label: str, calls: list[dict]) -> list[str]:
    '''Findings for the JSON-RPC calls of one page: a command outside the action table, a key outside the table, a missing key, a null value, a wrong fixed value.'''
    found = []
    for call in calls:
        method, params = call['method'], call['params']
        if method not in ACTIONS:
            found.append('%s: the page sends %r, outside the 10 commands of the action table (backup_download_begin is not used by the SPA)' % (label, method))
            continue
        always, optional, fixed = ACTIONS[method]
        params = params if isinstance(params, dict) else {}
        missing, extra = sorted(set(always) - set(params)), sorted(set(params) - set(always) - set(optional))
        nulls = sorted(key for key, value in params.items() if value is None)
        wrong = {key: params.get(key) for key, value in fixed.items() if key in params and params[key] != value}
        if missing or extra or nulls or wrong:
            found.append('%s: %s sends %s, expected exactly the keys %s plus optionally %s, no null, fixed %s (missing %s, extra %s, null %s, wrong %s)'
                         % (label, method, sorted(params), list(always), list(optional), fixed, missing, extra, nulls, wrong))
    return found


def open_cases(report: Report, drv: Driver) -> list[tuple[str, Session]]:
    '''V2 and G7 on the open service: every linked page renders, sends no key, shows no login form, keeps no cookie or web storage and only defined calls.

    Returns the (label, closed session) pairs so the other cases can reuse the calls; each session is closed.'''
    done = []
    for route in routes(drv):
        label = 'G7 page /#%s' % route.lstrip('#') if route else 'G7 index page'
        sess = Session(drv)
        try:
            sess.go(route)
            if not sess.page.locator('body').inner_text().strip():
                report.product.append('%s: the page renders no text, the SPA did not mount' % label)
            if sess.password_fields():
                report.product.append('%s: a password field is visible while the service is open (no login form exists while it is open)' % label)
            if any(call['status'] in (401, 403) for call in sess.calls):
                report.product.append('%s: a command answered 401 or 403 from the open service: %s' % (label, [call['method'] for call in sess.calls if call['status'] in (401, 403)]))
            if any(call['key'] for call in sess.calls) or sess.keyed:
                report.product.append('%s: the page sends X-API-Key while the service is open (a key is sent only after a 401)' % label)
            if sess.external:
                report.product.append('%s: the page loads %s from another origin, the runtime has no external dependency' % (label, sorted(set(sess.external))))
            if sess.errors:
                report.product.append('%s: the page logged errors: %s' % (label, sess.errors[:3]))
            if sess.context.cookies():
                report.product.append('%s: the page set a cookie, expected none' % label)
            if sess.storage() != (0, 0):
                report.product.append('%s: the page wrote web storage (localStorage, sessionStorage) %s, expected none' % (label, sess.storage()))
            report.product.extend(call_problems(label, sess.calls))
            done.append((label, sess))
        finally:
            sess.close()
    return done


def table_cases(report: Report, drv: Driver) -> None:
    '''V4: every linked page sends only commands of the action table, with exactly the table's keys.'''
    for route in routes(drv):
        label = 'V4 page /#%s' % route.lstrip('#') if route else 'V4 index page'
        sess = Session(drv)
        try:
            sess.go(route)
            report.product.extend(call_problems(label, sess.calls))
        finally:
            sess.close()


def key_after_401(report: Report, drv: Driver) -> None:
    '''V2: with a mocked 401 the page shows ONE password field and no login name field; the typed key goes in X-API-Key on /api/jsonrpc and nowhere else, and stays out of cookies, web storage and the URL.'''
    key = 'k' + secrets.token_hex(12)
    sess = Session(drv)
    try:
        sess.override = 401
        sess.go()
        if sess.password_fields() != 1:
            report.product.append('V2 mocked 401: %d visible password field(s), expected exactly one (the key field appears only after a 401)' % sess.password_fields())
            return
        if sess.page.locator('input[name=login]:visible, input[name=username]:visible, input[autocomplete=username]:visible').count():
            report.product.append('V2 mocked 401: a login name field is visible, expected the key (password) field only (no login exists)')
        sess.page.locator('input[type=password]:visible').first.fill(key)
        before = len(sess.calls)
        sess.page.keyboard.press('Enter')
        sess.page.wait_for_timeout(SETTLE_MS)
        sent = [call for call in sess.calls[before:] if call['key'] == key]
        if not sent:
            report.product.append('V2 mocked 401: after the key is entered no /api/jsonrpc request carries it in X-API-Key')
        if sess.keyed:
            report.product.append('V2 mocked 401: the key is sent to %s, expected /api/jsonrpc and /downloads only' % sorted(set(sess.keyed)))
        if sess.context.cookies():
            report.product.append('V2 mocked 401: the page set a cookie after the key was entered')
        if sess.storage() != (0, 0):
            report.product.append('V2 mocked 401: the key was written to web storage')
        if key in sess.page.url:
            report.product.append('V2 mocked 401: the key appears in the page URL')
    finally:
        sess.close()


def _raw_values(page) -> set[str]:
    return set(page.eval_on_selector_all('[data-raw]', 'els => els.map(e => e.getAttribute("data-raw"))'))


def _flat(item: object, prefix: str = '') -> dict[str, str]:
    '''Scalar fields of a result item by name, None values as the string None excluded.'''
    out: dict[str, str] = {}
    if isinstance(item, dict):
        for key, value in item.items():
            if isinstance(value, (dict, list)):
                out.update(_flat(value, prefix + key + '.'))
            elif value is not None:
                out[prefix + key] = value if isinstance(value, str) else json.dumps(value)
    elif isinstance(item, list):
        for element in item:
            out.update({prefix + k: v for k, v in _flat(element).items()})
    return out


def page_equals_result(report: Report, drv: Driver) -> None:
    '''G9 (V4): for every read command a linked page sends, the data-raw values of the page carry every scalar field of the result the Python client returns for the same command and parameters; a command error renders data-testid error-banner with the code and message verbatim and no rows.'''
    for route in routes(drv):
        label = 'G9 page /#%s' % route.lstrip('#') if route else 'G9 index page'
        sess = Session(drv)
        try:
            sess.go(route)
            raw = _raw_values(sess.page)
            for call in sess.calls:
                if call['method'] not in ('backup_snapshots', 'backup_sites_list', 'backup_discovery_status', 'help', 'info', 'backup_list_files', 'backup_libraries_list') or not isinstance(call['params'], dict):
                    continue
                kind, code, message, data = live.request(call['method'], call['params'])
                if kind == 'success':
                    missing = sorted(key for key, value in _flat(data).items() if key.split('.')[-1] not in VOLATILE and value not in raw)
                    if missing:
                        report.product.append('%s: %s %s: the data-raw cells of the page lack the result fields %s of the client result' % (label, call['method'], call['params'], missing[:8]))
                elif kind == 'command_error':
                    banner = sess.page.locator('[data-testid=error-banner]')
                    text = banner.first.inner_text() if banner.count() else ''
                    if str(code) not in text or message not in text:
                        report.product.append('%s: %s answers the error %s %r but data-testid error-banner holds %r' % (label, call['method'], code, message[:60], text[:80]))
                    if sess.page.locator('[data-testid$=-row]').count():
                        report.product.append('%s: %s answers an error but the page renders rows (no demo data)' % (label, call['method']))
        finally:
            sess.close()


def polling(report: Report, drv: Driver) -> None:
    '''G10 (V7, R25) on the page that sends backup_discovery_status: with a controlled clock exactly one extra call per 30 s, none while one is in flight, only the two status commands, a 401 on a poll shows the key field and stops polling.'''
    target = None
    for route in routes(drv):
        probe = Session(drv)
        try:
            probe.go(route)
            if any(call['method'] == 'backup_discovery_status' for call in probe.calls):
                target = route
                break
        finally:
            probe.close()
    if target is None:
        report.product.append('V7 no linked page sends backup_discovery_status, the discovery page that polls it (A8, R25) does not exist')
        return
    sess = Session(drv, clock=True)
    try:
        sess.go(target)

        def count() -> int:
            return sum(1 for call in sess.calls if call['method'] == 'backup_discovery_status')

        first = count()
        loaded = len(sess.calls)
        sess.page.clock.fast_forward(30000)
        sess.page.wait_for_timeout(SETTLE_MS)
        if count() != first + 1:
            report.product.append('V7 after 30 s on the discovery page: %d backup_discovery_status call(s), expected exactly %d (one extra)' % (count(), first + 1))
        sess.hold = True
        sess.page.clock.fast_forward(30000)
        sess.page.wait_for_timeout(SETTLE_MS)
        in_flight = count()
        sess.page.clock.fast_forward(30000)
        sess.page.wait_for_timeout(SETTLE_MS)
        if count() != in_flight:
            report.product.append('V7 a second poll was sent while the first was still in flight (%d calls, expected %d)' % (count(), in_flight))
        sess.hold = False
        sess.release()
        sess.page.wait_for_timeout(SETTLE_MS)
        others = sorted({call['method'] for call in sess.calls[loaded:]} - set(POLL_COMMANDS))
        if others:
            report.product.append('V7 the poll sent commands other than the two status commands: %s' % others)
        sess.override = 401
        sess.page.clock.fast_forward(30000)
        sess.page.wait_for_timeout(SETTLE_MS)
        if sess.password_fields() != 1:
            report.product.append('V7 a 401 on a poll shows %d password field(s), expected the key field (R25)' % sess.password_fields())
        stopped = len(sess.calls)
        sess.page.clock.fast_forward(120000)
        sess.page.wait_for_timeout(SETTLE_MS)
        if len(sess.calls) != stopped:
            report.product.append('V7 after a 401 the page kept polling (%d calls more in 120 s, expected zero)' % (len(sess.calls) - stopped))
    finally:
        sess.close()
