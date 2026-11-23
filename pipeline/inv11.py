'''Revision 11 assertions of matrix_inventory (matrix TODO 10.19, blocks FILTER-REV11 and UI-FILTER).

The matrix snapshot must carry the three new commands M12-M14, the file index row PL14, the client and odbcli rows, the SPA rows V9 and V10,
the relations RF1-RF6, the named checks of 10.19.9 and the reconciliation record of the user authorization.
'''

from __future__ import annotations

TAG = 'PLANNED(FILTER-REV11)'
UI_TAG = 'PLANNED(UI-FILTER)'
M12 = ('baseline', 'site_filter', 'unknown_site', 'unknown_param', 'site_ids_type', 'site_ids_item_type', 'site_id_bad_char',
       'site_ids_duplicate', 'writes_nothing')
M13 = ('baseline_dates', 'baseline_empty', 'name_case', 'name_glob_pdf', 'name_contains_pdf', 'two_dates_versions', 'paging_concat',
       'offset_beyond', 'writes_nothing', 'name_ctl', 'name_nine_stars', 'name_129', 'date_feb30', 'date_format', 'site_id_bad_char',
       'limit_0', 'limit_501', 'offset_neg', 'offset_1000001', 'unknown_param', 'site_ids_type', 'limit_type', 'name_part_type')
M14 = ('text_akt', 'text_glob', 'text_rf3', 'text_one_char', 'text_star', 'text_129', 'omit_text', 'unknown_param', 'text_type',
       'limit_0', 'limit_21', 'writes_nothing')
V9 = ('load_calls', 'site_tick_options_only', 'apply_one_search', 'name_wildcard_rows', 'three_columns_no_identifier',
      'row_download_inline_export', 'autocomplete_keyboard_and_logout')
V10 = ('service_tabs_lazy_and_poll', 'old_routes_notfound')
ROWS = {
    'M12': ('mcp', 'CURRENT', M12), 'M13': ('mcp', 'CURRENT', M13), 'M14': ('mcp', 'CURRENT', M14),
    'PL14': ('platform', TAG, ('catchup_all_snapshots_indexed',)),
    'C-K16': ('client', TAG, ()), 'C-K17': ('client', TAG, ()), 'C-K18': ('client', TAG, ()),
    'O17': ('odbcli', TAG, ()), 'O18': ('odbcli', TAG, ()), 'O19': ('odbcli', TAG, ()),
    'V9': ('vue', UI_TAG, V9), 'V10': ('vue', UI_TAG, V10),
}
CHECKS = {
    'cmd_backup_filter_options': 'M12', 'cmd_backup_search_files': 'M13', 'cmd_backup_suggest_names': 'M14',
    'file_index_coverage': 'PL14', 'client_cmd_backup_filter_options': 'C-K16', 'client_cmd_backup_search_files': 'C-K17',
    'client_cmd_backup_suggest_names': 'C-K18', 'odbcli_filter_options': 'O17', 'odbcli_search_files': 'O18',
    'odbcli_suggest_names': 'O19',
}
RELATIONS = ('RF1', 'RF2', 'RF3', 'RF4', 'RF5', 'RF6')
OPTIONS = tuple('O-%d' % number for number in range(1, 17))
EXTENDED = ('M13', 'M14')  # revision 13 (matrix TODO 10.21.7) appends cases to M13 and M14 and rows to their client/odbcli checks (pipeline/inv13.py)


def problems(data: dict, names: dict[str, dict]) -> list[str]:
    '''Return the violations of the revision 11 content of the matrix snapshot.

    Args:
        data: the loaded matrix.
        names: the check registry entries by name.

    Returns:
        The list of violation texts, empty when the snapshot carries revision 11.
    '''
    found: list[str] = []
    rows = {row.get('id'): row for row in data['rows']}
    for rid, (surface, tag, wanted) in ROWS.items():
        row = rows.get(rid)
        if row is None:
            found.append('rev11: row %s of matrix TODO 10.19 is absent' % rid)
            continue
        if row.get('surface') != surface or row.get('tag') != tag:
            found.append('rev11: row %s is %r/%r, expected %s/%s' % (rid, row.get('surface'), row.get('tag'), surface, tag))
        got = tuple(case.get('id') for case in row.get('cases', []))
        if (got[:len(wanted)] if rid in EXTENDED else got) != wanted:
            found.append('rev11: row %s cases %s differ from 10.19.9 %s' % (rid, got, wanted))
    for name, rid in CHECKS.items():
        entry = names.get(name) or {}
        if entry.get('rows', [])[:1] != [rid] or 'FILTER-REV11' not in entry.get('blocks', []):
            found.append('rev11: check %s is registered as %r, expected block FILTER-REV11 and rows [%s]' % (name, entry, rid))
    mapped = {check for rid in ('V9', 'V10') for check in (rows.get(rid) or {}).get('checks', [])}
    for name in ('vue_command_calls', 'vue_download', 'vue_static_serve', 'vue_auth', 'vue_command_contract', 'vue_build', 'vue_polling'):
        if name not in mapped:
            found.append('rev11: no row V9 or V10 maps the changed check %s' % name)
    relations = {rel.get('id') for rel in data['relations']}
    found += ['rev11: relation %s is absent (10.19.5)' % rel for rel in RELATIONS if rel not in relations]
    for column in ('site_ids', 'dates', 'name_part', 'text'):
        if column not in data['parameter_columns']:
            found.append('rev11: parameter column %s is absent' % column)
    record = data['identity'].get('reconciliations_10_19')
    if not isinstance(record, dict):
        found.append('rev11: identity.reconciliations_10_19 is absent')
    else:
        chosen = record.get('options')
        if not isinstance(chosen, dict) or tuple(chosen) != OPTIONS:
            found.append('rev11: identity.reconciliations_10_19.options must list %s' % (OPTIONS,))
        if 'approval' not in record or 'contract_gaps' not in record:
            found.append('rev11: identity.reconciliations_10_19 lacks approval or contract_gaps')
    return found
