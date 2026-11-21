'''Revision 11 browser and static cases of the UI-VUE checks (matrix TODO 10.19, block UI-FILTER).

The single filter page '#/', the service page '#/service' and the replaced nav, routes and test ids of 10.19.2, 10.19.7 and 10.19.8 are
driven through the headless driver of pipeline.vuebrowser. Every locator is counted before it is used, so an SPA that lacks a test id
is a PRODUCT finding and never a timeout. The named checks vue_* compose the unchanged cases of pipeline.vuechecks with these.
'''

from __future__ import annotations

import hashlib
import json
from typing import Any, Callable
from unittest import mock

from pipeline import b4base, live, rev11, vuebrowser, vuebuild, vuechecks, vueroutes
from pipeline.checks import CheckFailure
from pipeline.report import Report
from pipeline.vuebase import lan_try, spa_files, tracked_files
from pipeline.vuebrowser import SETTLE_MS, Session, call_problems
from pipeline.vueroutes import hash_of, pairs, tid, wait_hash

NAV = {'nav-search': '#/', 'nav-service': '#/service'}
MAIN_IDS = ('page-main', 'filter-panel', 'filter-sites', 'filter-dates', 'name-input', 'filter-apply', 'filter-reset', 'result-area')
OLD_ROUTES = ('#/snapshots', '#/sites', '#/discovery', '#/help', '#/help/backup_snapshots', '#/info', '#/snapshots/abcdef12/files', '#/sites/site-1/libraries')
NEW_COMMANDS = ('backup_filter_options', 'backup_search_files', 'backup_suggest_names')
GROUPS11 = ('filters', 'autocomplete', 'datelabel', 'service-sections')
SEARCH_KEYS = {'site_ids', 'dates', 'name_part', 'limit', 'offset'}
ACTIONS: Any = vuebrowser.ACTIONS
ACTIONS.update({'backup_filter_options': ((), ('site_ids',), {}), 'backup_search_files': ((), ('site_ids', 'dates', 'name_part', 'limit', 'offset'), {'limit': 100}),
                'backup_suggest_names': (('text',), ('site_ids', 'dates', 'limit'), {'limit': 10})})


def compose(name: str, old: Callable[[], None] | None, extra: Callable[[Report], None]) -> None:
    '''Run the unchanged check body and the revision 11 cases and raise one CheckFailure holding both results.

    Args:
        name: the named check.
        old: the body of the check before revision 11, or None when revision 11 replaces it.
        extra: the revision 11 cases, filling a report.

    Returns:
        None.
    '''
    lines: list[str] = []
    for body in ([old] if old else []) + [lambda: _finish(name, extra)]:
        try:
            body()
        except CheckFailure as exc:
            lines.append(str(exc))
    if lines:
        raise CheckFailure('\n'.join(lines))


def _finish(name: str, extra: Callable[[Report], None]) -> None:
    '''Fill a report with the extra cases and finish it.

    Args:
        name: the named check.
        extra: the revision 11 cases.

    Returns:
        None.
    '''
    report = Report()
    extra(report)
    report.finish(name + ' (revision 11)')


class Cases:
    '''The revision 11 browser cases of one run.

    Attributes:
        report: the findings collector.
        drv: the headless driver.
        root: the SPA endpoint URL.
    '''

    def __init__(self, report: Report, drv: Any, root: str) -> None:
        '''Keep the run parts.'''
        self.report, self.drv, self.root = report, drv, root

    def bad(self, text: str) -> None:
        '''PRODUCT finding.

        Args:
            text: what differs.

        Returns:
            None.
        '''
        self.report.product.append(text)

    def have(self, label: str, page: Any, names: tuple[str, ...]) -> bool:
        '''PRODUCT finding for every test id that is absent.

        Args:
            label: the case label.
            page: the page.
            names: the test ids that must exist.

        Returns:
            True when every id exists.
        '''
        missing = [name for name in names if tid(page, name).count() == 0]
        if missing:
            self.bad('%s: the page has no element with data-testid %s' % (label, missing))
        return not missing

    def newest(self) -> str:
        '''Return the newest backup date of the live snapshots.

        Returns:
            The ISO date, or an empty string.
        '''
        days = rev11.Context().days
        return days[-1] if days else ''

    def nav_ids(self) -> None:
        '''10.19.2 NAV: one nav on every page with exactly nav-search (#/) and nav-service (#/service) and the main page container on #/.

        Returns:
            None.
        '''
        for route in ('', '#/service', '#/no/such/route'):
            sess = Session(self.drv)
            try:
                sess.go(route)
                page = sess.page
                ids = sorted(page.eval_on_selector_all('[data-testid^="nav-"]', 'els => els.map(e => e.getAttribute("data-testid"))'))
                hrefs = {name: tid(page, name).first.get_attribute('href') for name in NAV if tid(page, name).count()}
                if ids != sorted(NAV) or hrefs != NAV or tid(page, 'nav').count() != 1:
                    self.bad('V2 nav on #%s: the nav- test ids are %s with hrefs %s, expected exactly %s inside one nav' % (route.lstrip('#'), ids, hrefs, NAV))
                if not route and tid(page, 'page-main').count() != 1:
                    self.bad('V1 index: no page-main container on #/ (hash %r)' % hash_of(page))
            finally:
                sess.close()

    def load_calls(self) -> None:
        '''L1: the main page loads backup_filter_options then backup_search_files for the newest date with the exact key sets and every filter id.

        Returns:
            None.
        '''
        sess = Session(self.drv)
        try:
            sess.go('')
            want = [('backup_filter_options', {}), ('backup_search_files', {'dates': [self.newest()], 'limit': 100})]
            sent = [(m, p) for m, p in pairs(sess) if not (m == 'backup_search_files' and isinstance(p, dict) and p.get('offset') == 0)] + [(m, {k: v for k, v in p.items() if k != 'offset'}) for m, p in pairs(sess) if m == 'backup_search_files' and isinstance(p, dict) and p.get('offset') == 0]
            if sorted(sent, key=lambda item: item[0]) != want:
                self.bad('V4 L1 load of #/: the page sent %s, expected exactly %s (offset 0 may be sent)' % (pairs(sess), want))
            self.report.product.extend(call_problems('V4 L1 load of #/', sess.calls))
            self.have('V4 L1', sess.page, MAIN_IDS)
        finally:
            sess.close()

    def site_tick(self) -> None:
        '''L2: ticking a site sends exactly one backup_filter_options with the ticked site and no search.

        Returns:
            None.
        '''
        sess = Session(self.drv)
        try:
            sess.go('')
            if not self.have('V4 L2', sess.page, ('site-check',)):
                return
            raw = tid(sess.page, 'site-check').first.get_attribute('data-raw')
            start = len(sess.calls)
            tid(sess.page, 'site-check').first.click()
            sess.page.wait_for_timeout(SETTLE_MS)
            if pairs(sess, start) != [('backup_filter_options', {'site_ids': [raw]})]:
                self.bad('V4 L2 tick of a site: the page sent %s, expected exactly [backup_filter_options {site_ids: [%s]}]' % (pairs(sess, start), raw))
        finally:
            sess.close()

    def apply_one(self) -> None:
        '''L3: filter-apply sends exactly one backup_search_files whose keys are the search keys, no empty array or string, limit 100.

        Returns:
            None.
        '''
        sess = Session(self.drv)
        try:
            sess.go('')
            if not self.have('V4 L3', sess.page, ('filter-apply',)):
                return
            start = len(sess.calls)
            tid(sess.page, 'filter-apply').click()
            sess.page.wait_for_timeout(SETTLE_MS)
            sent = pairs(sess, start)
            params = sent[0][1] if len(sent) == 1 and isinstance(sent[0][1], dict) else {}
            if len(sent) != 1 or sent[0][0] != 'backup_search_files' or not set(params) <= SEARCH_KEYS or params.get('limit') != 100 or any(v in ([], '', None) for v in params.values()):
                self.bad('V4 L3 apply: the click sent %s, expected exactly one backup_search_files with keys within %s, limit 100 and no empty value' % (sent, sorted(SEARCH_KEYS)))
        finally:
            sess.close()

    def wildcard_rows(self) -> None:
        '''L4: the name pattern with a star lists only names that start with it, equal to the client result of the same parameters.

        Returns:
            None.
        '''
        sess = Session(self.drv)
        try:
            sess.go('')
            if not self.have('V4 L4', sess.page, ('name-input', 'filter-apply')):
                return
            tid(sess.page, 'name-input').fill('акт*')
            start = len(sess.calls)
            tid(sess.page, 'filter-apply').click()
            sess.page.wait_for_timeout(SETTLE_MS)
            sent = [p for m, p in pairs(sess, start) if m == 'backup_search_files' and isinstance(p, dict)]
            shown = sess.page.eval_on_selector_all('[data-testid=result-row]', 'rows => rows.map(r => (r.querySelector("[data-field=name]") || r).getAttribute("data-raw"))')
            kind, _, _, data = live.request('backup_search_files', sent[0]) if sent else ('none', 0, '', {})
            wanted = [item['name'] for item in data.get('items', [])] if kind == 'success' and isinstance(data, dict) else None
            if not sent or shown != wanted or any(not rev11.key(str(name)).startswith('акт') for name in shown):
                self.bad('V9 L4 name акт*: the page sent %s and shows %s, expected the client names %s, all starting with акт' % (sent, shown[:5], wanted if wanted is None else wanted[:5]))
        finally:
            sess.close()

    def columns(self) -> None:
        '''L5: exactly three header cells and no key, sharepoint/ or .dup- fragment in any result row text.

        Returns:
            None.
        '''
        sess = Session(self.drv)
        try:
            sess.go('')
            page = sess.page
            heads = page.locator('[data-testid=result-table] th').count()
            if heads != 3 or not self.have('V9 L5', page, ('col-site', 'col-name', 'col-date')):
                self.bad('V9 L5: %d header cells in result-table, expected exactly three (col-site, col-name, col-date)' % heads)
            texts = page.eval_on_selector_all('[data-testid=result-row]', 'rows => rows.map(r => r.innerText)')
            leaked = [text[:60] for text in texts if '.dup-' in text or 'sharepoint/' in text or rev11.KEY_SEGMENT.search(text)]
            if leaked:
                self.bad('V9 L5: result rows show an identifier fragment: %s' % leaked[:3])
        finally:
            sess.close()

    def download_row(self) -> None:
        '''L6: result-download of the smallest row sends one backup_prepare_download and opens the inline export card; the link downloads the exact bytes.

        Returns:
            None.
        '''
        sess = Session(self.drv)
        made: list[str] = []
        try:
            sess.go('')
            page = sess.page
            rows = tid(page, 'result-row')
            if not self.have('V5 L6', page, ('result-row', 'result-download')):
                return
            sizes = page.eval_on_selector_all('[data-testid=result-row]', 'rows => rows.map(r => Number(r.getAttribute("data-size")))')
            index = sizes.index(min(sizes))
            row = rows.nth(index)
            want = {'snapshot_id': row.get_attribute('data-snapshot-id'), 'file_path': row.get_attribute('data-path')}
            start = len(sess.calls)
            row.locator('[data-testid=result-download]').first.click()
            page.wait_for_timeout(SETTLE_MS * 3)
            sent = [c for c in sess.calls[start:] if c['method'] == 'backup_prepare_download']
            meta = vueroutes.reply_data(sent[0]) if sent else None
            if len(sent) != 1 or sent[0]['params'] != want or not isinstance(meta, dict):
                self.bad('V5 L6 result-download: the click sent %s, expected exactly one backup_prepare_download %s' % (pairs(sess, start), want))
                return
            made.append(meta['export_id'])
            if page.locator('[data-testid=export-panel] [data-testid=export-card]').count() != 1 or hash_of(page).startswith('#/exports/'):
                self.bad('V5 L6: no inline export-card inside export-panel on the main page (hash %s)' % hash_of(page))
            vueroutes._card(self.report, sess, meta['export_id'], meta, self.root)
        finally:
            sess.close()
            for export_id in made:
                live.request('backup_delete_export', {'export_id': export_id})

    def autocomplete(self) -> None:
        '''L7: the drop-down opens only after 250 ms and 2 characters with one suggest call, keyboard pick fills and applies, Escape closes, logout sends nothing.

        Returns:
            None.
        '''
        sess = Session(self.drv, clock=True)
        try:
            sess.go('')
            page = sess.page
            if not self.have('V9 L7', page, ('name-input',)):
                return
            start = len(sess.calls)
            tid(page, 'name-input').fill('акт')
            page.clock.fast_forward(200)
            page.wait_for_timeout(SETTLE_MS)
            early = [m for m, _ in pairs(sess, start) if m == 'backup_suggest_names']
            page.clock.fast_forward(100)
            page.wait_for_timeout(SETTLE_MS)
            late = [p for m, p in pairs(sess, start) if m == 'backup_suggest_names']
            if early or len(late) != 1 or not isinstance(late[0], dict) or late[0].get('text') != 'акт' or not set(late[0]) <= {'text', 'limit', 'site_ids', 'dates'}:
                self.bad('V9 L7: backup_suggest_names calls before 250 ms %d and after %s, expected none and exactly one with text акт' % (len(early), late))
                return
            items = tid(page, 'name-suggest-item')
            if tid(page, 'name-suggest').count() != 1 or not 0 < items.count() <= 10:
                self.bad('V9 L7: the listbox holds %d items, expected 1 to 10' % items.count())
                return
            first = items.first.get_attribute('data-raw') or ''
            before = len(sess.calls)
            page.keyboard.press('ArrowDown')
            page.keyboard.press('Enter')
            page.wait_for_timeout(SETTLE_MS)
            picked = [m for m, _ in pairs(sess, before)]
            if tid(page, 'name-input').input_value().replace(chr(92) + '*', '*') != first or picked != ['backup_search_files']:
                self.bad('V9 L7 ArrowDown+Enter: the field is %r and the calls %s, expected the name %r and exactly one backup_search_files' % (tid(page, 'name-input').input_value(), picked, first))
            tid(page, 'name-input').fill('акт')
            page.clock.fast_forward(300)
            page.wait_for_timeout(SETTLE_MS)
            before = len(sess.calls)
            page.keyboard.press('Escape')
            page.wait_for_timeout(SETTLE_MS)
            if tid(page, 'name-suggest').count() or len(sess.calls) != before:
                self.bad('V9 L7 Escape: the listbox stays or a call was sent')
            if tid(page, 'logout').count() == 1:
                tid(page, 'logout').click()
                page.wait_for_timeout(SETTLE_MS)
                after = len(sess.calls)
                page.clock.fast_forward(120000)
                page.wait_for_timeout(SETTLE_MS)
                if len(sess.calls) != after:
                    self.bad('V7 L7 logout: %s sent after the logout, expected zero calls of any method incl. suggest' % pairs(sess, after))
        finally:
            sess.close()

    def service_tabs(self) -> None:
        '''L8: #/service sends only the snapshots command, a tab sends only its section commands and the discovery poll stops when the tab is left.

        Returns:
            None.
        '''
        sess = Session(self.drv, clock=True)
        try:
            sess.go('#/service')
            page = sess.page
            if tid(page, 'page-service').count() != 1 or pairs(sess) != [('backup_snapshots', {'limit': 100})]:
                self.bad('V10 L8 #/service: page-service %d and the calls %s, expected one page-service and exactly [backup_snapshots {limit: 100}]' % (tid(page, 'page-service').count(), pairs(sess)))
            if not self.have('V10 L8', page, ('svc-tab-discovery', 'svc-tab-info')):
                return
            start = len(sess.calls)
            tid(page, 'svc-tab-discovery').click()
            page.wait_for_timeout(SETTLE_MS)
            page.clock.fast_forward(30000)
            page.wait_for_timeout(SETTLE_MS)
            methods = sorted({m for m, _ in pairs(sess, start)})
            polls = [m for m, _ in pairs(sess, start) if m == 'backup_discovery_status']
            if methods != ['backup_discovery_status'] or len(polls) != 2:
                self.bad('V10 L8 discovery tab: calls %s with %d status calls, expected only backup_discovery_status, one load and one poll in 30 s' % (methods, len(polls)))
            tid(page, 'svc-tab-info').click()
            page.wait_for_timeout(SETTLE_MS)
            left = len(sess.calls)
            page.clock.fast_forward(60000)
            page.wait_for_timeout(SETTLE_MS)
            if [m for m, _ in pairs(sess, left) if m == 'backup_discovery_status']:
                self.bad('V7 L8: backup_discovery_status is still polled after the discovery tab was left')
        finally:
            sess.close()

    def old_routes(self) -> None:
        '''L9: every removed 10.18 route is page-notfound with the 404 banner and sends no command.

        Returns:
            None.
        '''
        for route in OLD_ROUTES:
            sess = Session(self.drv)
            try:
                sess.go(route)
                if tid(sess.page, 'page-notfound').count() != 1 or sess.calls:
                    self.bad('V10 L9 %s: page-notfound %d and the calls %s, expected one page-notfound and no command' % (route, tid(sess.page, 'page-notfound').count(), pairs(sess)))
            finally:
                sess.close()


def _case(root: str, name: str) -> Callable[[Report, Any], None]:
    '''Return a browser case that runs one Cases method.

    Args:
        root: the SPA endpoint URL.
        name: the Cases method.

    Returns:
        The case function for vuechecks.with_driver.
    '''
    return lambda report, drv: getattr(Cases(report, drv, root), name)()


def _driven(report: Report, *names: str) -> None:
    '''Run Cases methods in the headless browser against the deployed SPA.

    Args:
        report: the findings collector.
        names: the Cases methods.

    Returns:
        None.
    '''
    root = vuechecks.deployed(report, 'rev11 SPA endpoint')
    if root is not None:
        vuechecks.with_driver(report, 'rev11 browser', root, *[_case(root, name) for name in names])


def _manifest(report: Report) -> None:
    '''V3: the served command manifest lists the three new commands with their parameters.

    Args:
        report: the findings collector.

    Returns:
        None.
    '''
    root = vuechecks.deployed(report, 'V3 rev11 SPA endpoint')
    got = lan_try(report, 'V3 GET /command-manifest.json', root, 'GET', '/command-manifest.json') if root else None
    if got is None:
        return
    try:
        text = json.dumps(json.loads(got[2]).get('used'))
    except (ValueError, AttributeError):
        text = ''
    for command, params in (('backup_filter_options', ('site_ids',)), ('backup_search_files', ('name_part', 'dates', 'limit')), ('backup_suggest_names', ('text',))):
        if command not in text or any('"%s"' % item not in text for item in params):
            report.product.append('V3 /command-manifest.json: the used set lacks %s with its parameters %s' % (command, list(params)))


def vue_static_serve() -> None:
    '''V1 on revision 11: the unchanged static cases and the nav of the single filter page.

    Returns:
        None.
    '''
    compose('vue_static_serve', vuechecks.vue_static_serve, lambda report: _driven(report, 'nav_ids'))


def vue_auth() -> None:
    '''V2 on revision 11: the unchanged key and logout cases and the nav ids.

    Returns:
        None.
    '''
    compose('vue_auth', vuechecks.vue_auth, lambda report: _driven(report, 'nav_ids'))


def vue_command_contract() -> None:
    '''V3 on revision 11: the live help lists the 14 commands and the manifest lists the three new ones.

    Returns:
        None.
    '''
    with mock.patch.object(b4base, 'COMMANDS', tuple(b4base.COMMANDS) + NEW_COMMANDS):
        compose('vue_command_contract', vuechecks.vue_command_contract, _manifest)


def _calls(report: Report) -> None:
    '''V4 on revision 11: the action table, the page cells and the cases L1 to L5, L8 and L9 replace the routes of 10.18.

    Args:
        report: the findings collector.

    Returns:
        None.
    '''
    vuechecks.removed_ui(report, ('U5', 'U6', 'U7', 'U8', 'U10'))
    vuechecks._actions_cases(report)
    root = vuechecks.deployed(report, 'V4 SPA endpoint')
    if root is not None:
        spa_files(report, 'V4 SPA sources')
        vuechecks.with_driver(report, 'V4 browser', root, vuebrowser.table_cases, vuebrowser.page_equals_result,
                              *[_case(root, name) for name in ('nav_ids', 'load_calls', 'site_tick', 'apply_one', 'wildcard_rows', 'columns', 'service_tabs', 'old_routes')])


def vue_command_calls() -> None:
    '''V4 on revision 11, replacing the route and nav cases of 10.18.

    Returns:
        None.
    '''
    compose('vue_command_calls', None, _calls)


def _download(report: Report) -> None:
    '''V5 on revision 11: the unknown link, the staged export and the row download of the main page.

    Args:
        report: the findings collector.

    Returns:
        None.
    '''
    vuechecks.removed_ui(report, ('U9',))
    root = vuechecks.deployed(report, 'V5 SPA endpoint')
    if root is None:
        return
    got = lan_try(report, 'V5 GET an unknown link', root, 'GET', '/downloads/%s/x.bin' % b4base.ZERO_ID)
    if got is not None and got[0] != 404:
        report.product.append('V5 GET an unknown link answered %d, expected 404' % got[0])
    if live.service_state() == 'S1':
        vuechecks._s1_download(report, root)
        vuechecks.with_driver(report, 'V5 browser', root, _case(root, 'download_row'))
    else:
        report.state.append('V5 the staged export and the row download need an S1 service')


def vue_download() -> None:
    '''V5 on revision 11: the row download of the main page replaces the files page flow.

    Returns:
        None.
    '''
    compose('vue_download', None, _download)


def _polling(report: Report) -> None:
    '''V7 on revision 11: the discovery poll lives in the service tab, logout and suggest send nothing, the final export card never polls.

    Args:
        report: the findings collector.

    Returns:
        None.
    '''
    root = vuechecks.deployed(report, 'V7 SPA endpoint')
    if root is not None:
        vuechecks.with_driver(report, 'V7 browser', root, _case(root, 'service_tabs'), _case(root, 'autocomplete'), vueroutes.export_poll_case)


def vue_polling() -> None:
    '''V7 on revision 11, replacing the polling and logout cases of 10.18.

    Returns:
        None.
    '''
    compose('vue_polling', None, _polling)


def _groups(report: Report) -> None:
    '''V6 on revision 11: the Vitest groups filters, autocomplete, datelabel and service-sections exist in the tracked tests.

    Args:
        report: the findings collector.

    Returns:
        None.
    '''
    found: set[str] = set()
    for item in tracked_files() or []:
        if item.startswith('frontend/') and '.test.' in item:
            try:
                found |= set(vuebuild.DESCRIBE.findall(open(vuechecks.ROOT / item, encoding='utf-8').read()))
            except OSError:
                continue
    missing = [name for name in GROUPS11 if name not in found]
    if missing:
        report.product.append('V6 the Vitest describe groups %s do not exist in the tracked frontend tests (found %s)' % (missing, sorted(found)))
    report.info.append('V6 sha256 of the group list: %s' % hashlib.sha256(','.join(sorted(found)).encode()).hexdigest()[:12])


def vue_build() -> None:
    '''V6 on revision 11: the unchanged build cases and the new Vitest groups.

    Returns:
        None.
    '''
    compose('vue_build', vuechecks.vue_build, _groups)


def settle(page: Any, prefix: str) -> None:
    '''Wait for a location hash prefix.

    Args:
        page: the page.
        prefix: the hash prefix.

    Returns:
        None.
    '''
    wait_hash(page, prefix)
