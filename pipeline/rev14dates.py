'''Revision 14 validators of row M13 backup_search_files (matrix TODO 10.22.2, 10.22.6.5, 10.22.9 TD1-TD8, TD14, TD15, TM7, TM12).

Expected values are relations computed by the check from the live state (pipeline.rev14.Tree14): the newest snapshot of every
library from backup_snapshots, single-date totals, the collapse 'none' view read completely, the time zone of the answer. No total
is a literal. Every validator receives a successful reply; the 0.3.28 service answers the new parameters -32602 unknown before.
'''

from __future__ import annotations

import re
from datetime import datetime
from typing import Any
from zoneinfo import ZoneInfo

from pipeline import rev11
from pipeline.rev13 import local_day
from pipeline.rev14 import SEARCH_ADDED, Case14, ErrorChecks, Reply, Tree14, Validators, edata, file_id, strip

TOP = ('items', 'total', 'offset', 'limit', 'timezone', 'index', 'date_scope', 'warnings')
FILE_ID = re.compile('[0-9a-f]{8}[.][0-9a-f]{24}')
TRIGGERS = ('scheduled', 'manual', 'unknown')
BOUND_SEARCH = 3.0


def latest(tree: Tree14) -> tuple[list[str], int]:
    '''Return the local dates of the newest snapshot of every library and the number of libraries (O-DT1 A, RD2).

    Args:
        tree: the revision 14 state.

    Returns:
        (ascending distinct dates, library count).
    '''
    newest: dict[str, str] = {}
    for snap in tree.snapshots:
        drive = next((tag for tag in snap.get('tags', []) if str(tag).startswith('drive-')), '')
        if drive and str(snap.get('time', '')) > newest.get(drive, ''):
            newest[drive] = str(snap.get('time', ''))
    return sorted({local_day(stamp) for stamp in newest.values()}), len(newest)


def time_local(stamp: str) -> str:
    '''Return snapshot_time_local of 10.22.2.4: the UTC instant in the service zone, ISO with offset, seconds precision.

    Args:
        stamp: the UTC time ending with Z.

    Returns:
        The local ISO time.
    '''
    return datetime.fromisoformat(stamp.replace('Z', '+00:00')).astimezone(ZoneInfo(rev11.TZ)).isoformat(timespec='seconds')


def shape(case: Case14, items: bool = True) -> bool:
    '''PRODUCT finding unless the page carries date_scope, warnings and every added item key (10.22.6.5).

    Args:
        case: the executed case.
        items: whether the item keys are judged (not with `fields`).

    Returns:
        True when the shape is right.
    '''
    missing = [key for key in TOP if key not in case.data]
    lacking = sorted({key for item in case.data.get('items', []) for key in SEARCH_ADDED if key not in item}) if items else []
    if missing or lacking:
        case.bad('the result lacks %s and the items lack %s (10.22.6.5: date_scope and warnings always present, item keys of 10.22.2.4)'
                 % (missing, lacking))
        return False
    return True


def pages(case: Case14, params: dict) -> list[dict] | None:
    '''Read every row of a search with the given parameters, paged by 500.

    Args:
        case: the executed case.
        params: the search parameters without limit and offset.

    Returns:
        The rows, or None after a finding.
    '''
    rows: list[dict] = []
    total = 1
    while len(rows) < total:
        data = case.need('backup_search_files', dict(params, limit=500, offset=len(rows)))
        if data is None:
            return None
        total = int(data.get('total', 0))
        rows += data.get('items', [])
        if not data.get('items'):
            break
    return rows


def _s_latest(case: Case14) -> None:
    '''TD1: no date = the newest snapshot of every library; date_scope names it; total == the search of those dates (RD2).'''
    dates, count = latest(case.tree14)
    total = case.total({'dates': dates})
    if case.data.get('total') != total:
        case.bad('total %s, expected the total %s of the newest snapshot of each of the %d libraries (dates %s, O-DT1 A)'
                 % (case.data.get('total'), total, count, dates))
    if not shape(case):
        return
    if case.data['date_scope'] != {'mode': 'latest', 'dates': dates, 'snapshot_count': count}:
        case.bad('date_scope %s, expected %s' % (case.data['date_scope'], {'mode': 'latest', 'dates': dates, 'snapshot_count': count}))
    if any(item['snapshot_date'] not in dates for item in case.data['items']):
        case.bad('a row has a snapshot_date outside %s' % dates)


def _s_empty(case: Case14) -> None:
    '''TD1: a well-formed unknown site gives total 0, items [] and date_scope.snapshot_count 0.'''
    if (case.data.get('total'), case.data.get('items')) != (0, []):
        case.bad('expected total 0 and items [], got total %s' % case.data.get('total'))
    if shape(case) and case.data['date_scope'].get('snapshot_count') != 0:
        case.bad('date_scope %s, expected snapshot_count 0' % case.data['date_scope'])


def _s_all(case: Case14) -> None:
    '''TD2: dates_mode 'all' = every indexed snapshot: the sum of the single-date totals, the 0.3.27 rows plus the added keys (RD3).'''
    tree = case.tree14
    total = sum(case.total({'dates': [day]}) or 0 for day in tree.days)
    if case.data.get('total') != total:
        case.bad('total %s, expected the sum %s of the single-date totals of %s' % (case.data.get('total'), total, tree.days))
    if not shape(case):
        return
    indexed = ((case.need('backup_filter_options', {}) or {}).get('index') or {}).get('snapshots_indexed')
    scope = case.data['date_scope']
    if scope.get('mode') != 'all' or scope.get('snapshot_count') != indexed or scope.get('dates') != tree.days:
        case.bad('date_scope %s, expected mode all, dates %s and snapshot_count %s (index.snapshots_indexed)' % (scope, tree.days, indexed))
    old = case.need('backup_search_files', {'dates': tree.days, 'limit': 5}) or {}
    if strip('backup_search_files', case.data)['items'] != old.get('items'):
        case.bad('the first 5 rows minus the added keys differ from the rows of all dates (RD3)')


def _s_collapse(case: Case14) -> None:
    '''TD4, TD5: collapse version/file against the collapse 'none' view read completely (RD5).'''
    params = {k: v for k, v in case.params.items() if k not in ('collapse', 'limit', 'offset')}
    none = pages(case, params)
    rows = pages(case, dict(params, collapse=case.params['collapse']))
    if none is None or rows is None or not shape(case):
        return
    versions = {(r['dir'], r['name'], r['copy_index'], r['size'], r['mtime']) for r in none}
    files = {(r['dir'], r['name'], r['copy_index']) for r in none}
    total = case.data['total']
    if 'dates' in case.params:
        for mode in ('version', 'file'):
            other = case.total(dict(params, collapse=mode))
            if other != len(none):
                case.bad('one date: collapse %s total %s differs from the none total %d (RD5)' % (mode, other, len(none)))
        return
    if case.params['collapse'] == 'version':
        if total != len(versions) or sum(r['snapshot_count'] for r in rows) != len(none):
            case.bad('total %s vs %d distinct versions; sum of snapshot_count %s vs the none total %d (RD5)'
                     % (total, len(versions), sum(r['snapshot_count'] for r in rows), len(none)))
        dates = len({r['snapshot_date'] for r in none})
        if any(not (r['first_date'] <= r['last_date'] and 1 <= r['snapshot_count'] <= len(none)) for r in rows) or dates < 1:
            case.bad('a row breaks first_date <= last_date or 1 <= snapshot_count')
        newest: dict[tuple, str] = {}
        for r in none:
            group = (r['dir'], r['name'], r['copy_index'], r['size'], r['mtime'])
            newest[group] = max(newest.get(group, ''), r['snapshot_time'])
        if any(newest.get((r['dir'], r['name'], r['copy_index'], r['size'], r['mtime'])) != r['snapshot_time'] for r in rows):
            case.bad('a row does not show the newest snapshot of its version (10.22.2.2)')
        return
    counts: dict[tuple, set] = {}
    for r in none:
        counts.setdefault((r['dir'], r['name'], r['copy_index']), set()).add((r['size'], r['mtime']))
    if total != len(files) or total > len(versions):
        case.bad('total %s vs %d distinct files (<= %d versions, RD5)' % (total, len(files), len(versions)))
    wrong = [r['name'] for r in rows if r['version_count'] != len(counts.get((r['dir'], r['name'], r['copy_index']), ()))]
    if wrong:
        case.bad('version_count differs from the distinct (size, mtime) of the none view for %s' % wrong[:3])


ORDER_KEY = {'snapshot_time': 'snapshot_time', 'mtime': 'mtime', 'size': 'size'}


def _order(rows: list[dict], key: str) -> bool:
    '''Return True when rows are non-increasing in key with ties ascending by name key, then dir (RD8).

    Args:
        rows: the items.
        key: snapshot_time, mtime or size.

    Returns:
        Whether the order holds.
    '''
    keys: list[tuple[Any, str, str]] = [(item.get(key), rev11.key(str(item.get('name'))), str(item.get('dir'))) for item in rows]
    return all(a[0] > b[0] or (a[0] == b[0] and a[1:] <= b[1:]) for a, b in zip(keys, keys[1:]))


def _s_order(case: Case14) -> None:
    '''TD6: order_by gives the fixed direction per key with the tie-break of 10.22.2.4; 'name' equals the default order.'''
    if not shape(case):
        return
    by = case.params['order_by']
    if by == 'name':
        default = case.need('backup_search_files', {k: v for k, v in case.params.items() if k != 'order_by'}) or {}
        if case.data['items'] != default.get('items'):
            case.bad("order_by 'name' differs from the default order")
    elif not _order(case.data['items'], ORDER_KEY[by]):
        case.bad('the rows are not non-increasing in %s with ties by name key, then dir (RD8)' % by)


def _s_paging(case: Case14) -> None:
    '''TD6: offset 50 continues the order of offset 0 without repeat or gap (RF5).'''
    if not shape(case):
        return
    whole = case.need('backup_search_files', dict(case.params, offset=0, limit=100)) or {}
    if case.data['items'] != whole.get('items', [])[50:100]:
        case.bad('the page at offset 50 is not rows 50..99 of one page of 100 (RF5, RD8)')


def _s_fields(case: Case14) -> None:
    '''TD7: fields gives exactly the requested keys; every key equals the default item.'''
    if not shape(case, items=False):
        return
    wanted = sorted(case.params['fields'])
    if any(sorted(item) != wanted for item in case.data['items']) or not case.data['items']:
        case.bad('items do not carry exactly the keys %s' % wanted)
    if len(wanted) > 3:
        default = case.need('backup_search_files', {k: v for k, v in case.params.items() if k != 'fields'}) or {}
        if case.data['items'] != default.get('items'):
            case.bad('fields with every key differs from the default items')


def _s_keys(case: Case14) -> None:
    '''TD8: the added keys of one live row: ext, local time and date (RD4), type, trigger and run id of M3, counts of collapse none.'''
    if not shape(case) or not case.data['items']:
        return
    item = case.data['items'][0]
    name = str(item['name'])
    ext = name.rsplit('.', 1)[1].lower() if '.' in name.lstrip('.') else ''
    snap: dict = next((s for s in case.tree14.snapshots if s.get('id') == item['snapshot_id']), {})
    want = {'ext': ext, 'snapshot_time_local': time_local(item['snapshot_time']), 'snapshot_date': local_day(item['snapshot_time']),
            'backup_type': 'full', 'trigger': snap.get('trigger'), 'run_id': snap.get('run_id'), 'snapshot_count': 1,
            'first_date': local_day(item['snapshot_time']), 'last_date': local_day(item['snapshot_time']), 'version_count': 1}
    got = {key: item.get(key) for key in want}
    if got != want or item['trigger'] not in TRIGGERS or not item['run_id']:
        case.bad('added keys %s, expected %s (trigger and run_id of backup_snapshots)' % (got, want))


def _s_warn(case: Case14) -> None:
    '''TD14: an unknown well-formed site or a date without snapshot is an empty success with one warning naming it.'''
    field = 'site_ids' if 'site_ids' in case.params else 'dates'
    code = 'UNKNOWN_SITE_ID' if field == 'site_ids' else 'NO_SNAPSHOT_FOR_DATE'
    value = case.params[field][0]
    if (case.data.get('total'), case.data.get('items')) != (0, []):
        case.bad('expected total 0 and items [], got total %s' % case.data.get('total'))
    warnings = case.data.get('warnings')
    if not (isinstance(warnings, list) and warnings and all(isinstance(w, dict) for w in warnings)
            and {'code': code, 'field': field, 'value': value}.items() <= warnings[0].items()):
        case.bad('warnings %r, expected [{code %s, field %s, value %r, hint}] (10.22.6.10)' % (warnings, code, field, value))
        return
    known = case.need('backup_search_files', {'dates': [case.tree14.days[-1]], 'limit': 1}) if case.tree14.days else None
    if known is not None and known.get('warnings') != []:
        case.bad('a call with a known date gives warnings %r, expected []' % (known.get('warnings'),))


def _s_fileid(case: Case14) -> None:
    '''TM7: file_id of every row is the RM3 hash of (snapshot_id, file_path); a second call gives equal ids.'''
    if not shape(case):
        return
    wrong = [i['name'] for i in case.data['items'] if not FILE_ID.fullmatch(str(i['file_id'])) or i['file_id'] != file_id(i['snapshot_id'], i['file_path'])]
    if wrong or not case.data['items']:
        case.bad('file_id differs from <snapshot 8 hex>.<sha256(snapshot_id LF file_path)[:24]> for %s' % wrong[:3])
    again = case.need('backup_search_files', case.params) or {}
    if [i.get('file_id') for i in again.get('items', [])] != [i['file_id'] for i in case.data['items']]:
        case.bad('a second identical call gives other file ids')


def _latency(case: Case14) -> None:
    '''TM12: M13 {} (the default latest) answers within 3 s.'''
    spent = case.tree14.seconds
    case.report.info.append('TM12 latency: backup_search_files {} %.2fs' % spent)
    if spent > BOUND_SEARCH:
        case.bad('answered in %.2f s, bound %.1f s (TM12)' % (spent, BOUND_SEARCH))


def _fields_scope(reply: Reply, tree: Tree14) -> str:
    '''RD1: INVALID_DATE_SCOPE names both fields.'''
    data = edata(reply)
    return '' if sorted(data.get('fields') or []) == ['dates', 'dates_mode'] else 'error.data %s lacks fields [dates, dates_mode] (RD1)' % str(data)[:120]


def _allowed(reply: Reply, tree: Tree14) -> str:
    '''TD3: INVALID_FIELDS lists the allowed keys, file_id among them.'''
    data = edata(reply)
    return '' if 'file_id' in (data.get('allowed') or []) else 'error.data %s lacks allowed listing file_id (TD3)' % str(data)[:120]


def _detail(field: str, value: str, expected: Any) -> Any:
    '''Return the RM6 predicate of a 400 with error.data {field, index 0, value, expected, hint}.

    Args:
        field: the parameter.
        value: the offending item.
        expected: the expected text, or None when any is accepted.

    Returns:
        The predicate.
    '''
    def check(reply: Reply, tree: Tree14) -> str:
        '''Judge error.data against RM6.

        Args:
            reply: the classified error reply.
            tree: the revision 14 state.

        Returns:
            '' or the finding.
        '''
        data = edata(reply)
        good = data.get('field') == field and data.get('index') == 0 and data.get('value') == value and bool(data.get('hint'))
        good = good and (expected is None or data.get('expected') == expected)
        return '' if good else 'error.data %s, expected {field %s, index 0, value %r, expected %r, hint} (RM6, TD15)' % (str(data)[:160], field, value, expected)
    return check


VALIDATORS: Validators = {
    's_latest': _s_latest, 's_empty': _s_empty, 's_all': _s_all, 's_collapse': _s_collapse, 's_order': _s_order, 's_paging': _s_paging,
    's_fields': _s_fields, 's_keys': _s_keys, 's_warn': _s_warn, 's_fileid': _s_fileid, 'latency': _latency,
}
ERRORS: ErrorChecks = {
    'td3_scope_conflict_latest': _fields_scope, 'td3_scope_conflict_all': _fields_scope, 'td3_fields_duplicate': _allowed,
    'td3_fields_unknown': _allowed, 'td15_date_detail': _detail('dates', '23.11.2026', 'YYYY-MM-DD'),
    'td15_feb30_detail': _detail('dates', '2026-02-30', None), 'td15_site_ids_index': _detail('site_ids', 'a b', None),
}
