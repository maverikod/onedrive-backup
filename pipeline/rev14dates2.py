'''Revision 14 validators of rows M3, M12, M14 and M19 (matrix TODO 10.22.2.5, 10.22.6.2-10.22.6.6, 10.22.9 TD9-TD12, TD14).

The newest snapshot of every library, the libraries and runs of a backup date and the snapshot identity are computed by the check
from backup_snapshots (tags site-/drive- and time), backup_sites_list and backup_libraries_list (pipeline.rev13.Tree). The literal
attribute values of TD9/TD10 are the expected backfill of 10.22.2.5 for the 15 snapshots of 2026-11-19..2026-11-24.
'''

from __future__ import annotations

from pipeline import rev11
from pipeline.rev13 import digest, local_day
from pipeline.rev14 import Case14, ErrorChecks, Validators, strip
from pipeline.rev14dates import TRIGGERS, _fields_scope, latest, time_local

BACKFILL_TRIGGERS = {'2026-11-19': ['unknown'], '2026-11-21': ['unknown'], '2026-11-22': ['unknown'], '2026-11-23': ['scheduled'],
                     '2026-11-24': ['scheduled']}
TD10_SHORT = '71b12dcb'
TD10 = {'date': '2026-11-21', 'time_local': '2026-11-21T15:08:33+02:00', 'backup_type': 'full', 'trigger': 'unknown',
        'run_id': 'legacy-20261121T124752Z', 'type_source': 'derived'}
SOURCES = ('tag', 'record', 'derived')


def _tag(snap: dict, prefix: str) -> str:
    '''Return the value of the tag site- or drive- of a snapshot.

    Args:
        snap: the backup_snapshots item.
        prefix: 'site-' or 'drive-'.

    Returns:
        The 64-hex key or ''.
    '''
    return next((str(tag)[len(prefix):] for tag in snap.get('tags', []) if str(tag).startswith(prefix)), '')


def _warned(case: Case14, code: str, field: str, value: str) -> bool:
    '''PRODUCT finding unless the first warning is {code, field, value, hint} (10.22.6.10).

    Args:
        case: the executed case.
        code: the warning code.
        field: the parameter.
        value: the offending value.

    Returns:
        True when the warning is present.
    '''
    warnings = case.data.get('warnings')
    if isinstance(warnings, list) and warnings and isinstance(warnings[0], dict) and {'code': code, 'field': field, 'value': value}.items() <= warnings[0].items():
        return True
    case.bad('warnings %r, expected [{code %s, field %s, value %r, hint}] (10.22.6.10)' % (warnings, code, field, value))
    return False


def _fo_attr(case: Case14) -> None:
    '''TD9: every dates[] item carries backup_types, triggers, run_count, library_count and last_snapshot_time of its snapshots.'''
    by_day: dict[str, list[dict]] = {}
    for snap in case.tree14.snapshots:
        by_day.setdefault(local_day(str(snap.get('time'))), []).append(snap)
    keys = ('backup_types', 'triggers', 'run_count', 'library_count', 'last_snapshot_time')
    for item in case.data.get('dates', []):
        day = str(item.get('date'))
        snaps = by_day.get(day, [])
        want = {'backup_types': ['full'], 'library_count': len({_tag(s, 'drive-') for s in snaps}),
                'last_snapshot_time': max((str(s.get('time')) for s in snaps), default=None)}
        got = {key: item.get(key) for key in keys}
        triggers = got['triggers'] if isinstance(got['triggers'], list) else None
        good = all(got[key] == value for key, value in want.items()) and isinstance(got['run_count'], int) and got['run_count'] >= 1
        good = good and triggers is not None and set(triggers) <= set(TRIGGERS) and (day not in BACKFILL_TRIGGERS or triggers == BACKFILL_TRIGGERS[day])
        if not good:
            case.bad('date %s: %s, expected %s, run_count >= 1 and triggers %s (10.22.6.4, backfill of 10.22.2.5)'
                     % (day, got, want, BACKFILL_TRIGGERS.get(day, 'within %s' % (TRIGGERS,))))
            return


def _fo_latest(case: Case14) -> None:
    '''TD9: latest == what dates_mode 'latest' selects and equals the date_scope of M13 {} (RD2).'''
    dates, count = latest(case.tree14)
    want = {'dates': dates, 'snapshot_count': count}
    if case.data.get('latest') != want:
        case.bad('latest %r, expected %s (10.22.6.4)' % (case.data.get('latest'), want))
        return
    scope = (case.need('backup_search_files', {'limit': 1}) or {}).get('date_scope') or {}
    if {'dates': scope.get('dates'), 'snapshot_count': scope.get('snapshot_count')} != want:
        case.bad('the date_scope %s of backup_search_files {} differs from latest (RD2)' % scope)


def _fo_unknown(case: Case14) -> None:
    '''TD14: the 10.19.5 C3 answer for an unknown site plus warnings [UNKNOWN_SITE_ID].'''
    rev11.VALIDATORS['fo_unknown'](rev11.Case(case.report, case.desc, strip('backup_filter_options', case.data), case.tree, case.params))
    if _warned(case, 'UNKNOWN_SITE_ID', 'site_ids', case.params['site_ids'][0]):
        known = case.need('backup_filter_options', {}) or {}
        if known.get('warnings') != []:
            case.bad('backup_filter_options {} gives warnings %r, expected []' % (known.get('warnings'),))


def _u_all(case: Case14) -> None:
    '''TD2: dates_mode 'all' gives the 0.3.27 suggestions of every snapshot (all dates) plus warnings (RD3).'''
    old = case.need('backup_suggest_names', {'text': case.params['text'], 'dates': case.tree14.days}) or {}
    if 'warnings' not in case.data or strip('backup_suggest_names', case.data) != old:
        case.bad('the answer minus warnings %s differs from the suggestions of all dates %s, or warnings is absent' % (str(case.data)[:120], str(old)[:120]))


def _u_rf3(case: Case14) -> None:
    '''TD12: under the default every suggestion is the name of a row of the default search (RF3, RD2); warnings [].'''
    rows = {i.get('name') for i in (case.need('backup_search_files', {'name_part': case.params['text'], 'limit': 500}) or {}).get('items', [])}
    names = [i.get('name') for i in case.data.get('items', [])]
    if not names or any(name not in rows for name in names):
        case.bad('suggestions %s are not names of the default search rows (RF3, RD2)' % names[:5])
    if case.data.get('warnings') != []:
        case.bad('warnings %r, expected [] (10.22.6.10: always present)' % (case.data.get('warnings', '<absent>'),))


def _u_warn(case: Case14) -> None:
    '''TD14: an unknown site gives no suggestion and warnings [UNKNOWN_SITE_ID].'''
    if case.data.get('items') != []:
        case.bad('expected no suggestion, got %s' % str(case.data.get('items'))[:100])
    _warned(case, 'UNKNOWN_SITE_ID', 'site_ids', case.params['site_ids'][0])


def _tree_keys(case: Case14) -> bool:
    '''PRODUCT finding unless the tree page carries date_scope and warnings (10.22.6.6).

    Args:
        case: the executed case.

    Returns:
        True when both are present.
    '''
    missing = [key for key in ('date_scope', 'warnings') if key not in case.data]
    if missing:
        case.bad('the result lacks %s (10.22.6.6)' % missing)
    return not missing


def _fc_latest(case: Case14) -> None:
    '''TD11: M19 {} under the default latest: the site file_count == the M13 total of the latest selection; date_scope; warnings [] (RD2).'''
    dates, count = latest(case.tree14)
    flat = case.total({'dates': dates})
    counted = sum(int(node.get('file_count', 0)) for node in case.data.get('nodes', []))
    if counted != flat:
        case.bad('the root file_count sum %s differs from the backup_search_files total %s of the newest snapshot of every library (dates %s, RD2)'
                 % (counted, flat, dates))
    if not _tree_keys(case):
        return
    want = {'mode': 'latest', 'dates': dates, 'snapshot_count': count}
    if case.data['date_scope'] != want or case.data['warnings'] != []:
        case.bad('date_scope %s / warnings %r, expected %s / []' % (case.data['date_scope'], case.data['warnings'], want))


def _fc_collapse(case: Case14) -> None:
    '''TD11: with dates_mode all and collapse version every folder file_count == the collapsed M13 total of its subtree (RD2, RD5).'''
    if not _tree_keys(case):
        return
    base = {'site_id': case.params['site_id'], 'drive_id': case.params['drive_id'], 'recursive': True, 'dates_mode': 'all', 'collapse': 'version'}
    for node in case.data.get('nodes', [])[:8]:
        total = case.total(dict(base, dir=node.get('dir')))
        if total != node.get('file_count'):
            case.bad('node %r: file_count %s, the collapsed search of its subtree totals %s (RD2)' % (node.get('name'), node.get('file_count'), total))
            return


def _fc_compat(case: Case14) -> None:
    '''TD11: dates_mode all with collapse none gives the 0.3.27 nodes of every snapshot (all dates) plus date_scope and warnings (RD3).'''
    if not _tree_keys(case):
        return
    old = case.need('backup_folder_children', {'dates': case.tree14.days}) or {}
    if strip('backup_folder_children', case.data) != old:
        case.bad('the nodes minus date_scope and warnings differ from those of all dates: %s vs %s' % (str(case.data.get('nodes'))[:120], str(old.get('nodes'))[:120]))


def _snap_attr(case: Case14) -> None:
    '''TD10: snapshot items carry the library identity, local date and time and the run attributes; no paths or hostname.'''
    items = case.data.get('items', [])
    if case.cid == 'td10_no_host_paths':
        carrying = sorted({key for item in items for key in ('paths', 'hostname') if key in item})
        if carrying:
            case.bad('items still carry %s (O-MD5 A: host paths and the container id leave the items)' % carrying)
        return
    tree = case.tree14
    site = tree.site or ''
    if [i.get('id') for i in items] != [s.get('id') for s in tree.snapshots][:len(items)] or not items:
        case.bad('the items are not the snapshots in the 0.3.27 order')
    for item in items:
        drive = next((d for d in tree.libraries if digest(d) == _tag(item, 'drive-')), '')
        want = {'site_id': site if digest(site) == _tag(item, 'site-') else '', 'site_name': tree.site_name, 'drive_id': drive,
                'library_name': tree.libraries.get(drive, ''), 'date': local_day(str(item.get('time'))),
                'time_local': time_local(str(item.get('time'))), 'backup_type': 'full'}
        if item.get('short_id') == TD10_SHORT:
            want.update(TD10)
        got = {key: item.get(key) for key in want}
        attrs = item.get('trigger') in TRIGGERS and bool(item.get('run_id')) and item.get('type_source') in SOURCES
        if got != want or not attrs:
            case.bad('snapshot %s: %s, expected %s with trigger, run_id and type_source (10.22.6.2, TD10)' % (item.get('short_id'), got, want))
            return
    if not any(item.get('short_id') == TD10_SHORT for item in items):
        case.report.state.append('%s: the snapshot %s of TD10 is not listed' % (case.desc, TD10_SHORT))


FO_VALIDATORS: Validators = {'fo_attr': _fo_attr, 'fo_latest': _fo_latest, 'fo_unknown': _fo_unknown}
SUGGEST_VALIDATORS: Validators = {'u_all': _u_all, 'u_rf3': _u_rf3, 'u_warn': _u_warn}
TREE_VALIDATORS: Validators = {'fc_latest': _fc_latest, 'fc_collapse': _fc_collapse, 'fc_compat': _fc_compat}
SNAP_VALIDATORS: Validators = {'snap_attr': _snap_attr}
SUGGEST_ERRORS: ErrorChecks = {'td12_scope_conflict': _fields_scope}
TREE_ERRORS: ErrorChecks = {'td3_m19_scope_conflict': _fields_scope}
NO_ERRORS: ErrorChecks = {}
