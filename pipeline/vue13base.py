'''Revision 13 helpers of the UI-TREE browser cases (matrix TODO 10.21.6 and 10.21.8, row V12, block UI-TREE).

Session13 extends the recording session of pipeline.vuebrowser: a request the page aborts is marked 'failed', and a stub function may
answer a chosen JSON-RPC call with an error or park it until the case answers it (the stub-only cases of 10.21.6). Every wait polls the
recorded call status or a DOM condition every POLL_MS and ends on that condition; quiescence is the condition 'every recorded call is
answered and no new call arrived for QUIET_POLLS polls'. Nothing here sleeps for a fixed time. Ref is the reference side: the counts
and orders the page must show are read from the project client of the checkout source (BackupClient.raw_call through rev13.Tree, the
0.3.25 client has no folder method), never assumed.
'''

from __future__ import annotations

import json
import urllib.parse
from typing import Any, Callable

from pipeline import rev13, vue11
from pipeline.report import Report
from pipeline.vuebase import TESTIDS
from pipeline.vuebrowser import Session
from pipeline.vueroutes import hash_of

M12, M13, M14, M19 = 'backup_filter_options', 'backup_search_files', 'backup_suggest_names', 'backup_folder_children'
SCOPE_KEYS = ('site_id', 'drive_id', 'dir', 'recursive')
TREE_KEYS = ('site_id', 'drive_id', 'dir', 'site_ids', 'dates', 'name_part', 'limit', 'offset')
HASH_SCOPE = ('fs', 'fd', 'fp', 'rec')
POLL_MS = 100
QUIET_POLLS = 5
BOUND_MS = 45000
STUB_ERROR = 'SOURCE_NOT_READY: stub answer of the pipeline (tree error case)'
STALE = 'STALE-STUB-FOLDER'
LOAD13 = tuple(name for name in TESTIDS if name not in ('tree-more', 'tree-loading', 'tree-empty', 'crumb'))
vue11.ACTIONS.update({M19: ((), TREE_KEYS, {}), M13: ((), ('site_ids', 'dates', 'name_part', 'limit', 'offset') + SCOPE_KEYS, {'limit': 100}),
                      M14: (('text',), ('site_ids', 'dates', 'limit') + SCOPE_KEYS, {'limit': 10})})
NODES_JS = (
    'els => els.map(e => { const own = t => Array.from(e.querySelectorAll("[data-testid=" + t + "]"))'
    '.find(x => x.closest("[data-testid=tree-node]") === e) || null;'
    ' const lab = own("tree-label"), cnt = own("tree-count");'
    ' return {kind: e.getAttribute("data-kind") || "", site: e.getAttribute("data-site-id") || "", drive: e.getAttribute("data-drive-id") || "",'
    ' dir: e.getAttribute("data-dir") || "", raw: e.getAttribute("data-raw") || "", level: e.getAttribute("aria-level") || "",'
    ' expanded: e.getAttribute("aria-expanded"), selected: e.getAttribute("aria-selected"), role: e.getAttribute("role") || "",'
    ' label: lab ? lab.textContent.trim() : "", count: cnt ? cnt.textContent.trim() : "", count_raw: cnt ? (cnt.getAttribute("data-raw") || "") : "",'
    ' toggle: !!own("tree-toggle"), shown: e.offsetParent !== null}; })'
)
FOCUS_JS = ('(() => { const a = document.activeElement; const n = a && a.closest ? a.closest("[role=treeitem]") : null;'
            ' return n ? [n.getAttribute("data-testid") || "", n.getAttribute("data-kind") || "", n.getAttribute("data-drive-id") || "",'
            ' n.getAttribute("data-dir") || ""] : null; })()')
ITEMS_JS = ('Array.from(document.querySelectorAll("[data-testid=folder-tree] [role=treeitem]")).filter(e => e.offsetParent !== null)'
            '.map(e => [e.getAttribute("data-testid") || "", e.getAttribute("data-kind") || "", e.getAttribute("data-drive-id") || "",'
            ' e.getAttribute("data-dir") || ""])')


def q(value: str) -> str:
    '''Return a CSS attribute value literal (double quoted, escaped).

    Args:
        value: the attribute value.

    Returns:
        The quoted literal.
    '''
    return json.dumps(value, ensure_ascii=False)


def enc(value: str) -> str:
    '''Return encodeURIComponent(value) ('/' becomes %2F).

    Args:
        value: a hash value.

    Returns:
        The encoded value.
    '''
    return urllib.parse.quote(value, safe='')


def url(dates: list[str], site: str = '', drive: str = '', folder: str | None = None, name: str = '', rec: bool = False) -> str:
    '''Return the main page hash of 10.21.6 STATE IN THE HASH for these filters and scope.

    Args:
        dates: the date keys.
        site: fs, the scope site id.
        drive: fd, the scope drive id.
        folder: fp, the scope dir, or None.
        name: q, the name part.
        rec: rec=1.

    Returns:
        The hash route.
    '''
    parts = ['date=' + enc(day) for day in dates] + (['q=' + enc(name)] if name else [])
    parts += (['fs=' + enc(site)] if site else []) + (['fd=' + enc(drive)] if drive else []) + (['fp=' + enc(folder)] if folder is not None else [])
    return '#/?' + '&'.join(parts + (['rec=1'] if rec else []))


def hash_query(page: Any) -> dict[str, list[str]]:
    '''Return the query inside the location hash of the page.

    Args:
        page: the page.

    Returns:
        The parsed query (key -> values).
    '''
    text = hash_of(page)
    return urllib.parse.parse_qs(text.split('?', 1)[1], keep_blank_values=True) if '?' in text else {}


def canon(item: tuple[Any, Any]) -> str:
    '''Return a sortable text of one (method, params) pair.

    Args:
        item: the pair.

    Returns:
        Its JSON text with sorted keys.
    '''
    return json.dumps(item, sort_keys=True, ensure_ascii=False)


def same(sent: list[tuple[Any, Any]], want: list[Any]) -> bool:
    '''Return whether two call lists are equal as multisets.

    Args:
        sent: the recorded (method, params) pairs.
        want: the expected pairs.

    Returns:
        True when equal.
    '''
    return sorted(canon(item) for item in sent) == sorted(canon(item) for item in want)


class Session13(Session):
    '''A recording session with marked aborts, a stub hook and condition waits.

    Attributes:
        stub: None, or a function (method, params) -> 'error', 'hold' or None deciding how a JSON-RPC call is answered.
        parked: the held routes and their JSON-RPC ids.
    '''

    def __init__(self, drv: Any, clock: bool = False, size: tuple[int, int] = (1600, 900)) -> None:
        '''Open the recording page with the viewport size.

        Args:
            drv: the headless driver.
            clock: install the Playwright clock.
            size: the viewport (width, height).
        '''
        self.stub: Callable[[str, dict], str | None] | None = None
        self.parked: list[tuple[Any, Any]] = []
        super().__init__(drv, clock)
        self.page.set_viewport_size({'width': size[0], 'height': size[1]})
        self.page.on('requestfailed', self._failed)

    def _failed(self, request: Any) -> None:
        '''Mark a recorded call whose request failed or was aborted by the page.

        Args:
            request: the Playwright request.

        Returns:
            None.
        '''
        entry = self._by_request.get(request)
        if entry is not None and entry['status'] is None:
            entry['status'] = 'failed'

    def _route(self, route: Any) -> None:
        '''Answer a call by the stub (error or park) or hand it to the recording route of the base session.

        Args:
            route: the Playwright route.

        Returns:
            None.
        '''
        verdict: str | None = None
        ident: Any = 1
        if self.stub is not None:
            try:
                body = json.loads(route.request.post_data or 'null')
            except ValueError:
                body = None
            body = body if isinstance(body, dict) else {}
            params = body.get('params')
            ident = body.get('id', 1)
            verdict = self.stub(str(body.get('method')), params if isinstance(params, dict) else {})
        if verdict == 'hold':
            entry = self._by_request.get(route.request)
            if entry is not None:
                entry['parked'] = True
            self.parked.append((route, ident))
        elif verdict == 'error':
            route.fulfill(status=200, content_type='application/json',
                          body=json.dumps({'jsonrpc': '2.0', 'id': ident, 'error': {'code': 503, 'message': STUB_ERROR}}))
        else:
            super()._route(route)

    def answer_parked(self, data: dict) -> int:
        '''Answer every parked call with a successful result carrying data.

        Args:
            data: the result data.

        Returns:
            How many parked calls could still be answered (an aborted request cannot).
        '''
        parked, self.parked, done = self.parked, [], 0
        for route, ident in parked:
            try:
                route.fulfill(status=200, content_type='application/json',
                              body=json.dumps({'jsonrpc': '2.0', 'id': ident, 'result': {'success': True, 'data': data}}, ensure_ascii=False))
                done += 1
            except Exception:
                continue
        return done

    def since(self, start: int, *methods: str) -> list[tuple[Any, Any]]:
        '''Return the recorded (method, params) pairs from index start, only of methods when given.

        Args:
            start: the first call index.
            methods: the methods to keep (all when empty).

        Returns:
            The pairs.
        '''
        return [(c['method'], c['params']) for c in self.calls[start:] if not methods or c['method'] in methods]

    def answered(self, start: int, method: str) -> int:
        '''Return how many calls of method from index start have their answer.

        Args:
            start: the first call index.
            method: the method.

        Returns:
            The count.
        '''
        return sum(1 for c in self.calls[start:] if c['method'] == method and c['status'] is not None)

    def settle(self, start: int = 0, want: Callable[[], bool] | None = None, bound: int = BOUND_MS) -> bool:
        '''Poll until want() holds, every recorded call from start is answered (or parked) and no call arrived for QUIET_POLLS polls.

        Args:
            start: the first call index.
            want: the extra condition, or None.
            bound: the bound in ms.

        Returns:
            True when the condition was reached within the bound.
        '''
        stable, seen, waited = 0, -1, 0
        while waited <= bound:
            done = all(c['status'] is not None or c.get('parked') for c in self.calls[start:]) and (want is None or want())
            stable = stable + 1 if done and len(self.calls) == seen else 0
            seen = len(self.calls)
            if stable >= QUIET_POLLS:
                return True
            self.page.wait_for_timeout(POLL_MS)
            waited += POLL_MS
        return False

    def until(self, test: Callable[[], bool], bound: int = BOUND_MS) -> bool:
        '''Poll a DOM or call condition every POLL_MS.

        Args:
            test: the condition.
            bound: the bound in ms.

        Returns:
            True when it held within the bound.
        '''
        waited = 0
        while waited <= bound:
            if test():
                return True
            self.page.wait_for_timeout(POLL_MS)
            waited += POLL_MS
        return False

    def load(self, route: str) -> None:
        '''Open the index page or a hash route and settle on the first answered search.

        Args:
            route: the hash route ('' for the index page).

        Returns:
            None.
        '''
        self.page.goto(self.drv.root + '/' + route, wait_until='load', timeout=30000)
        self.settle(0, lambda: self.answered(0, M13) > 0, bound=30000)

    def nodes(self) -> list[dict]:
        '''Return every tree-node of the page with its own label, count, toggle and attributes.

        Returns:
            The node maps in DOM order.
        '''
        return list(self.page.eval_on_selector_all('[data-testid=tree-node]', NODES_JS))

    def children(self, drive: str, parent: str | None) -> list[dict]:
        '''Return the shown nodes below one parent: libraries of the site (parent None) or folders whose parent dir is parent.

        Args:
            drive: the drive id ('' for the libraries of the site).
            parent: the parent dir ('' = the library root), or None for libraries.

        Returns:
            The node maps in DOM order.
        '''
        found = []
        for node in self.nodes():
            if not node['shown']:
                continue
            if parent is None and node['kind'] == 'library':
                found.append(node)
            elif parent is not None and node['kind'] == 'folder' and node['drive'] == drive and node['dir'].rpartition('/')[0] == parent:
                found.append(node)
        return found

    def node(self, kind: str, site: str = '', drive: str = '', folder: str | None = None) -> Any:
        '''Return the locator of one tree-node.

        Args:
            kind: site, library or folder.
            site: data-site-id.
            drive: data-drive-id.
            folder: data-dir.

        Returns:
            The locator.
        '''
        sel = '[data-testid=tree-node][data-kind=%s]' % kind
        sel += ('[data-site-id=%s]' % q(site) if site else '') + ('[data-drive-id=%s]' % q(drive) if drive else '')
        return self.page.locator(sel + ('[data-dir=%s]' % q(folder) if folder is not None else ''))

    def focused(self) -> tuple | None:
        '''Return (testid, kind, drive, dir) of the treeitem holding the focus, or None.

        Returns:
            The focus tuple.
        '''
        got = self.page.evaluate(FOCUS_JS)
        return tuple(got) if got else None

    def items(self) -> list[tuple]:
        '''Return the visible treeitems of folder-tree in DOM order.

        Returns:
            (testid, kind, drive, dir) per item.
        '''
        return [tuple(item) for item in self.page.evaluate(ITEMS_JS)]

    def row_names(self) -> list[Any]:
        '''Return the data-raw name of every result-row.

        Returns:
            The names.
        '''
        return list(self.page.eval_on_selector_all('[data-testid=result-row]', 'rows => rows.map(r => (r.querySelector("[data-field=name]") || r).getAttribute("data-raw"))'))

    def texts(self, name: str) -> list[str]:
        '''Return the trimmed text of every element with one test id.

        Args:
            name: the test id.

        Returns:
            The texts.
        '''
        return [str(text).strip() for text in self.page.eval_on_selector_all('[data-testid="%s"]' % name, 'els => els.map(e => e.textContent)')]

    def box(self, name: str) -> dict | None:
        '''Return the bounding box of the first element with one test id.

        Args:
            name: the test id.

        Returns:
            The box, or None.
        '''
        loc = self.page.locator('[data-testid="%s"]' % name)
        return loc.first.bounding_box() if loc.count() else None


class Ref:
    '''The reference side of the cases: the project client of the checkout source, read once per check run.

    Attributes:
        report: the findings collector.
    '''

    def __init__(self, report: Report) -> None:
        '''Keep the report; the client state is read on first use.

        Args:
            report: the findings collector.
        '''
        self.report = report
        self._tree: rev13.Tree | None = None

    @property
    def tree(self) -> rev13.Tree:
        '''Return the revision 13 state (site, libraries, listing of F4), read on first use.

        Returns:
            The state.
        '''
        if self._tree is None:
            self._tree = rev13.Tree(self.report)
        return self._tree

    def ask(self, label: str, command: str, params: dict) -> dict | None:
        '''Send one command through the client and return its data, or None with a PRODUCT finding.

        Args:
            label: the case label.
            command: the command.
            params: the parameters.

        Returns:
            The data map, or None.
        '''
        kind, code, message, data = self.tree.send(command, params)
        if kind != 'success' or not isinstance(data, dict):
            self.report.product.append('%s: the client %s %s answers %s %s %s, expected a result (reference side of the case)' % (label, command, params, kind, code, message[:160]))
            return None
        return data

    def nodes(self, label: str, params: dict, upto: int = 500) -> tuple[list[dict], int] | None:
        '''Return the first upto children of one M19 address (pages of 200 concatenated) and the total.

        Args:
            label: the case label.
            params: the M19 address and filters.
            upto: how many nodes to read at most.

        Returns:
            (nodes, total), or None.
        '''
        found: list[dict] = []
        total = 0
        while len(found) < upto:
            data = self.ask(label, M19, dict(params, limit=200, offset=len(found)))
            if data is None:
                return None
            got, total = list(data.get('nodes', [])), int(data.get('total', 0))
            found += got
            if not got or len(found) >= total:
                break
        return found[:upto], total


def shown(node: dict) -> tuple:
    '''Return the comparable part of a page tree-node.

    Args:
        node: a node map of Session13.nodes.

    Returns:
        (kind, site, drive, dir, label, raw, toggle).
    '''
    return node['kind'], node['site'], node['drive'], node['dir'], node['label'], node['raw'], node['toggle']


def wanted(node: dict) -> tuple:
    '''Return the comparable part of a client M19 node.

    Args:
        node: a node of the client result.

    Returns:
        (kind, site_id, drive_id, dir, name, str(file_count), has_children).
    '''
    return (str(node.get('kind')), str(node.get('site_id') or ''), str(node.get('drive_id') or ''), str(node.get('dir') or ''), str(node.get('name')),
            str(node.get('file_count')), bool(node.get('has_children')))
