'''Revision 13 validators of the scope cases of M13 backup_search_files and M14 backup_suggest_names (matrix TODO 10.21.7 TC7-TC14).

Expected rows come from the reference listing of F4 (pipeline.rev13.Tree), from single-date or per-library totals (relations RT3, RT4,
RT6, RT7, RT8, RT10) and from the matcher of 10.19.3 (pipeline.rev11.matcher); every item of a 0.3.26 search carries drive_id.
'''

from __future__ import annotations

from typing import Callable

from pipeline import rev11
from pipeline.rev13 import DIR_TG, DUP_NAME, Case, digest, local_day

ITEM_KEYS = sorted(rev11.ITEM_KEYS + ['drive_id'])


def items_ok(case: Case, drive: str | None = None) -> bool:
    '''Judge a search page: the 0.3.25 page rules of rev11, the added field drive_id, and the library of every row.

    Args:
        case: the executed case.
        drive: the library every row must belong to, or None.

    Returns:
        True when the page is conformant.
    '''
    before = len(case.report.product)
    rev11._page(case, case.params.get('limit', 100), case.params.get('offset', 0))
    lacking = [i.get('name') for i in case.data.get('items', []) if sorted(i) != ITEM_KEYS]
    if lacking:
        case.bad('%d item(s) lack the field drive_id or carry others, e.g. %r (10.21.4: items are %s)' % (len(lacking), lacking[0], ITEM_KEYS))
    for item in case.data.get('items', []) if not lacking else []:
        segments = str(item['file_path']).split('/')
        if case.tree.libraries.get(item['drive_id']) != item['library_name'] or len(segments) < 3 or segments[2] != digest(item['drive_id']):
            case.bad('item %r: drive_id %r is not the library %r of its file_path' % (item['name'], item['drive_id'], item['library_name']))
            break
        if drive is not None and item['drive_id'] != drive:
            case.bad('item %r of library %r is outside the scope library' % (item['name'], item['library_name']))
            break
    return len(case.report.product) == before


def _listed(case: Case, folder: str) -> list[str]:
    '''Return the names of the reference listing in folder, sorted.

    Args:
        case: the executed case.
        folder: the dir.

    Returns:
        The names.
    '''
    return sorted(name for d, name in case.tree.files if d == folder)


def _s_scope_dir(case: Case) -> None:
    '''TC7: a folder scope (direct, or recursive on a leaf) returns exactly the files of that folder in the listing.

    Args:
        case: the executed case.

    Returns:
        None.
    '''
    folder, drive = case.params['dir'], case.params['drive_id']
    want = _listed(case, folder)
    if not items_ok(case, drive):
        return
    items = case.data['items']
    if case.data['total'] != len(want) or sorted(i['name'] for i in items) != want:
        case.bad('total %s and %d names, expected the %d files of %r in the listing' % (case.data['total'], len(items), len(want), folder))
    if any(i['dir'] != folder or i['snapshot_id'] != case.tree.listing_id for i in items):
        case.bad('a row is outside the folder %r or the snapshot %s' % (folder, case.tree.listing_id[:8]))


def _s_scope_root(case: Case) -> None:
    '''TC8: the library root of ДЕНЬГИ holds no file; with recursive true the whole library is the listing.

    Args:
        case: the executed case.

    Returns:
        None.
    '''
    want = len(case.tree.files) if case.params.get('recursive') else len(_listed(case, ''))
    if items_ok(case, case.params['drive_id']) and (case.data['total'] != want or (want == 0) != (case.data['items'] == [])):
        case.bad('total %s with %d items, expected %d (recursive %s)' % (case.data['total'], len(case.data['items']), want, case.params.get('recursive', False)))


def _s_scope_name(case: Case) -> None:
    '''TC9: scope AND name part: the total equals the listing names of the folder that match, computed with key().

    Args:
        case: the executed case.

    Returns:
        None.
    '''
    match = rev11.matcher(case.params['name_part'])
    want = [name for name in _listed(case, case.params['dir']) if match(name)]
    if not items_ok(case, case.params['drive_id']):
        return
    names = sorted(i['name'] for i in case.data['items'])
    if case.data['total'] != len(want) or not want or (len(want) <= 100 and names != want):
        case.bad('total %s, names %s; expected the %d matching names of the listing' % (case.data['total'], names[:5], len(want)))


def _s_scope_filter(case: Case) -> None:
    '''TC10: a scope whose site is not among site_ids gives nothing (RT6); two dates give the rows of both snapshots.

    Args:
        case: the executed case.

    Returns:
        None.
    '''
    if 'site_ids' in case.params:
        if (case.data.get('total'), case.data.get('items')) != (0, []):
            case.bad('expected total 0 and items [], got %s' % str(case.data)[:160])
        return
    if not items_ok(case, case.params['drive_id']):
        return
    single = [case.total(dict(case.params, dates=[day])) for day in case.params['dates']]
    days = sorted({local_day(i['snapshot_time']) for i in case.data['items']})
    twice: dict[tuple, list[str]] = {}
    for item in case.data['items']:
        twice.setdefault((item['dir'], item['name'], item['copy_index']), []).append(item['snapshot_time'])
    if None in single or case.data['total'] != sum(s or 0 for s in single) or days != sorted(case.params['dates']):
        case.bad('total %s vs the single-date totals %s, row dates %s vs %s' % (case.data['total'], single, days, case.params['dates']))
    elif not any(len(set(times)) == 2 for times in twice.values()):
        case.bad('no file appears once per snapshot with two different snapshot_time')


def _s_scope_dup(case: Case) -> None:
    '''TC11: the stored copy pair of the Telegram Desktop folder: a primary and a copy, same name and dir, counted by M19 (RT10).

    Args:
        case: the executed case.

    Returns:
        None.
    '''
    if not items_ok(case, case.params['drive_id']):
        return
    pair = [i for i in case.data['items'] if rev11.key(i['name']) == rev11.key(DUP_NAME) and i['dir'] == DIR_TG]
    kinds = sorted((i['copy_index'], i['is_copy']) for i in pair)
    if kinds[:1] != [(0, False)] or not any(index >= 1 and copy for index, copy in kinds):
        case.report.state.append('%s: the stored duplicate pair of %r is absent in the live state: rows %s' % (case.desc, DUP_NAME, kinds))
        return
    parent = DIR_TG.rsplit('/', 1)[0]
    data = case.need('backup_folder_children', {k: case.params[k] for k in ('site_id', 'drive_id', 'dates', 'name_part')} | {'dir': parent}) or {}
    node: dict = next((n for n in data.get('nodes', []) if n.get('dir') == DIR_TG), {})
    if node.get('file_count') != case.data['total'] or case.data['total'] < 2:
        case.bad('M19 counts %s rows for %r, the search returns %s (RT10: both objects of the pair count)' % (node.get('file_count'), DIR_TG, case.data['total']))


def _s_rt7(case: Case) -> None:
    '''TC14: without scope parameters the search is the 0.3.25 search plus drive_id; the total is the sum of the libraries (RT7, RT4).

    Args:
        case: the executed case.

    Returns:
        None.
    '''
    if not items_ok(case):
        return
    tree = case.tree
    filters = {k: v for k, v in case.params.items() if k in ('dates', 'name_part')}
    parts = [case.total(dict(filters, site_id=tree.site, drive_id=drive, recursive=True)) for drive in tree.libraries]
    if None in parts or sum(p or 0 for p in parts) != case.data['total']:
        case.bad('total %s differs from the sum %s of the per-library scoped totals' % (case.data['total'], parts))


def _u_scope(case: Case) -> None:
    '''TC13: a scoped suggestion names only rows of the search with the same scope (RT8), at most 10, no fragment.

    Args:
        case: the executed case.

    Returns:
        None.
    '''
    names = rev11._u_check(case, 10, case.params['text'])
    scope = {k: v for k, v in case.params.items() if k != 'text'}
    rows = {i.get('name') for i in (case.need('backup_search_files', dict(scope, name_part=case.params['text'], limit=500)) or {}).get('items', [])}
    if not names or any(name not in rows or '.dup-' in name for name in names):
        case.bad('suggestions %s are not names of the scoped search rows of %r, or there is none' % (names[:5], scope.get('dir')))


def _u_rt7(case: Case) -> None:
    '''TC13: without the scope parameters the suggestion is the 0.3.25 one: same rules, same names as an identical call, RF3.

    Args:
        case: the executed case.

    Returns:
        None.
    '''
    rev11._u_check(case, 10, case.params['text'])
    again = case.need('backup_suggest_names', case.params)
    if again is not None and again != case.data:
        case.bad('a repeated identical call returns another result')
    rev11._u_rf3(case)


VALIDATORS: dict[str, Callable[[Case], None]] = {
    's_scope_dir': _s_scope_dir, 's_scope_root': _s_scope_root, 's_scope_name': _s_scope_name, 's_scope_filter': _s_scope_filter,
    's_scope_dup': _s_scope_dup, 's_rt7': _s_rt7, 'u_scope': _u_scope, 'u_rt7': _u_rt7,
}
