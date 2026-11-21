'''10.18 browser cases of the UI-VUE checks: route table, nav, export controls, logout and the export-card poll.'''

from __future__ import annotations

import hashlib
import posixpath
import urllib.parse
from pathlib import Path
from typing import Any

from pipeline import cmdcases, live
from pipeline.report import Report
from pipeline.vuebase import lan_try
from pipeline.vuebrowser import SETTLE_MS, VOLATILE, Driver, Session, _flat, call_problems

NAV = {'nav-snapshots': '#/snapshots', 'nav-sites': '#/sites', 'nav-discovery': '#/discovery', 'nav-help': '#/help', 'nav-info': '#/info'}
UNKNOWN_EXPORT = '0' * 32
PAGE_SIZE = 100
# page container -> the controls that may exist only there (R27): start only on the files page, delete and the link only on the card.
CONTROLS = {'export-start-snapshot': 'page-files', 'export-start-file': 'page-files', 'export-delete': 'page-export', 'download-link': 'page-export'}
ROW_IDS = {'page-snapshots': 'snap-row', 'page-files': 'file-row', 'page-sites': 'site-row', 'page-libraries': 'library-row'}


def tid(page: Any, name: str) -> Any:
    '''Locator of one data-testid.'''
    return page.locator('[data-testid="%s"]' % name)


def enc(value: str) -> str:
    '''encodeURIComponent.'''
    return urllib.parse.quote(value, safe='')


def hash_of(page: Any) -> str:
    '''The location hash of the page.'''
    return page.evaluate('window.location.hash')


def wait_hash(page: Any, prefix: str, timeout_ms: int = 60000) -> None:
    '''Wait until the location hash starts with prefix; polled from Python because the page CSP forbids the eval of wait_for_function.'''
    for _ in range(timeout_ms // 200):
        if hash_of(page).startswith(prefix):
            return
        page.wait_for_timeout(200)
    raise TimeoutError('the location hash did not start with %s within %d ms (it is %s)' % (prefix, timeout_ms, hash_of(page)))


def reply_data(call: dict) -> Any:
    '''The data of a successful JSON-RPC reply captured by the session, or None.'''
    reply = call.get('reply')
    result = reply.get('result') if isinstance(reply, dict) else None
    return result.get('data') if isinstance(result, dict) and result.get('success') is True else None


def pairs(sess: Session, start: int = 0) -> list[tuple]:
    '''(method, params) of the captured calls from index start.'''
    return [(call['method'], call['params']) for call in sess.calls[start:]]


def known_ids() -> dict:
    '''Ids obtained through the Python client: first snapshot, a directory of it, first site that has libraries.'''
    found: dict = {'sid': None, 'dir': None, 'site': None}
    kind, _, _, snaps = live.request('backup_snapshots', {'limit': PAGE_SIZE})
    if kind == 'success' and isinstance(snaps, dict) and snaps.get('items'):
        found['sid'] = snaps['items'][0]['id']
        kind, _, _, files = live.request('backup_list_files', {'snapshot_id': found['sid'], 'limit': PAGE_SIZE})
        if kind == 'success' and isinstance(files, dict):
            found['dir'] = next((i['path'] for i in files.get('items', []) if i.get('type') == 'dir'), None)
    kind, _, _, sites = live.request('backup_sites_list', {'limit': PAGE_SIZE, 'offset': 0})
    if kind == 'success' and isinstance(sites, dict):
        found['site'] = next((i['site_id'] for i in sites.get('items', []) if i.get('library_count')), None)
    return found


def files_params(sid: str, prefix: str = '', offset: int = 0) -> dict:
    '''Parameters the files page sends (10.18.2 A2).'''
    return {'snapshot_id': sid, 'prefix': prefix, 'offset': offset, 'limit': PAGE_SIZE}


def route_table(ids: dict) -> list[tuple]:
    '''(label, hash route, expected calls, page container, outcome) of 10.18.2; outcome ok = a result page, error = banner and no data.'''
    sid, site = ids['sid'], ids['site']
    table: list[tuple] = [('A1 snapshots', '#/snapshots', [('backup_snapshots', {'limit': PAGE_SIZE})], 'page-snapshots', 'ok')]
    if sid:
        table.append(('A2 files', '#/snapshots/%s/files' % sid, [('backup_list_files', files_params(sid))], 'page-files', 'ok'))
        if ids['dir']:
            table.append(('A2 files prefix', '#/snapshots/%s/files?prefix=%s' % (sid, enc(ids['dir'])),
                          [('backup_list_files', files_params(sid, ids['dir']))], 'page-files', 'ok'))
            table.append(('A2 files prefix offset', '#/snapshots/%s/files?prefix=%s&offset=%d' % (sid, enc(ids['dir']), PAGE_SIZE),
                          [('backup_list_files', files_params(sid, ids['dir'], PAGE_SIZE))], 'page-files', 'ok'))
    table += [('A4 export card, unknown id', '#/exports/' + UNKNOWN_EXPORT, [('backup_download_status', {'export_id': UNKNOWN_EXPORT})], 'page-export', 'error'),
              ('A6 sites', '#/sites', [('backup_sites_list', {'limit': PAGE_SIZE, 'offset': 0})], 'page-sites', 'ok'),
              ('A6 sites query', '#/sites?q=sharepoint', [('backup_sites_list', {'limit': PAGE_SIZE, 'offset': 0, 'query': 'sharepoint'})], 'page-sites', 'ok')]
    if site:
        table.append(('A7 libraries', '#/sites/%s/libraries' % enc(site), [('backup_libraries_list', {'site_id': site, 'limit': PAGE_SIZE, 'offset': 0})], 'page-libraries', 'ok'))
    table += [('A8 discovery', '#/discovery', [('backup_discovery_status', {})], 'page-discovery', 'ok'),
              ('A9 help', '#/help', [('help', {})], 'page-help', 'ok'),
              ('A9 help command', '#/help/backup_snapshots', [('help', {'cmdname': 'backup_snapshots'})], 'page-help', 'ok'),
              ('A10 info page 2', '#/info?page=2', [('info', {'page': 2})], 'page-info', 'ok')]
    return table


def _banner(report: Report, label: str, page: Any, want: tuple | None) -> None:
    '''10.18.6: exactly one error-banner (role alert) with error-code (data-raw numeric) and error-message; no row while it is shown.'''
    banner = tid(page, 'error-banner')
    if banner.count() != 1:
        report.product.append('%s: %d error-banner element(s), expected exactly one' % (label, banner.count()))
        return
    if banner.get_attribute('role') != 'alert':
        report.product.append('%s: error-banner has role %r, expected alert' % (label, banner.get_attribute('role')))
    code, message = tid(page, 'error-code'), tid(page, 'error-message')
    if code.count() != 1 or message.count() != 1 or not message.inner_text().strip():
        report.product.append('%s: the error-banner lacks one error-code and one non-empty error-message' % label)
        return
    raw = code.get_attribute('data-raw')
    if want is not None and raw not in want:
        report.product.append('%s: error-code data-raw %r, expected one of %s' % (label, raw, want))
    if page.locator('[data-testid$="-row"]').count():
        report.product.append('%s: the page renders rows while an error-banner is shown (no demo data)' % label)


def _cells(report: Report, label: str, page: Any, call: tuple) -> None:
    '''G9n: every scalar of the client result for the same command and parameters is a cell with data-field and data-raw (volatile by name excluded).'''
    kind, _, _, data = live.request(call[0], call[1])
    if kind != 'success':
        report.state.append('%s: the client answers %s to %s %s, the page cells are not compared' % (label, kind, call[0], call[1]))
        return
    raw = set(page.eval_on_selector_all('[data-raw]', 'els => els.map(e => e.getAttribute("data-raw"))'))
    fields = {'.'.join(part for part in name.split('.') if not part.isdigit()) for name in page.eval_on_selector_all('[data-field]', 'els => els.map(e => e.getAttribute("data-field"))')}  # the SPA indexes list elements, the result keys do not
    flat = {key: value for key, value in _flat(data).items() if key.split('.')[-1] not in VOLATILE}
    lost = sorted(key for key, value in flat.items() if value not in raw)
    nameless = sorted(key for key in flat if '.'.join(part for part in (key.split('.', 1)[1] if key.split('.')[0] in ('items', 'nodes', 'entries') and '.' in key else key).split('.') if not part.isdigit()) not in fields)  # row cells are named by the item key; numeric segments are list indexes on both sides
    if lost:
        report.product.append('%s: the data-raw cells lack the result fields %s of the client result' % (label, lost[:8]))
    if nameless:
        report.product.append('%s: no cell carries data-field %s of the client result' % (label, nameless[:8]))
    items = data.get('items') if isinstance(data, dict) else None
    row = ROW_IDS.get(next((c for c in ROW_IDS if tid(page, c).count()), ''))
    if row and isinstance(items, list) and tid(page, row).count() != len(items):
        report.product.append('%s: %d %s element(s), the result holds %d items' % (label, tid(page, row).count(), row, len(items)))


def _controls(report: Report, label: str, page: Any, container: str) -> None:
    '''R27: the export controls exist only on their page.'''
    for name, where in CONTROLS.items():
        if where != container and tid(page, name).count():
            report.product.append('%s: the control %s exists on %s, it may exist only on %s (R27)' % (label, name, container, where))


def route_cases(report: Report, drv: Driver) -> None:
    '''V8 / G9n: every route of 10.18.2 sends exactly its row's command and parameters and renders its page container and result cells.'''
    ids = known_ids()
    if not ids['sid'] or not ids['site']:
        report.state.append('V8 routes: the client lists no snapshot or no site with libraries (ids %s): the A2 and A7 routes are not executed' % ids)
    for label, route, expected, container, outcome in route_table(ids):
        label = 'V8 %s %s' % (label, route)
        sess = Session(drv)
        try:
            sess.go(route)
            if tid(sess.page, container).count() != 1:
                report.product.append('%s: %d %s container(s), expected exactly one' % (label, tid(sess.page, container).count(), container))
            sent = pairs(sess)
            if sent != expected:
                report.product.append('%s: the page sent %s, expected exactly %s' % (label, sent, expected))
            report.product.extend(call_problems(label, sess.calls))
            _controls(report, label, sess.page, container)
            if outcome == 'ok':
                if tid(sess.page, 'error-banner').count():
                    report.product.append('%s: an error-banner is shown while the client answers success' % label)
                else:
                    _cells(report, label, sess.page, expected[0])
            else:
                _banner(report, label, sess.page, ('404', '410'))
                for name in ('export-card', 'download-link'):
                    if tid(sess.page, name).count():
                        report.product.append('%s: %s is shown for an unknown export (error-banner only)' % (label, name))
        finally:
            sess.close()
    _unknown_route(report, drv)
    _paging(report, drv, ids)
    _search(report, drv)


def _unknown_route(report: Report, drv: Driver) -> None:
    '''10.18.2: an unknown hash route renders page-notfound with error-banner 404 'route not found' and sends no command.'''
    sess = Session(drv)
    try:
        sess.go('#/no/such/route')
        label = 'V8 unknown route #/no/such/route'
        if tid(sess.page, 'page-notfound').count() != 1:
            report.product.append('%s: no page-notfound' % label)
        _banner(report, label, sess.page, ('404',))
        if 'route not found' not in tid(sess.page, 'error-message').first.inner_text():
            report.product.append('%s: the error-message is not "route not found"' % label)
        if sess.calls:
            report.product.append('%s: the page sent %s, expected no command' % (label, pairs(sess)))
    finally:
        sess.close()


def _paging(report: Report, drv: Driver, ids: dict) -> None:
    '''A2: page-prev is disabled at offset 0, page-next moves the hash offset by 100 and sends exactly one backup_list_files.'''
    if not ids['sid'] or not ids['dir']:
        return
    sess = Session(drv)
    label = 'V8 A2 paging'
    try:
        sess.go('#/snapshots/%s/files?prefix=%s' % (ids['sid'], enc(ids['dir'])))
        kind, _, _, data = live.request('backup_list_files', files_params(ids['sid'], ids['dir']))
        if not (tid(sess.page, 'page-prev').count() == 1 and tid(sess.page, 'page-next').count() == 1):
            report.product.append('%s: page-prev and page-next are not both present' % label)
            return
        if not tid(sess.page, 'page-prev').is_disabled():
            report.product.append('%s: page-prev is enabled at offset 0' % label)
        total = data.get('total', 0) if kind == 'success' and isinstance(data, dict) else 0
        if total <= PAGE_SIZE:
            report.state.append('%s: the listing holds %s node(s), page-next is not exercised' % (label, total))
            return
        start = len(sess.calls)
        tid(sess.page, 'page-next').click()
        sess.page.wait_for_timeout(SETTLE_MS)
        want = [('backup_list_files', files_params(ids['sid'], ids['dir'], PAGE_SIZE))]
        if pairs(sess, start) != want or 'offset=%d' % PAGE_SIZE not in hash_of(sess.page):
            report.product.append('%s: page-next sent %s and left the hash %s, expected exactly %s and offset=%d' % (label, pairs(sess, start), hash_of(sess.page), want, PAGE_SIZE))
    finally:
        sess.close()


def _search(report: Report, drv: Driver) -> None:
    '''A6: Enter in search-input and the button search-submit set q, reset the offset and send backup_sites_list with query.'''
    label = 'V8 A6 search'
    for how in ('Enter', 'search-submit'):
        sess = Session(drv)
        try:
            sess.go('#/sites')
            tid(sess.page, 'search-input').fill('sharepoint')
            start = len(sess.calls)
            if how == 'Enter':
                sess.page.keyboard.press('Enter')
            else:
                tid(sess.page, 'search-submit').click()
            sess.page.wait_for_timeout(SETTLE_MS)
            want = [('backup_sites_list', {'limit': PAGE_SIZE, 'offset': 0, 'query': 'sharepoint'})]
            if pairs(sess, start) != want or 'q=sharepoint' not in hash_of(sess.page):
                report.product.append('%s via %s: sent %s with the hash %s, expected exactly %s and q=sharepoint' % (label, how, pairs(sess, start), hash_of(sess.page), want))
        finally:
            sess.close()


def nav_cases(report: Report, drv: Driver) -> None:
    '''V8 / 10.18.3: the empty hash becomes #/snapshots; one nav with the five plain anchors on every page; nav- is the nav's own prefix; the index links are the nav plus row links.'''
    sess = Session(drv)
    try:
        sess.go('')
        if hash_of(sess.page) != '#/snapshots':
            report.product.append('V8 index: the empty hash became %r, expected #/snapshots' % hash_of(sess.page))
        got = {name: tid(sess.page, name).get_attribute('href') for name in NAV}
        if got != NAV:
            report.product.append('V8 nav: the anchors are %s, expected exactly %s' % (got, NAV))
        if tid(sess.page, 'nav').count() != 1:
            report.product.append('V8 nav: %d nav element(s), expected one' % tid(sess.page, 'nav').count())
        extra = sess.page.locator('[data-testid^="nav-"]').count() - sess.page.locator('[data-testid="nav"] [data-testid^="nav-"]').count()
        if extra or sess.page.locator('[data-testid^="nav-"]').count() != len(NAV):
            report.product.append('V8 nav: test ids with the prefix nav- are not exactly the %d anchors of the nav' % len(NAV))
        rows = sess.page.eval_on_selector_all('[data-testid="snap-open"]', 'els => els.map(e => e.getAttribute("href"))')
        links = set(sess.links())
        if (links - set(NAV.values()) - set(rows)) or (set(NAV.values()) - links):
            report.product.append('V8 index links: %s, expected exactly the nav %s plus the snap-open rows %s' % (sorted(links), sorted(NAV.values()), rows[:3]))
        kind, _, _, snaps = live.request('backup_snapshots', {'limit': PAGE_SIZE})
        if kind == 'success' and isinstance(snaps, dict) and snaps.get('items') and rows and rows[0] != '#/snapshots/%s/files' % snaps['items'][0]['id']:
            report.product.append('V8 snap-open: first href %s, expected #/snapshots/%s/files' % (rows[0], snaps['items'][0]['id']))
    finally:
        sess.close()
    for route in ('#/sites', '#/discovery', '#/help', '#/info', '#/signed-out', '#/no/such/route'):
        sess = Session(drv)
        try:
            sess.go(route)
            if tid(sess.page, 'nav').count() != 1:
                report.product.append('V8 nav on %s: %d nav element(s), expected one on every page' % (route, tid(sess.page, 'nav').count()))
        finally:
            sess.close()
    for name, route in NAV.items():
        sess = Session(drv)
        try:
            sess.go('#/snapshots')
            tid(sess.page, name).click()
            sess.page.wait_for_timeout(SETTLE_MS)
            if hash_of(sess.page) != route:
                report.product.append('V8 nav click %s: the hash is %r, expected %r (a plain anchor)' % (name, hash_of(sess.page), route))
        finally:
            sess.close()


def auth_ids(report: Report, drv: Driver) -> None:
    '''V2 / 10.18.6: mount id app, one script /assets/app.js, logout always present, no key form while open; the key ids and both submissions after a 401.'''
    sess = Session(drv)
    try:
        sess.go('#/snapshots')
        if sess.page.locator('#app > *').count() < 1:
            report.product.append('V2 mount: #app has no child after the page settled (the SPA is not mounted at id app)')
        scripts = sess.page.eval_on_selector_all('script[src]', 'els => els.map(e => e.getAttribute("src"))')
        if scripts != ['/assets/app.js']:
            report.product.append('V2 mount: the page loads the scripts %s, expected only /assets/app.js' % scripts)
        if tid(sess.page, 'logout').count() != 1:
            report.product.append('V2 logout: %d logout control(s) while the service is open, expected one (O-1: always present)' % tid(sess.page, 'logout').count())
        if tid(sess.page, 'key-form').count():
            report.product.append('V2 key-form is present while the service is open (shown only after a 401)')
    finally:
        sess.close()
    sess = Session(drv)
    try:
        sess.override = 401
        sess.go()
        names = ('key-form', 'key-input', 'key-submit')
        if any(tid(sess.page, name).count() != 1 for name in names):
            report.product.append('V2 key ids: %s counts after a 401, expected one each' % {name: tid(sess.page, name).count() for name in names})
            return
        field = tid(sess.page, 'key-input')
        if (field.get_attribute('type'), field.get_attribute('name'), field.get_attribute('autocomplete')) != ('password', 'api-key', 'off'):
            report.product.append('V2 key-input: attributes type/name/autocomplete are %s, expected password/api-key/off' % ((field.get_attribute('type'), field.get_attribute('name'), field.get_attribute('autocomplete')),))
        field.fill('kclick-test-key')
        start = len(sess.calls)
        tid(sess.page, 'key-submit').click()
        sess.page.wait_for_timeout(SETTLE_MS)
        if not [call for call in sess.calls[start:] if call['key'] == 'kclick-test-key']:
            report.product.append('V2 key-submit: the click sent no /api/jsonrpc request with the key in X-API-Key')
    finally:
        sess.close()


def _target() -> tuple | None:
    '''(snapshot id, smallest file entry, page offset of that file under its directory) or None.'''
    snapshot = cmdcases._first_snapshot()
    entry = cmdcases._smallest_file(snapshot['id']) if snapshot else None
    if not entry:
        return None
    parent = posixpath.dirname(entry['path'])
    for offset in range(0, 5000, PAGE_SIZE):
        kind, _, _, data = live.request('backup_list_files', files_params(snapshot['id'], parent, offset))
        items = data.get('items', []) if kind == 'success' and isinstance(data, dict) else []
        if not items:
            return None
        if any(item.get('path') == entry['path'] for item in items):
            return snapshot['id'], entry, parent, offset
    return None


def _files_route(sid: str, parent: str, offset: int) -> str:
    '''Hash route of a files page.'''
    query = [('prefix=' + enc(parent))] if parent else []
    query += ['offset=%d' % offset] if offset else []
    return '#/snapshots/%s/files%s' % (sid, '?' + '&'.join(query) if query else '')


def export_cases(report: Report, drv: Driver, root: str) -> None:
    '''V5 / G7d in S1: start (file and snapshot), the export card, the plain link download, delete; every export the case made is deleted.'''
    target = _target()
    if target is None:
        report.state.append('V5 export cases: the client lists no snapshot with a file the files page shows')
        return
    sid, entry, parent, offset = target
    path, made = entry['path'], []
    sess = Session(drv)
    try:
        sess.go(_files_route(sid, parent, offset))
        rows = sess.page.eval_on_selector_all('[data-testid="file-row"]', 'rows => rows.map(r => [(r.querySelector("[data-field=type]") || r).getAttribute("data-raw"), r.querySelectorAll("[data-testid=export-start-file]").length])')
        wrong = [row for row in rows if row[1] != (1 if row[0] == 'file' else 0)]
        if wrong or tid(sess.page, 'export-start-snapshot').count() != 1:
            report.product.append('V5 start controls: file rows [type, controls] %s differ from one control per file and none per directory, or export-start-snapshot is not unique (%d)' % (wrong[:3], tid(sess.page, 'export-start-snapshot').count()))
        button = sess.page.locator('[data-testid="export-start-file"]')
        index = next((i for i in range(button.count()) if button.nth(i).get_attribute('data-path') == path), None)
        if index is None:
            report.product.append('V5 export-start-file: no control with data-path %r on the files page' % path)
            return
        start = len(sess.calls)
        button.nth(index).click()
        wait_hash(sess.page, '#/exports/')
        sess.page.wait_for_timeout(SETTLE_MS)
        sent = [call for call in sess.calls[start:] if call['method'] == 'backup_prepare_download']
        meta = reply_data(sent[0]) if sent else None
        if len(sent) != 1 or sent[0]['params'] != {'snapshot_id': sid, 'file_path': path} or not isinstance(meta, dict):
            report.product.append('V5 export-start-file: the click sent %s, expected exactly one backup_prepare_download %s' % (pairs(sess, start), {'snapshot_id': sid, 'file_path': path}))
            return
        eid = meta['export_id']
        made.append(eid)
        if hash_of(sess.page) != '#/exports/' + eid or tid(sess.page, 'page-export').count() != 1:
            report.product.append('V5 export-start-file: the hash is %s, expected #/exports/%s with page-export' % (hash_of(sess.page), eid))
        _card(report, sess, eid, meta, root)
        _delete(report, sess, sid, eid, root)
    finally:
        sess.close()
        for eid in made:
            live.request('backup_delete_export', {'export_id': eid})
    _snapshot_start(report, drv, sid, parent, offset)


def _card(report: Report, sess: Session, eid: str, meta: dict, root: str) -> None:
    '''G7d (3)-(4): card cells equal the client status result; the plain link downloads the file with the metadata size and sha256.'''
    page = sess.page
    _cells(report, 'V5 export card', page, ('backup_download_status', {'export_id': eid}))
    for field in ('export_id', 'snapshot_id', 'path', 'filename', 'size_bytes', 'sha256', 'created_at', 'expires_at'):
        if page.locator('[data-testid="export-card"] [data-field="%s"]' % field).count() != 1:
            report.product.append('V5 export-card: no single cell with data-field %s' % field)
    link = tid(page, 'download-link')
    want = '/downloads/%s/%s' % (eid, meta['filename'])
    if link.count() != 1 or urllib.parse.unquote(link.get_attribute('href') or '') != want or link.get_attribute('target') or link.get_attribute('download') is None:
        report.product.append('V5 download-link: href %r target %r, expected a plain anchor with download and href %s' % (link.get_attribute('href'), link.get_attribute('target'), want))
        return
    seen: list = []
    page.on('response', lambda reply: seen.append(reply) if '/downloads/' in reply.url else None)
    start = len(sess.calls)
    with page.expect_download(timeout=60000) as info:
        link.click()
    download = info.value
    body = Path(download.path()).read_bytes()
    if len(body) != meta['size_bytes'] or hashlib.sha256(body).hexdigest() != meta['sha256'] or download.suggested_filename != meta['filename']:
        report.product.append('V5 download-link click: %d bytes sha256 %s name %r, expected %s bytes sha256 %s name %r' % (len(body), hashlib.sha256(body).hexdigest()[:12], download.suggested_filename, meta['size_bytes'], meta['sha256'][:12], meta['filename']))
    if any('set-cookie' in reply.headers for reply in seen) or sess.context.cookies():
        report.product.append('V5 download-link click: the /downloads answer carries Set-Cookie or a cookie was set')
    if len(sess.calls) != start:
        report.product.append('V5 download-link click: the click sent %s, expected no JSON-RPC call' % pairs(sess, start))


def _delete(report: Report, sess: Session, sid: str, eid: str, root: str) -> None:
    '''G7d (5): export-delete sends one backup_delete_export, asks no confirmation, navigates to the files page; the export is gone.'''
    def on_dialog(dialog) -> None:
        dialogs.append(dialog.message)
        dialog.dismiss()
    page = sess.page
    dialogs: list[str] = []
    page.on('dialog', on_dialog)
    start = len(sess.calls)
    tid(page, 'export-delete').click()
    wait_hash(page, '#/snapshots/%s/files' % sid)
    page.wait_for_timeout(SETTLE_MS)
    sent = [call for call in sess.calls[start:] if call['method'] == 'backup_delete_export']
    if len(sent) != 1 or sent[0]['params'] != {'export_id': eid} or dialogs:
        report.product.append('V5 export-delete: sent %s with dialogs %s, expected exactly one backup_delete_export %s and no confirmation' % (pairs(sess, start), dialogs, {'export_id': eid}))
    if tid(page, 'page-files').count() != 1:
        report.product.append('V5 export-delete: page-files did not appear after the delete')
    kind, code, _, _ = live.request('backup_download_status', {'export_id': eid})
    if not (kind == 'command_error' and code == 404):
        report.product.append('V5 export-delete: backup_download_status after the delete answers %s %s, expected 404' % (kind, code))
    got = lan_try(report, 'V5 GET the link after the delete', root, 'GET', '/downloads/%s/x' % eid)
    if got is not None and got[0] != 404:
        report.product.append('V5 export-delete: GET of the link after the delete answers %d, expected 404' % got[0])


def _snapshot_start(report: Report, drv: Driver, sid: str, parent: str, offset: int) -> None:
    '''G7d (2): export-start-snapshot sends backup_prepare_download {snapshot_id} with file_path ABSENT.

    The request is aborted before it reaches the service: staging a whole production snapshot as a plaintext archive is heavy and is not
    needed to assert the request the control sends (it is asserted by the captured request; no export exists afterwards).'''
    sess = Session(drv)
    try:
        sess.page.route('**/api/jsonrpc', lambda route: route.abort() if 'backup_prepare_download' in (route.request.post_data or '') else route.fallback())
        sess.go(_files_route(sid, parent, offset))
        start = len(sess.calls)
        tid(sess.page, 'export-start-snapshot').click()
        sess.page.wait_for_timeout(SETTLE_MS)
        sent = [call for call in sess.calls[start:] if call['method'] == 'backup_prepare_download']
        if len(sent) != 1 or sent[0]['params'] != {'snapshot_id': sid}:
            report.product.append('V5 export-start-snapshot: the click sent %s, expected exactly one backup_prepare_download %s with no file_path key' % (pairs(sess, start), {'snapshot_id': sid}))
    finally:
        sess.close()


def logout_cases(report: Report, drv: Driver) -> None:
    '''V7 / G10x (1)-(2): logout routes to #/signed-out and sends nothing; a poll answered after the logout is discarded; signin resumes.'''
    sess = Session(drv, clock=True)
    try:
        sess.go('#/snapshots')
        before = len(sess.calls)
        tid(sess.page, 'logout').click()
        sess.page.wait_for_timeout(SETTLE_MS)
        link = tid(sess.page, 'signin')
        if hash_of(sess.page) != '#/signed-out' or tid(sess.page, 'page-signed-out').count() != 1 or link.get_attribute('href') != '#/snapshots':
            report.product.append('V7 logout: hash %r, page-signed-out %d, signin href %r, expected #/signed-out, one page-signed-out and signin #/snapshots' % (hash_of(sess.page), tid(sess.page, 'page-signed-out').count(), link.get_attribute('href')))
        sess.page.clock.fast_forward(120000)
        sess.page.wait_for_timeout(SETTLE_MS)
        if len(sess.calls) != before:
            report.product.append('V7 logout: %s sent after the click and 120 s, expected ZERO calls of any method (R28)' % pairs(sess, before))
        link.click()
        sess.page.wait_for_timeout(SETTLE_MS)
        if hash_of(sess.page) != '#/snapshots' or ('backup_snapshots', {'limit': PAGE_SIZE}) not in pairs(sess, before):
            report.product.append('V7 signin: hash %r calls %s, expected #/snapshots and the calls resumed' % (hash_of(sess.page), pairs(sess, before)))
    finally:
        sess.close()
    sess = Session(drv, clock=True)
    try:
        sess.go('#/discovery')
        sess.hold = True
        sess.page.clock.fast_forward(30000)
        sess.page.wait_for_timeout(SETTLE_MS)
        sent = len(sess.calls)
        tid(sess.page, 'logout').click()
        sess.page.wait_for_timeout(SETTLE_MS)
        try:
            sess.release()
        except Exception as exc:
            report.info.append('V7 logout: releasing the held poll raised %s (the request was already aborted by the SPA)' % type(exc).__name__)
        sess.page.wait_for_timeout(SETTLE_MS)
        sess.page.clock.fast_forward(120000)
        sess.page.wait_for_timeout(SETTLE_MS)
        if len(sess.calls) != sent or tid(sess.page, 'page-discovery').count() or tid(sess.page, 'page-signed-out').count() != 1:
            report.product.append('V7 logout during a poll: %d calls after (was %d), page-discovery %d, page-signed-out %d, expected no call and no render after the logout' % (len(sess.calls), sent, tid(sess.page, 'page-discovery').count(), tid(sess.page, 'page-signed-out').count()))
    finally:
        sess.close()


def export_poll_case(report: Report, drv: Driver) -> None:
    '''V7 / G10x (3), S1: the card of a FINAL export (non-empty sha256, integer size_bytes) never polls: zero extra backup_download_status in 60 s.'''
    made = cmdcases._prepare_small(report, 'V7 export card poll')
    if not made:
        return
    meta = made[2]
    sess = Session(drv, clock=True)
    try:
        sess.go('#/exports/' + meta['export_id'])
        first = len(sess.calls)
        if first != 1 or pairs(sess) != [('backup_download_status', {'export_id': meta['export_id']})]:
            report.product.append('V7 export card: the page sent %s, expected exactly one backup_download_status' % pairs(sess))
        sess.page.clock.fast_forward(60000)
        sess.page.wait_for_timeout(SETTLE_MS)
        if len(sess.calls) != first:
            report.product.append('V7 export card: %s after 60 s on a FINAL export, expected ZERO extra backup_download_status calls' % pairs(sess, first))
    finally:
        sess.close()
        live.request('backup_delete_export', {'export_id': meta['export_id']})
