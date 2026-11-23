'''Revision 13 validators of row M19 backup_folder_children (matrix TODO 10.21.7 TC1-TC6, TC15, TC16; relations RT3-RT5, RT9).

Every expected number is derived by relation from backup_search_files, from the reference listing of F4 (snapshot of ДЕНЬГИ on
2026-11-21, read once by pipeline.rev13.Tree) or from the inventory; sort orders are computed with key() = casefold(NFC).
'''

from __future__ import annotations

import time
from typing import Callable

from pipeline import rev11
from pipeline.rev13 import DENGI, DIR_WIDE, EXPORT_COMMANDS, SCHEDULE_REVISION, SITE_NAME, Case

COMMAND = 'backup_folder_children'
TOP = ['index', 'limit', 'nodes', 'offset', 'path', 'timezone', 'total']
NODE_KEYS = ['dir', 'direct_count', 'drive_id', 'file_count', 'has_children', 'kind', 'name', 'site_id']
PATH_KEYS = ['dir', 'drive_id', 'kind', 'name', 'site_id']
BOUND_TREE = 1.0
BOUND_SCOPE = 3.0


def shape(case: Case, data: dict, limit: int = 200, offset: int = 0) -> bool:
    '''Judge one M19 page: exact fields, echoes, node shape and types, pruning, order key(name) then name.

    Args:
        case: the executed case.
        data: the page.
        limit: the effective limit.
        offset: the effective offset.

    Returns:
        True when the page is conformant.
    '''
    saved, case.data = case.data, data
    good = case.fields(TOP)
    case.data = saved
    if not good:
        return False
    before = len(case.report.product)
    nodes = data['nodes']
    if (data['limit'], data['offset']) != (limit, offset) or len(nodes) > limit or not isinstance(data['total'], int) or data['total'] < len(nodes) or data['timezone'] != rev11.TZ:
        case.bad('limit/offset %s/%s, %d nodes for total %r, timezone %r; expected %s/%s and %s' % (data['limit'], data['offset'], len(nodes), data['total'], data['timezone'], limit, offset, rev11.TZ))
    for node in nodes:
        strings = all(isinstance(node.get(k), str) for k in ('site_id', 'drive_id', 'dir', 'name'))
        counts = type(node.get('file_count')) is int and type(node.get('direct_count')) is int and type(node.get('has_children')) is bool
        if sorted(node) != NODE_KEYS or not strings or not counts or node['kind'] not in ('site', 'library', 'folder'):
            case.bad('node %s is not {%s} with strings, integers and a boolean' % (str(node)[:160], ', '.join(NODE_KEYS)))
            break
        if node['file_count'] < 1 or node['direct_count'] < 0 or node['direct_count'] > node['file_count'] or node['has_children'] != (node['file_count'] > node['direct_count']):
            case.bad('node %r: file_count %s, direct_count %s, has_children %s break RT9/RT4 (file_count >= 1, has_children iff rows below)' % (node['name'], node['file_count'], node['direct_count'], node['has_children']))
    if [(rev11.key(n.get('name', '')), n.get('name', '')) for n in nodes] != sorted((rev11.key(n.get('name', '')), n.get('name', '')) for n in nodes):
        case.bad('nodes are not ordered by key(name), then name')
    if any(sorted(item) != PATH_KEYS for item in data['path']):
        case.bad('path %s is not a list of {%s}' % (str(data['path'])[:160], ', '.join(PATH_KEYS)))
    return len(case.report.product) == before


def path_for(case: Case, drive: str = '', folder: str = '') -> list[dict]:
    '''Return the expected path chain site -> library -> folders to the addressed parent inclusive.

    Args:
        case: the executed case.
        drive: the library address or ''.
        folder: the folder address or ''.

    Returns:
        The path entries.
    '''
    tree = case.tree
    site = tree.site or ''
    chain = [{'kind': 'site', 'name': tree.site_name, 'site_id': site, 'drive_id': '', 'dir': ''}]
    if drive:
        chain.append({'kind': 'library', 'name': tree.libraries.get(drive, drive), 'site_id': site, 'drive_id': drive, 'dir': ''})
    parts = folder.split('/') if folder else []
    for index, part in enumerate(parts):
        chain.append({'kind': 'folder', 'name': part, 'site_id': site, 'drive_id': drive, 'dir': '/'.join(parts[:index + 1])})
    return chain


def pages(case: Case, params: dict, limit: int) -> tuple[list[dict], int] | None:
    '''Read every page of one M19 address with the given limit and judge each page.

    Args:
        case: the executed case.
        params: the address and filters.
        limit: the page size.

    Returns:
        (all nodes, total) or None after a finding.
    '''
    nodes: list[dict] = []
    offset, total = 0, 1
    while offset < total:
        data = case.need(COMMAND, dict(params, limit=limit, offset=offset))
        if data is None or not shape(case, data, limit, offset):
            return None
        if offset and data['total'] != total:
            case.bad('the total changed from %s to %s between pages' % (total, data['total']))
            return None
        total, offset = data['total'], offset + limit
        nodes += data['nodes']
        if not data['nodes']:
            break
    return nodes, total


def _fc_roots(case: Case) -> None:
    '''TC1: the sites with rows, kind site, counts summing to the flat search total (RT4), path [].

    Args:
        case: the executed case.

    Returns:
        None.
    '''
    if not shape(case, case.data):
        return
    nodes, flat = case.data['nodes'], case.total({})
    sites = {i['site_id']: i['name'] for i in (case.need('backup_filter_options', {}) or {}).get('sites', [])}
    if any(n['kind'] != 'site' or n['drive_id'] != '' or n['dir'] != '' or n['direct_count'] != 0 or not n['has_children'] for n in nodes):
        case.bad("a root node is not {kind 'site', drive_id '', dir '', direct_count 0, has_children true}")
    if {n['site_id']: n['name'] for n in nodes} != sites or case.data['total'] != len(nodes) or case.data['path'] != []:
        case.bad('roots %s, total %s, path %s; expected the sites %s of backup_filter_options and path []' % ({n['site_id'][-12:]: n['name'] for n in nodes}, case.data['total'], case.data['path'], list(sites.values())))
    if sum(n['file_count'] for n in nodes) != flat:
        case.bad('the root file_count sum %s differs from the backup_search_files {} total %s (RT4)' % (sum(n['file_count'] for n in nodes), flat))
    if [n['name'] for n in nodes] != [SITE_NAME]:
        case.report.state.append('%s: TC1 expects exactly one site %s today, the roots are %s' % (case.desc, SITE_NAME, [n['name'] for n in nodes]))


def _fc_libraries(case: Case) -> None:
    '''TC2: the libraries of the site, names from backup_libraries_list, counts by RT3, sum equal to the site node (RT4).

    Args:
        case: the executed case.

    Returns:
        None.
    '''
    tree, data = case.tree, case.data
    if not shape(case, data):
        return
    roots = (case.need(COMMAND, {}) or {}).get('nodes', [])
    site_count = next((n.get('file_count') for n in roots if n.get('site_id') == tree.site), None)
    got = {n['drive_id']: n['name'] for n in data['nodes']}
    if got != tree.libraries or data['total'] != len(data['nodes']) or len(got) != 3 or any(n['kind'] != 'library' or n['site_id'] != tree.site or n['dir'] != '' for n in data['nodes']):
        case.bad("libraries %s, total %s; expected the 3 libraries %s of backup_libraries_list, kind 'library', dir ''" % (sorted(got.values()), data['total'], sorted(tree.libraries.values())))
    for node in data['nodes']:
        scope = {'site_id': tree.site, 'drive_id': node['drive_id']}
        deep, root = case.total(dict(scope, recursive=True)), case.total(scope)
        if (node['file_count'], node['direct_count']) != (deep, root):
            case.bad('library %r: file_count/direct_count %s/%s, backup_search_files recursive/root totals %s/%s (RT3)' % (node['name'], node['file_count'], node['direct_count'], deep, root))
    if sum(n['file_count'] for n in data['nodes']) != site_count or data['path'] != path_for(case):
        case.bad('library sum %s vs site node %s (RT4), path %s vs %s' % (sum(n['file_count'] for n in data['nodes']), site_count, data['path'], path_for(case)))


def _fc_folders(case: Case) -> None:
    '''TC3: the six top folders of ДЕНЬГИ on 2026-11-21 equal the ones recomputed from the reference listing.

    Args:
        case: the executed case.

    Returns:
        None.
    '''
    tree, data, drive = case.tree, case.data, case.params['drive_id']
    if not shape(case, data):
        return
    dirs = [d for d, _ in tree.files]
    want = [{'kind': 'folder', 'site_id': tree.site, 'drive_id': drive, 'dir': f, 'name': f, 'direct_count': dirs.count(f),
             'file_count': sum(1 for d in dirs if d == f or d.startswith(f + '/')), 'has_children': any(d.startswith(f + '/') for d in dirs)}
            for f in tree.folders]
    if data['nodes'] != want or data['total'] != len(want) or data['path'] != path_for(case, drive):
        case.bad('folders %s, total %s; expected %s from the listing of %s, path [site, library]'
                 % ([(n.get('name'), n.get('file_count'), n.get('direct_count')) for n in data['nodes']], data['total'], [(w['name'], w['file_count'], w['direct_count']) for w in want], tree.listing_id[:8]))
    if len(want) != 6 or len(dirs) != 347 or '' in dirs or any(w['has_children'] for w in want):
        case.report.state.append('%s: F4 expects 6 leaf folders, 347 files and no root file, the listing has %d folders and %d files' % (case.desc, len(want), len(dirs)))


def _fc_leaf(case: Case) -> None:
    '''TC4: a leaf folder has no children; the path reaches the folder.

    Args:
        case: the executed case.

    Returns:
        None.
    '''
    params = case.params
    if shape(case, case.data) and (case.data['nodes'], case.data['total'], case.data['path']) != ([], 0, path_for(case, params['drive_id'], params['dir'])):
        case.bad('expected nodes [], total 0 and the path [site, library, folder], got %s' % str(case.data)[:200])


def _fc_name(case: Case) -> None:
    '''TC5: under a name part every node count equals the scoped search (RT3), partition holds (RT4); no match prunes all (RT9).

    Args:
        case: the executed case.

    Returns:
        None.
    '''
    tree, params = case.tree, case.params
    if params.get('name_part') == 'zzzzqqqq':
        others = [{'site_id': tree.site}, {'site_id': tree.site, 'drive_id': tree.drive(DENGI), 'dir': tree.table['$DIR_DENGI_FOLDER']}]
        for data in [case.data] + [case.need(COMMAND, dict(other, name_part='zzzzqqqq')) for other in others]:
            if data is not None and shape(case, data) and (data['nodes'], data['total']) != ([], 0):
                case.bad('a name part that matches nothing must give nodes [] and total 0, got %s' % str(data)[:160])
        return
    listed = pages(case, params, 200)
    if listed is None:
        return
    filters = {'name_part': params['name_part'], 'dates': params['dates']}
    for node in listed[0]:
        scope = dict(filters, site_id=tree.site, drive_id=node['drive_id'], dir=node['dir'])
        deep, flat = case.total(dict(scope, recursive=True)), case.total(scope)
        if (node['file_count'], node['direct_count']) != (deep, flat):
            case.bad('folder %r: file_count/direct_count %s/%s, scoped search totals %s/%s (RT3)' % (node['dir'], node['file_count'], node['direct_count'], deep, flat))
    libs = (case.need(COMMAND, dict(filters, site_id=tree.site)) or {}).get('nodes', [])
    lib: dict = next((n for n in libs if n.get('drive_id') == params['drive_id']), {})
    if lib.get('file_count') != lib.get('direct_count', -1) + sum(n['file_count'] for n in listed[0]):
        case.bad('library file_count %s != its direct_count %s + the sum of its folders %s (RT4)' % (lib.get('file_count'), lib.get('direct_count'), sum(n['file_count'] for n in listed[0])))


def _fc_paging(case: Case) -> None:
    '''TC6: pages of 200 concatenated equal pages of 500 (RT5); an offset beyond the total gives nodes [] and the exact total.

    Args:
        case: the executed case.

    Returns:
        None.
    '''
    params = {k: v for k, v in case.params.items() if k not in ('limit', 'offset')}
    if 'offset' in case.params:
        first = case.need(COMMAND, params)
        if shape(case, case.data, 200, case.params['offset']) and (first is None or case.data['nodes'] != [] or case.data['total'] != first.get('total') or not first.get('total')):
            case.bad('offset %s: expected nodes [] and the total %s, got %s' % (case.params['offset'], (first or {}).get('total'), str(case.data)[:160]))
        return
    small, big = pages(case, params, 200), pages(case, params, 500)
    if small is not None and big is not None and (small != big or small[1] < 1 or len(small[0]) != small[1]):
        case.bad('pages of 200 (%d nodes, total %s) differ from pages of 500 (%d nodes, total %s) of %r (RT5)' % (len(small[0]), small[1], len(big[0]), big[1], DIR_WIDE))


def _nowrite(case: Case) -> None:
    '''TC15: M19, M13 and M14 leave snapshots, index counts, rows per date and the schedule revision unchanged; no export.

    Args:
        case: the executed case.

    Returns:
        None.
    '''
    tree = case.tree
    scope = {'site_id': tree.site, 'drive_id': tree.drive(DENGI)}
    case.need('backup_search_files', dict(scope, recursive=True))
    case.need('backup_suggest_names', dict(scope, text='акт'))
    after = tree.state()
    if after != tree.before or after['schedule'] != SCHEDULE_REVISION:
        case.bad('the state changed: before %s, after %s (schedule revision expected %s)' % (str(tree.before)[:200], str(after)[:200], SCHEDULE_REVISION[:8]))
    if any(name in EXPORT_COMMANDS for name in tree.sent):
        case.bad('an export command was sent: %s' % [n for n in tree.sent if n in EXPORT_COMMANDS])


def _latency(case: Case) -> None:
    '''TC16: M19 {} and M19 of the widest folder within 1 s, M13 with a folder scope within 3 s (warm client).

    Args:
        case: the executed case.

    Returns:
        None.
    '''
    tree = case.tree
    scope = {'site_id': tree.site, 'drive_id': tree.drive(DENGI), 'dir': tree.table['$DIR_NEAKTIVNYE'], 'dates': ['2026-11-21']}
    wide = {'site_id': tree.site, 'drive_id': tree.table['$DRIVE_DOCS'], 'dir': DIR_WIDE}
    probes: tuple[tuple[str, dict, float], ...] = ((COMMAND, {}, BOUND_TREE), (COMMAND, wide, BOUND_TREE), ('backup_search_files', scope, BOUND_SCOPE))
    times = []
    for command, params, bound in probes:
        start = time.monotonic()
        data = case.need(command, params)
        spent = time.monotonic() - start
        times.append('%s %.2fs' % (command, spent))
        if data is not None and spent > bound:
            case.bad('%s(%s) answered in %.2f s, bound %.1f s (TC16)' % (command, list(params), spent, bound))
    case.report.info.append('TC16 latency: %s' % ', '.join(times))


VALIDATORS: dict[str, Callable[[Case], None]] = {
    'fc_roots': _fc_roots, 'fc_libraries': _fc_libraries, 'fc_folders': _fc_folders, 'fc_leaf': _fc_leaf, 'fc_name': _fc_name,
    'fc_paging': _fc_paging, 'nowrite': _nowrite, 'latency': _latency,
}
