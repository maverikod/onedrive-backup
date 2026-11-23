'''Revision 13 browser cases of the main page '#/' (matrix TODO 10.21.6 and 10.21.8 L16-L27, row V12, block UI-TREE).

One method per case id of row V12 (l16_three_regions .. l27_logout_zero_calls and the four stub cases) plus the revision 13 load and
apply cases of row V4 (10.21.6 CALLS OF THE MAIN PAGE, replacing L1 and L3 of 10.19.4). Every case opens its own page and starts with
the presence of main-grid and folder-tree, so on a page without the tree each case is RED on its own under its case id. Counts and
orders are taken from the project client (pipeline.vue13base.Ref), sorted by the server and compared as returned. READ-ONLY: no
export is created, no schedule or index is written.
'''

from __future__ import annotations

import re
from typing import Any

from pipeline import rev11, rev13, vue11
from pipeline.report import Report
from pipeline.vue13base import LOAD13, M12, M13, M19, STALE, Ref, Session13, hash_query, same, shown, url, wanted
from pipeline.vuebrowser import call_problems
from pipeline.vueroutes import tid

DAY = rev13.TREE_DATE
DUP_DAY = '2026-11-22'
LIMIT = 100


class Cases13(vue11.Cases):
    '''The revision 13 browser cases of one run.

    Attributes:
        ref: the reference side (project client).
    '''

    def __init__(self, report: Report, drv: Any, root: str, ref: Ref) -> None:
        '''Keep the run parts.

        Args:
            report: the findings collector.
            drv: the headless driver.
            root: the SPA endpoint URL.
            ref: the reference side.
        '''
        super().__init__(report, drv, root)
        self.ref = ref

    def start(self, label: str, sess: Session13, route: str, names: tuple[str, ...] = ('main-grid', 'folder-tree')) -> bool:
        '''Open the route; a page that does not mount is a harness finding, a page without the tree regions a PRODUCT finding.

        Args:
            label: the case label.
            sess: the session.
            route: the hash route.
            names: the test ids the case needs first.

        Returns:
            True when the case can go on.
        '''
        sess.load(route)
        if tid(sess.page, 'page-main').count() != 1:
            self.report.env.append('%s: the main page did not mount at %r (no page-main): harness or service availability, not the tree contract' % (label, route or '#/'))
            return False
        return self.have(label, sess.page, names)

    def scope(self, folder_part: str = 'неактивн') -> tuple[str, str, str]:
        '''Return (site id, ДЕНЬГИ drive id, the top folder of the reference listing whose key contains folder_part).

        Args:
            folder_part: the key fragment.

        Returns:
            The scope address.
        '''
        tree = self.ref.tree
        return tree.site or 'site-none', tree.drive(rev13.DENGI), tree.folder(folder_part)

    def expand(self, label: str, sess: Session13, drive: str) -> bool:
        '''Click the toggle of one library node and wait for its folders.

        Args:
            label: the case label.
            sess: the session.
            drive: the drive id.

        Returns:
            True when the folders are shown.
        '''
        node = sess.node('library', drive=drive)
        if not sess.until(lambda: node.count() == 1 and node.first.is_visible()):
            self.bad('%s: no tree-node of the library %s is shown under the expanded site' % (label, drive[:16]))
            return False
        toggle = node.first.locator('[data-testid=tree-toggle]')
        if toggle.count() == 0:
            self.bad('%s: the library node %s has no tree-toggle' % (label, drive[:16]))
            return False
        start = len(sess.calls)
        toggle.first.click()
        sess.settle(start, lambda: sess.answered(start, M19) > 0)
        return bool(sess.until(lambda: len(sess.children(drive, '')) > 0, bound=5000))

    def check_rows(self, label: str, sess: Session13, params: dict) -> dict | None:
        '''Compare the result rows with the client result of the same search parameters.

        Args:
            label: the case label.
            sess: the session.
            params: the search parameters the page sent.

        Returns:
            The client data, or None.
        '''
        data = self.ref.ask(label, M13, params)
        if data is None:
            return None
        names = [item.get('name') for item in data.get('items', [])]
        if sess.row_names() != names:
            self.bad('%s: the rows show %s, expected the client names %s (total %s)' % (label, sess.row_names()[:5], names[:5], data.get('total')))
        return data

    def l16_three_regions(self) -> None:
        '''L16: three regions in one row at 1600x900 with own scroll, the page within the window, root counts and the load calls.

        Returns:
            None.
        '''
        label = 'V12 l16_three_regions'
        sess = Session13(self.drv)
        try:
            if not self.start(label, sess, '', ('main-grid', 'folder-tree', 'result-area', 'detail-panel', 'result-scroll')):
                return
            page = sess.page
            self.have(label, page, LOAD13)
            boxes = [sess.box(name) for name in ('folder-tree', 'result-area', 'detail-panel')]
            tree, area, panel = boxes
            if tree is None or area is None or panel is None:
                self.bad('%s: no bounding box for folder-tree, result-area or detail-panel: %s' % (label, boxes))
            elif not (tree['x'] + tree['width'] <= area['x'] + 0.5 and area['x'] + area['width'] <= panel['x'] + 0.5
                      and max(tree['y'], area['y'], panel['y']) - min(tree['y'], area['y'], panel['y']) <= 4):
                self.bad('%s: the regions are not one row tree | list | detail at 1600x900: %s' % (label, boxes))
            for name in ('folder-tree', 'result-scroll', 'detail-panel'):
                over = page.evaluate('n => getComputedStyle(document.querySelector(`[data-testid="${n}"]`)).overflowY', name)
                if over != 'auto':
                    self.bad('%s: %s has overflow-y %s, expected auto (own scroll per region)' % (label, name, over))
            height, window = page.evaluate('[document.documentElement.scrollHeight, window.innerHeight]')
            rows = tid(page, 'result-row').count()
            if height - window > 16:
                self.bad('%s: the document scroll height %d exceeds the window %d by more than 16 px with %d rows' % (label, height, window, rows))
            if rows != LIMIT:
                self.report.state.append('%s: the first page holds %d rows, the scroll bound is asserted with a 100-row page' % (label, rows))
            tree_el = tid(page, 'folder-tree').first
            if (tree_el.get_attribute('role'), tree_el.get_attribute('aria-label')) != ('tree', 'Каталоги'):
                self.bad('%s: folder-tree has role %r aria-label %r, expected tree and Каталоги' % (label, tree_el.get_attribute('role'), tree_el.get_attribute('aria-label')))
            if tid(page, 'tree-all').first.get_attribute('aria-selected') != 'true':
                self.bad('%s: tree-all is not aria-selected with no scope' % label)
            newest = self.ref.tree.days[-1] if self.ref.tree.days else ''
            roots = self.ref.ask(label, M19, {'dates': [newest]})
            flat = self.ref.ask(label, M13, {'dates': [newest], 'limit': 1})
            if roots is None or flat is None:
                return
            sites = [node for node in sess.nodes() if node['kind'] == 'site']
            if [shown(node) for node in sites] != [wanted(node) for node in roots.get('nodes', [])]:
                self.bad('%s: the site nodes are %s, expected the client M19 roots %s' % (label, [shown(n) for n in sites], [wanted(n) for n in roots.get('nodes', [])]))
            if sum(int(node['raw'] or 0) for node in sites) != flat.get('total'):
                self.bad('%s: the site node counts %s do not sum to the client M13 total %s (RT4)' % (label, [n['raw'] for n in sites], flat.get('total')))
            for node in sites:
                if re.sub(r'\s', '', node['count']) != node['raw'] or node['count_raw'] != node['raw'] or (int(node['raw'] or 0) >= 1000 and not re.search(r'\s', node['count'])):
                    self.bad('%s: tree-count %r (data-raw %r) of the site, expected %s with a space as thousands separator' % (label, node['count'], node['count_raw'], node['raw']))
            sent = sess.since(0)
            want = [(M13, {'dates': [newest], 'limit': LIMIT}), (M19, {'dates': [newest]})]
            want += [(M19, {'site_id': n.get('site_id'), 'dates': [newest]}) for n in roots.get('nodes', [])] if len(roots.get('nodes', [])) == 1 else []
            rest = [(m, {k: v for k, v in p.items() if not (m == M13 and k == 'offset' and v == 0)}) for m, p in sent[1:] if isinstance(p, dict)]
            if not sent or sent[0] != (M12, {}) or not same(rest, want):
                self.bad('%s: the load sent %s, expected backup_filter_options {} first, then exactly %s' % (label, sent, want))
        finally:
            sess.close()

    def l17_toggle_site(self) -> None:
        '''L17: the libraries of the single site equal the client M19 {site_id}; its expansion is one M19; collapse and re-expansion call nothing.

        Returns:
            None.
        '''
        label = 'V12 l17_toggle_site'
        sess = Session13(self.drv)
        try:
            if not self.start(label, sess, ''):
                return
            tree = self.ref.tree
            newest = tree.days[-1] if tree.days else ''
            libs = self.ref.ask(label, M19, {'site_id': tree.site, 'dates': [newest]})
            if libs is None:
                return
            want = [wanted(node) for node in libs.get('nodes', [])]
            sess.until(lambda: len(sess.children('', None)) == len(want))
            if [shown(node) for node in sess.children('', None)] != want:
                self.bad('%s: the library nodes are %s, expected the client M19 {site_id} %s' % (label, [shown(n) for n in sess.children('', None)], want))
            expansions = [p for m, p in sess.since(0, M19) if isinstance(p, dict) and 'site_id' in p]
            if expansions != [{'site_id': tree.site, 'dates': [newest]}]:
                self.bad('%s: the site expansion sent %s, expected exactly one backup_folder_children {site_id, dates}' % (label, expansions))
            site = sess.node('site', site=tree.site or '')
            toggle = site.first.locator('[data-testid=tree-toggle]') if site.count() else site
            if site.count() != 1 or toggle.count() == 0:
                self.bad('%s: %d site node with %d tree-toggle, expected one of each' % (label, site.count(), toggle.count()))
                return
            start = len(sess.calls)
            toggle.first.click()
            sess.until(lambda: site.first.get_attribute('aria-expanded') == 'false', bound=5000)
            toggle.first.click()
            sess.until(lambda: site.first.get_attribute('aria-expanded') == 'true', bound=5000)
            sess.settle(start)
            if sess.since(start) or [shown(node) for node in sess.children('', None)] != want:
                self.bad('%s: collapse and re-expansion of the site sent %s and show %d libraries, expected no call (cached children) and the same %d' % (label, sess.since(start), len(sess.children('', None)), len(want)))
        finally:
            sess.close()

    def l18_expand_library(self) -> None:
        '''L18: the toggle of ДЕНЬГИ with the date 2026-11-21 sends one M19 and shows the six folders of F4 with their counts.

        Returns:
            None.
        '''
        label = 'V12 l18_expand_library'
        sess = Session13(self.drv)
        try:
            if not self.start(label, sess, url([DAY])):
                return
            site, drive, _ = self.scope()
            tree = self.ref.tree
            if not tree.listing_id:
                self.report.state.append('%s: no complete listing of %s on %s (F4)' % (label, rev13.DENGI, DAY))
                return
            start = len(sess.calls)
            if not self.expand(label, sess, drive):
                self.bad('%s: the expansion of %s shows no folder node' % (label, rev13.DENGI))
            if sess.since(start) != [(M19, {'site_id': site, 'drive_id': drive, 'dates': [DAY]})]:
                self.bad('%s: the toggle sent %s, expected exactly one backup_folder_children {site_id, drive_id, dates: [%s]}' % (label, sess.since(start), DAY))
            want = []
            for name in tree.folders:
                count = sum(1 for folder, _ in tree.files if folder == name or folder.startswith(name + '/'))
                want.append(('folder', site, drive, name, name, str(count), any(folder.startswith(name + '/') for folder, _ in tree.files)))
            got = [shown(node) for node in sess.children(drive, '')]
            if got != want:
                self.bad('%s: the folder nodes are %s, expected the %d folders of the listing in key order %s' % (label, got, len(want), want))
            ref = self.ref.ask(label, M19, {'site_id': site, 'drive_id': drive, 'dates': [DAY]})
            if ref is not None and [wanted(node) for node in ref.get('nodes', [])] != want:
                self.bad('%s: the client M19 answers %s, the listing gives %s' % (label, [wanted(n) for n in ref.get('nodes', [])], want))
        finally:
            sess.close()

    def l19_select_folder(self) -> None:
        '''L19: a click on 'ДЕНЬГИ Неактивные' sends one M13 with the scope keys, shows its 40 rows and the breadcrumb.

        Returns:
            None.
        '''
        label = 'V12 l19_select_folder'
        sess = Session13(self.drv)
        try:
            if not self.start(label, sess, url([DAY])):
                return
            site, drive, folder = self.scope()
            if not self.expand(label, sess, drive):
                return
            node = sess.node('folder', drive=drive, folder=folder)
            if node.count() != 1:
                self.bad('%s: %d tree-node for the folder %s, expected one' % (label, node.count(), folder))
                return
            start = len(sess.calls)
            node.first.locator('[data-testid=tree-label]').first.click()
            sess.settle(start, lambda: sess.answered(start, M13) > 0)
            params = {'site_id': site, 'drive_id': drive, 'dir': folder, 'dates': [DAY], 'limit': LIMIT}
            if sess.since(start) != [(M13, params)]:
                self.bad('%s: the click sent %s, expected exactly one backup_search_files %s (no offset, no tree call)' % (label, sess.since(start), params))
            self.selected_folder(label, sess, params, folder)
        finally:
            sess.close()

    def selected_folder(self, label: str, sess: Session13, params: dict, folder: str) -> None:
        '''Assert the page state of a selected top folder of ДЕНЬГИ: hash, node, rows, columns and breadcrumb.

        Args:
            label: the case label.
            sess: the session.
            params: the expected search parameters.
            folder: the folder.

        Returns:
            None.
        '''
        page, tree = sess.page, self.ref.tree
        query = hash_query(page)
        if (query.get('fs'), query.get('fd'), query.get('fp')) != ([params['site_id']], [params['drive_id']], [folder]) or 'offset' in query or 'rec' in query:
            self.bad('%s: the hash query is %s, expected fs, fd, fp of the scope and no offset or rec' % (label, query))
        node = sess.node('folder', drive=params['drive_id'], folder=folder)
        if node.count() != 1 or node.first.get_attribute('aria-selected') != 'true':
            self.bad('%s: the folder node %s is not the one aria-selected node' % (label, folder))
        data = self.check_rows(label, sess, params)
        listed = sum(1 for d, _ in tree.files if d == folder)
        if data is not None and (data.get('total') != listed or tid(page, 'result-row').count() != min(listed, LIMIT)):
            self.bad('%s: client total %s and %d rows shown, expected %d files of the listing' % (label, data.get('total'), tid(page, 'result-row').count(), listed))
        if page.locator('[data-testid=result-table] th').count() != 3:
            self.bad('%s: %d header cells, expected exactly three' % (label, page.locator('[data-testid=result-table] th').count()))
        texts = page.eval_on_selector_all('[data-testid=result-row]', 'rows => rows.map(r => r.innerText)')
        leaked = [text[:60] for text in texts if '.dup-' in text or 'sharepoint/' in text or rev11.KEY_SEGMENT.search(text)]
        if leaked:
            self.bad('%s: result rows show an identifier fragment: %s' % (label, leaked[:3]))
        crumbs = sess.texts('crumb')
        want = [tree.site_name, tree.libraries.get(params['drive_id'], ''), folder]
        last = tid(page, 'crumb').last.get_attribute('aria-current') if crumbs else None
        if sess.texts('crumb-all') != ['Все файлы'] or crumbs != want or last in (None, 'false'):
            self.bad('%s: the breadcrumb is %s + %s (last aria-current %r), expected Все файлы + %s with the last crumb current' % (label, sess.texts('crumb-all'), crumbs, last, ' / '.join(want)))

    def l20_reload_restores(self) -> None:
        '''L20: the URL of the selected folder reproduces the page; the chain calls {site_id} and {site_id, drive_id}.

        Returns:
            None.
        '''
        label = 'V12 l20_reload_restores'
        sess = Session13(self.drv)
        try:
            site, drive, folder = self.scope()
            if not self.start(label, sess, url([DAY], site, drive, folder)):
                return
            sess.until(lambda: sess.node('folder', drive=drive, folder=folder).count() == 1)
            sess.settle(0)
            params = {'site_id': site, 'drive_id': drive, 'dir': folder, 'dates': [DAY], 'limit': LIMIT}
            want = [(M13, params), (M19, {'dates': [DAY]}), (M19, {'site_id': site, 'dates': [DAY]}), (M19, {'site_id': site, 'drive_id': drive, 'dates': [DAY]})]
            sent = sess.since(0)
            if len(sess.since(0, M12)) != 1 or not same(sess.since(0, M13, M19), want):
                self.bad('%s: the reload sent %s, expected one backup_filter_options and exactly %s' % (label, sent, want))
            self.selected_folder(label, sess, params, folder)
        finally:
            sess.close()

    def l21_and_name_filter(self) -> None:
        '''L21: a name part applied with a folder selected: the tree is pruned like the client M19, the rows equal the client M13 with scope.

        Returns:
            None.
        '''
        label = 'V12 l21_and_name_filter'
        sess = Session13(self.drv)
        try:
            site, drive, folder = self.scope('рхив')
            if not self.start(label, sess, url([DAY], site, drive, folder)):
                return
            sess.until(lambda: sess.node('folder', drive=drive, folder=folder).count() == 1)
            sess.settle(0)
            pattern = '*.xls*'
            tid(sess.page, 'name-input').fill(pattern)
            start = len(sess.calls)
            tid(sess.page, 'filter-apply').click()
            sess.settle(start, lambda: sess.answered(start, M13) > 0 and sess.answered(start, M19) >= 3)
            base = {'dates': [DAY], 'name_part': pattern}
            params = dict(base, site_id=site, drive_id=drive, dir=folder, limit=LIMIT)
            want = [(M13, params), (M19, base), (M19, dict(base, site_id=site)), (M19, dict(base, site_id=site, drive_id=drive))]
            if not same(sess.since(start, M13, M19), want):
                self.bad('%s: the apply sent %s, expected exactly %s' % (label, sess.since(start, M13, M19), want))
            for title, address, parent, kind in (('roots', {}, None, 'site'), ('libraries', {'site_id': site}, None, 'library'), ('folders', {'site_id': site, 'drive_id': drive}, '', 'folder')):
                ref = self.ref.ask(label, M19, dict(base, **address))
                if ref is None:
                    continue
                got = [shown(n) for n in sess.nodes() if n['shown'] and n['kind'] == kind and (kind != 'folder' or (n['drive'] == drive and '/' not in n['dir']))]
                if got != [wanted(n) for n in ref.get('nodes', [])]:
                    self.bad('%s: the %s of the pruned tree are %s, expected the client M19 %s' % (label, title, got, [wanted(n) for n in ref.get('nodes', [])]))
            data = self.check_rows(label, sess, params)
            match = rev11.matcher(pattern)
            listed = sum(1 for d, name in self.ref.tree.files if d == folder and match(name))
            if data is not None and (data.get('total') != listed or any(not match(str(n)) for n in sess.row_names())):
                self.bad('%s: client total %s, rows %s, expected %d names of the folder matching %s' % (label, data.get('total'), sess.row_names()[:5], listed, pattern))
        finally:
            sess.close()

    def l22_recursive_library(self) -> None:
        '''L22: the library ДЕНЬГИ selected: 0 root files; folder-recursive sends one M13 with recursive true and shows the 347 rows total.

        Returns:
            None.
        '''
        label = 'V12 l22_recursive_library'
        sess = Session13(self.drv)
        try:
            site, drive, _ = self.scope()
            if not self.start(label, sess, url([DAY], site, drive)):
                return
            sess.settle(0)
            params = {'site_id': site, 'drive_id': drive, 'dates': [DAY], 'limit': LIMIT}
            files = self.ref.tree.files
            root = self.check_rows(label, sess, params)
            if root is not None and (root.get('total') != sum(1 for d, _ in files if d == '') or tid(sess.page, 'result-empty').count() != (0 if root.get('total') else 1)):
                self.bad('%s: the library root shows %d rows and %d result-empty, client total %s' % (label, tid(sess.page, 'result-row').count(), tid(sess.page, 'result-empty').count(), root.get('total')))
            box = tid(sess.page, 'folder-recursive')
            if box.count() != 1 or not box.first.is_enabled():
                self.bad('%s: %d folder-recursive, expected one enabled checkbox with a library scope' % (label, box.count()))
                return
            start = len(sess.calls)
            box.first.click()
            sess.settle(start, lambda: sess.answered(start, M13) > 0)
            deep = dict(params, recursive=True)
            if sess.since(start) != [(M13, deep)] or hash_query(sess.page).get('rec') != ['1']:
                self.bad('%s: the checkbox sent %s with hash rec %s, expected exactly one backup_search_files %s and rec=1' % (label, sess.since(start), hash_query(sess.page).get('rec'), deep))
            data = self.check_rows(label, sess, deep)
            count = tid(sess.page, 'result-count').first.get_attribute('data-raw') if tid(sess.page, 'result-count').count() else None
            if data is not None and (data.get('total') != len(files) or count != str(len(files))):
                self.bad('%s: recursive total client %s, result-count %r, expected the %d files of the library' % (label, data.get('total'), count, len(files)))
        finally:
            sess.close()

    def l23_keyboard(self) -> None:
        '''L23: ArrowDown, ArrowRight, ArrowLeft, ArrowUp, Home and End move as 10.21.6; Enter selects with exactly one search.

        Returns:
            None.
        '''
        label = 'V12 l23_keyboard'
        sess = Session13(self.drv)
        try:
            if not self.start(label, sess, url([DAY])):
                return
            site, drive, _ = self.scope()
            sess.until(lambda: len(sess.children('', None)) > 0)
            libs = sess.children('', None)
            node = sess.node('site', site=site)
            if node.count() != 1 or not libs:
                self.bad('%s: %d site node and %d library nodes shown, expected the expanded single site' % (label, node.count(), len(libs)))
                return
            first = ('tree-node', 'library', libs[0]['drive'], '')
            node.first.focus()
            steps: list[tuple[str, Any]] = []
            press = sess.page.keyboard.press
            press('ArrowDown')
            steps.append(('ArrowDown from the site', sess.focused() == first))
            start = len(sess.calls)
            press('ArrowRight')
            sess.settle(start, lambda: sess.answered(start, M19) > 0)
            lib = sess.node('library', drive=libs[0]['drive'])
            steps.append(('ArrowRight expands the collapsed library', lib.first.get_attribute('aria-expanded') == 'true' and sess.focused() == first
                          and sess.since(start) == [(M19, {'site_id': site, 'drive_id': libs[0]['drive'], 'dates': [DAY]})]))
            child = sess.children(libs[0]['drive'], '')
            press('ArrowRight')
            steps.append(('ArrowRight moves to the first child', bool(child) and sess.focused() == ('tree-node', 'folder', libs[0]['drive'], child[0]['dir'] if child else '')))
            press('ArrowLeft')
            steps.append(('ArrowLeft on a leaf moves to its parent', sess.focused() == first))
            start = len(sess.calls)
            press('ArrowLeft')
            sess.settle(start)
            steps.append(('ArrowLeft collapses the expanded library without a call', lib.first.get_attribute('aria-expanded') == 'false' and not sess.since(start)))
            press('ArrowUp')
            steps.append(('ArrowUp moves to the site', sess.focused() == ('tree-node', 'site', '', '')))
            press('End')
            items = sess.items()
            steps.append(('End moves to the last visible node', bool(items) and sess.focused() == items[-1]))
            press('Home')
            steps.append(('Home moves to the first visible node', bool(items) and sess.focused() == items[0]))
            lib.first.focus()
            start = len(sess.calls)
            press('Enter')
            sess.settle(start, lambda: sess.answered(start, M13) > 0)
            steps.append(('Enter selects with exactly one search and keeps the focus', sess.since(start) == [(M13, {'site_id': site, 'drive_id': libs[0]['drive'], 'dates': [DAY], 'limit': LIMIT})]
                          and sess.focused() == first))
            failed = [name for name, ok in steps if not ok]
            if failed:
                self.bad('%s: the keyboard steps %s do not hold (focus now %s, calls %s)' % (label, failed, sess.focused(), sess.since(start)))
        finally:
            sess.close()

    def l24_tree_all_clears(self) -> None:
        '''L24: tree-all clears the scope with one M13 without scope keys, equal to the flat client result.

        Returns:
            None.
        '''
        label = 'V12 l24_tree_all_clears'
        sess = Session13(self.drv)
        try:
            site, drive, folder = self.scope()
            if not self.start(label, sess, url([DAY], site, drive, folder), ('main-grid', 'folder-tree', 'tree-all')):
                return
            sess.settle(0)
            start = len(sess.calls)
            tid(sess.page, 'tree-all').first.click()
            sess.settle(start, lambda: sess.answered(start, M13) > 0)
            params = {'dates': [DAY], 'limit': LIMIT}
            if sess.since(start) != [(M13, params)]:
                self.bad('%s: tree-all sent %s, expected exactly one backup_search_files %s (no scope keys, no tree call)' % (label, sess.since(start), params))
            self.check_rows(label, sess, params)
            query = hash_query(sess.page)
            if set(query) & {'fs', 'fd', 'fp', 'rec'} or tid(sess.page, 'tree-all').first.get_attribute('aria-selected') != 'true' or tid(sess.page, 'crumb').count():
                self.bad('%s: hash %s, tree-all aria-selected %r, %d crumbs, expected no scope key, tree-all selected and no crumb' % (label, query, tid(sess.page, 'tree-all').first.get_attribute('aria-selected'), tid(sess.page, 'crumb').count()))
        finally:
            sess.close()

    def l25_tree_more(self) -> None:
        '''L25: the widest folder shows 200 children and tree-more; a click appends the next 200 with one M19 at offset 200.

        Returns:
            None.
        '''
        label = 'V12 l25_tree_more'
        sess = Session13(self.drv)
        try:
            tree = self.ref.tree
            newest, site, docs, wide = (tree.days[-1] if tree.days else ''), tree.site or 'site-none', tree.drive(rev13.DOCS), rev13.DIR_WIDE
            if not self.start(label, sess, url([newest], site, docs, wide)):
                return
            address = {'site_id': site, 'drive_id': docs, 'dir': wide, 'dates': [newest]}
            ref = self.ref.nodes(label, address, 400)
            if ref is None:
                return
            if ref[1] <= 200:
                self.report.state.append('%s: the folder %s has %d subfolders, the case needs more than 200' % (label, wide, ref[1]))
                return
            node = sess.node('folder', drive=docs, folder=wide)
            if not sess.until(lambda: node.count() == 1):
                self.bad('%s: the folder %s is not shown after the ancestor chain of the URL scope' % (label, wide))
                return
            sess.settle(0)
            start = len(sess.calls)
            node.first.locator('[data-testid=tree-toggle]').first.click()
            sess.settle(start, lambda: sess.answered(start, M19) > 0)
            sess.until(lambda: len(sess.children(docs, wide)) >= 200, bound=10000)
            more = node.first.locator('[data-testid=tree-more]')
            if sess.since(start) != [(M19, address)] or len(sess.children(docs, wide)) != 200 or more.count() != 1 or not more.first.inner_text().strip().startswith('Ещё'):
                self.bad('%s: the toggle sent %s and shows %d children and %d tree-more, expected one M19 %s, 200 children and one Ещё button'
                         % (label, sess.since(start), len(sess.children(docs, wide)), more.count(), address))
                return
            start = len(sess.calls)
            more.first.click()
            sess.settle(start, lambda: sess.answered(start, M19) > 0)
            sess.until(lambda: len(sess.children(docs, wide)) >= min(400, ref[1]), bound=10000)
            if sess.since(start) != [(M19, dict(address, offset=200))]:
                self.bad('%s: tree-more sent %s, expected exactly one backup_folder_children %s' % (label, sess.since(start), dict(address, offset=200)))
            got = [node_['dir'] for node_ in sess.children(docs, wide)]
            if got != [str(n.get('dir')) for n in ref[0][:400]]:
                self.bad('%s: the %d children after tree-more differ from the client pages (first difference at %s)' % (label, len(got), next((i for i, (a, b) in enumerate(zip(got, ref[0])) if a != b.get('dir')), min(len(got), len(ref[0])))))
        finally:
            sess.close()

    def l26_narrow_stack(self) -> None:
        '''L26: at 800x900 the regions stack: tree above list above detail, no overlap.

        Returns:
            None.
        '''
        label = 'V12 l26_narrow_stack'
        sess = Session13(self.drv, size=(800, 900))
        try:
            if not self.start(label, sess, '', ('main-grid', 'folder-tree', 'result-area', 'detail-panel')):
                return
            tree, area, panel = [sess.box(name) for name in ('folder-tree', 'result-area', 'detail-panel')]
            if tree is None or area is None or panel is None or not (tree['y'] + tree['height'] <= area['y'] + 0.5 and area['y'] + area['height'] <= panel['y'] + 0.5):
                self.bad('%s: the boxes at 800x900 are %s, expected folder-tree above result-area above detail-panel without overlap' % (label, [tree, area, panel]))
        finally:
            sess.close()

    def l27_logout_zero_calls(self) -> None:
        '''L27: after logout and 120 s of fake time the page sends zero calls of any method incl. backup_folder_children.

        Returns:
            None.
        '''
        label = 'V12 l27_logout_zero_calls'
        sess = Session13(self.drv, clock=True)
        try:
            if not self.start(label, sess, '', ('main-grid', 'folder-tree', 'logout')):
                return
            sess.settle(0)
            before = len(sess.calls)
            tid(sess.page, 'logout').first.click()
            sess.page.clock.fast_forward(120000)
            sess.settle(before)
            if sess.since(before):
                self.bad('%s: %s sent after the logout and 120 s, expected ZERO calls of any method incl. backup_folder_children (R28)' % (label, sess.since(before)))
        finally:
            sess.close()

    def stub_tree_error_banner(self) -> None:
        '''Stub: a tree command error shows the one error-banner and the node stays collapsed with no stale children.

        Returns:
            None.
        '''
        label = 'V12 stub_tree_error_banner'
        sess = Session13(self.drv)
        try:
            if not self.start(label, sess, url([DAY])):
                return
            _, drive, _ = self.scope()
            node = sess.node('library', drive=drive)
            if not sess.until(lambda: node.count() == 1) or node.first.locator('[data-testid=tree-toggle]').count() == 0:
                self.bad('%s: no library node %s with a tree-toggle' % (label, drive[:16]))
                return
            sess.stub = lambda method, params: 'error' if method == M19 and params.get('drive_id') else None
            start = len(sess.calls)
            node.first.locator('[data-testid=tree-toggle]').first.click()
            sess.settle(start, lambda: sess.answered(start, M19) > 0)
            if tid(sess.page, 'error-banner').count() != 1 or node.first.get_attribute('aria-expanded') == 'true' or sess.children(drive, ''):
                self.bad('%s: %d error-banner, aria-expanded %r, %d children after the stubbed error, expected one banner, a collapsed node and no child'
                         % (label, tid(sess.page, 'error-banner').count(), node.first.get_attribute('aria-expanded'), len(sess.children(drive, ''))))
        finally:
            sess.close()

    def stub_stale_tree_answer(self) -> None:
        '''Stub: a tree answer that arrives after an apply is discarded (only the latest request per node may render).

        Returns:
            None.
        '''
        label = 'V12 stub_stale_tree_answer'
        sess = Session13(self.drv)
        try:
            if not self.start(label, sess, url([DAY])):
                return
            site, drive, _ = self.scope()
            node = sess.node('library', drive=drive)
            if not sess.until(lambda: node.count() == 1) or node.first.locator('[data-testid=tree-toggle]').count() == 0:
                self.bad('%s: no library node %s with a tree-toggle' % (label, drive[:16]))
                return
            sess.stub = lambda method, params: 'hold' if method == M19 and params.get('drive_id') else None
            node.first.locator('[data-testid=tree-toggle]').first.click()
            if not sess.until(lambda: len(sess.parked) == 1, bound=10000):
                self.bad('%s: the toggle sent no backup_folder_children to hold' % label)
                return
            start = len(sess.calls)
            tid(sess.page, 'filter-apply').first.click()
            sess.settle(start, lambda: sess.answered(start, M13) > 0)
            stale = {'nodes': [{'kind': 'folder', 'site_id': site, 'drive_id': drive, 'dir': STALE, 'name': STALE, 'file_count': 1, 'direct_count': 1, 'has_children': False}],
                     'total': 1, 'offset': 0, 'limit': 200, 'path': [], 'timezone': rev11.TZ, 'index': {'complete': True, 'snapshots_total': 1, 'snapshots_indexed': 1}}
            sess.stub = None
            sess.answer_parked(stale)
            sess.settle(start)
            if STALE in tid(sess.page, 'folder-tree').first.inner_text() or sess.node('folder', folder=STALE).count():
                self.bad('%s: the tree answer of the request superseded by the apply was rendered (%s shown)' % (label, STALE))
        finally:
            sess.close()

    def stub_scope_kept_empty(self) -> None:
        '''O-T7 A: a filter that empties the selected folder keeps the scope (empty list, crumbs remain); crumb-all clears it.

        Returns:
            None.
        '''
        label = 'V12 stub_scope_kept_empty'
        sess = Session13(self.drv)
        try:
            site, drive, folder = self.scope()
            if not self.start(label, sess, url([DAY], site, drive, folder)):
                return
            sess.settle(0)
            tid(sess.page, 'name-input').fill('zzzzqqqq')
            start = len(sess.calls)
            tid(sess.page, 'filter-apply').click()
            sess.settle(start, lambda: sess.answered(start, M13) > 0)
            tree = self.ref.tree
            crumbs = sess.texts('crumb')
            if (tid(sess.page, 'result-empty').count() != 1 or tid(sess.page, 'result-row').count() or crumbs != [tree.site_name, tree.libraries.get(drive, ''), folder]
                    or hash_query(sess.page).get('fp') != [folder] or sess.node('folder', drive=drive, folder=folder).count() or tid(sess.page, 'tree-empty').count() != 1):
                self.bad('%s: after a name part matching nothing: %d result-empty, %d rows, crumbs %s, hash fp %s, folder node %d, tree-empty %d; expected the scope kept with an empty list, a pruned tree and tree-empty'
                         % (label, tid(sess.page, 'result-empty').count(), tid(sess.page, 'result-row').count(), crumbs, hash_query(sess.page).get('fp'),
                            sess.node('folder', drive=drive, folder=folder).count(), tid(sess.page, 'tree-empty').count()))
            start = len(sess.calls)
            if tid(sess.page, 'crumb-all').count() != 1:
                self.bad('%s: no crumb-all to clear the scope' % label)
                return
            tid(sess.page, 'crumb-all').first.click()
            sess.settle(start, lambda: sess.answered(start, M13) > 0)
            want = [(M13, {'dates': [DAY], 'name_part': 'zzzzqqqq', 'limit': LIMIT})]
            if sess.since(start) != want or tid(sess.page, 'crumb').count() or set(hash_query(sess.page)) & {'fs', 'fd', 'fp', 'rec'}:
                self.bad('%s: crumb-all sent %s, %d crumbs left, hash %s, expected exactly %s, no crumb and no scope key' % (label, sess.since(start), tid(sess.page, 'crumb').count(), hash_query(sess.page), want))
        finally:
            sess.close()

    def stub_copy_marker_scoped(self) -> None:
        '''RT10 in the page: the stored copy pair of a scoped list shows both rows under the original name, the copy with (копия N).

        Returns:
            None.
        '''
        label = 'V12 stub_copy_marker_scoped'
        sess = Session13(self.drv)
        try:
            tree = self.ref.tree
            site, docs = tree.site or 'site-none', tree.drive(rev13.DOCS)
            params = {'site_id': site, 'drive_id': docs, 'dir': rev13.DIR_TG, 'dates': [DUP_DAY], 'name_part': rev13.DUP_NAME, 'limit': LIMIT}
            if not self.start(label, sess, url([DUP_DAY], site, docs, rev13.DIR_TG, rev13.DUP_NAME)):
                return
            sess.settle(0)
            data = self.check_rows(label, sess, params)
            if data is None:
                return
            copies = [item for item in data.get('items', []) if item.get('is_copy')]
            if not copies:
                self.report.state.append('%s: the client finds no stored copy of %s in %s on %s' % (label, rev13.DUP_NAME, rev13.DIR_TG, DUP_DAY))
                return
            marks = sess.texts('result-copy-mark')
            texts = sess.page.eval_on_selector_all('[data-testid=result-row]', 'rows => rows.map(r => r.innerText)')
            if len(marks) != len(copies) or any('(копия' not in mark for mark in marks) or any('.dup-' in text for text in texts):
                self.bad('%s: %d copy marks %s for %d client copies, rows %s, expected one (копия N) per copy and no .dup- text' % (label, len(marks), marks, len(copies), [t[:50] for t in texts]))
        finally:
            sess.close()

    def load13(self) -> None:
        '''V4 revision 13 load of '#/': backup_filter_options first, then the search, the root tree call and the single-site expansion.

        Returns:
            None.
        '''
        label = 'V4 rev13 load of #/'
        sess = Session13(self.drv)
        try:
            sess.load('')
            sess.settle(0)
            self.have(label, sess.page, vue11.MAIN_IDS + ('main-grid', 'folder-tree'))
            self.report.product.extend(call_problems(label, sess.calls))
            newest = self.ref.tree.days[-1] if self.ref.tree.days else ''
            want = [(M13, {'dates': [newest], 'limit': LIMIT}), (M19, {'dates': [newest]})]
            roots = [c for c in sess.calls if c['method'] == M19 and c['params'] == {'dates': [newest]}]
            data = (roots[0].get('reply') or {}).get('result', {}).get('data') if roots and isinstance(roots[0].get('reply'), dict) else None
            nodes = data.get('nodes', []) if isinstance(data, dict) else []
            want += [(M19, {'site_id': nodes[0].get('site_id'), 'dates': [newest]})] if len(nodes) == 1 else []
            sent = sess.since(0)
            rest = [(m, {k: v for k, v in p.items() if not (m == M13 and k == 'offset' and v == 0)}) for m, p in sent[1:] if isinstance(p, dict)]
            if not sent or sent[0] != (M12, {}) or not same(rest, want):
                self.bad('%s: the page sent %s, expected backup_filter_options {} first, then exactly %s' % (label, sent, want))
        finally:
            sess.close()

    def apply13(self) -> None:
        '''V4 revision 13 apply: exactly one search, one root tree call and the single-site expansion with the applied filters.

        Returns:
            None.
        '''
        label = 'V4 rev13 apply'
        sess = Session13(self.drv)
        try:
            sess.load('')
            sess.settle(0)
            if not self.have(label, sess.page, ('filter-apply',)):
                return
            start = len(sess.calls)
            tid(sess.page, 'filter-apply').click()
            sess.settle(start, lambda: sess.answered(start, M13) > 0)
            searches = [p for m, p in sess.since(start, M13) if isinstance(p, dict)]
            trees = [c for c in sess.calls[start:] if c['method'] == M19 and isinstance(c['params'], dict)]
            roots = [c for c in trees if 'site_id' not in c['params']]
            empty: tuple[Any, ...] = ([], '', None)
            if len(searches) != 1 or not set(searches[0]) <= vue11.SEARCH_KEYS or searches[0].get('limit') != LIMIT or any(v in empty for v in searches[0].values()):
                self.bad('%s: the click sent the searches %s, expected exactly one backup_search_files with keys within %s, limit 100 and no empty value' % (label, searches, sorted(vue11.SEARCH_KEYS)))
            if len(roots) != 1 or not set(roots[0]['params']) <= {'site_ids', 'dates', 'name_part'} or any(v in empty for v in roots[0]['params'].values()):
                self.bad('%s: the click sent the tree calls %s, expected exactly one root backup_folder_children with the applied filters' % (label, [c['params'] for c in trees]))
                return
            data = (roots[0].get('reply') or {}).get('result', {}).get('data') if isinstance(roots[0].get('reply'), dict) else None
            nodes = data.get('nodes', []) if isinstance(data, dict) else []
            want = [dict(roots[0]['params'], site_id=nodes[0].get('site_id'))] if len(nodes) == 1 else []
            if [c['params'] for c in trees if 'site_id' in c['params']] != want or [m for m, _ in sess.since(start) if m not in (M13, M19)]:
                self.bad('%s: the expansions after the apply are %s, expected exactly %s and no other command' % (label, [c['params'] for c in trees if 'site_id' in c['params']], want))
        finally:
            sess.close()
