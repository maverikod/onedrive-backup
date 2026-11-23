'''Revision 13 assertions of matrix_inventory (matrix TODO 10.21, blocks TREE-REV13 and UI-TREE).

The matrix snapshot must carry the new command M19 backup_folder_children with its cells and cases, the changed rows M13 and M14 (cells
site_id, drive_id, dir, recursive, the item field drive_id, the cases of 10.21.7), the client rows CK-TREE1..3, the odbcli rows OC-TREE1..3,
the platform row PL19 (index file_dir), the UI row V12, the changed text of V3, V4 and V9, the relations RT1-RT10, the result-contract cases
TC1-TC16, the named checks of 10.21.8 and the reconciliation record of the user authorization ("Delat po rekom.": every option O-T1..O-T12
takes its recommended value). The command list of pipeline.b4base holds 18 commands.
'''

from __future__ import annotations

from pipeline import b4base

TAG = 'PLANNED(TREE-REV13)'
UI_TAG = 'PLANNED(UI-TREE)'
API = 'TREE-REV13'
UI = 'UI-TREE'
COMMAND = 'backup_folder_children'
USER_WORDS = 'Делать по реком.'
BAD_DIR = ('double_slash', 'leading_slash', 'trailing_slash', 'dotdot', 'dot', 'control', '65_segments', '1025_chars', 'segment_256')
M19_HEAD = ('tc1_roots', 'tc2_libraries', 'tc3_folders_dengi', 'tc4_leaf_folder', 'tc5_name_pruned', 'tc5_name_nothing', 'tc6_paging_wide',
            'tc6_offset_beyond', 'tc12_dir_without_drive', 'tc12_drive_without_site', 'tc12_relation_first')
M19_TAIL = ('tc12_drive_id_bad', 'tc12_site_id_bad', 'tc12_date_feb30', 'tc12_limit_0', 'tc12_limit_501', 'tc12_offset_neg', 'tc12_offset_100001',
            'tc12_unknown_param', 'tc15_writes_nothing', 'tc16_latency')
M19 = M19_HEAD + tuple('tc12_dir_' + name for name in BAD_DIR) + M19_TAIL
M13 = ('tc7_folder_direct', 'tc7_folder_recursive_leaf', 'tc8_library_root', 'tc8_library_recursive', 'tc9_scope_and_name',
       'tc10_site_not_in_filter', 'tc10_two_dates_folder', 'tc11_duplicates', 'tc12_dir_without_drive', 'tc12_drive_without_site',
       'tc12_recursive_without_drive', 'tc12_relation_first', 'tc12_dir_dotdot', 'tc12_drive_id_bad', 'tc12_recursive_type',
       'tc14_rt7_empty', 'tc14_rt7_dates', 'tc14_rt7_name_pdf')
M14 = ('tc13_scope_suggest', 'tc13_rt7_no_scope', 'tc12_dir_without_drive', 'tc12_recursive_without_drive', 'tc12_recursive_type')
PL19 = ('index_file_dir_exists', 'snapshot_rows_unchanged', 'schedule_unchanged')
V12 = ('l16_three_regions', 'l17_toggle_site', 'l18_expand_library', 'l19_select_folder', 'l20_reload_restores', 'l21_and_name_filter',
       'l22_recursive_library', 'l23_keyboard', 'l24_tree_all_clears', 'l25_tree_more', 'l26_narrow_stack', 'l27_logout_zero_calls',
       'vitest_foldertree', 'vitest_treekeys', 'vitest_breadcrumb', 'vitest_filters_extended', 'stub_tree_error_banner',
       'stub_stale_tree_answer', 'stub_scope_kept_empty', 'stub_copy_marker_scoped')
ROWS = {
    'M19': ('mcp', TAG, M19), 'CK-TREE1': ('client', TAG, ()), 'CK-TREE2': ('client', TAG, ()), 'CK-TREE3': ('client', TAG, ()),
    'OC-TREE1': ('odbcli', TAG, ()), 'OC-TREE2': ('odbcli', TAG, ()), 'OC-TREE3': ('odbcli', TAG, ()), 'PL19': ('platform', TAG, PL19),
    'V12': ('vue', UI_TAG, V12),
}
APPENDED = {'M13': M13, 'M14': M14}
SCOPE = ('site_id', 'drive_id', 'dir', 'recursive')
M19_PARAMS = ('site_id', 'drive_id', 'dir', 'site_ids', 'dates', 'name_part', 'limit', 'offset')
NEW = {'cmd_backup_folder_children': (API, ['M19']), 'folder_index_live': (API, ['PL19']), 'vue_folder_tree': (UI, ['V12']),
       'client_folder_children': (API, ['CK-TREE1']), 'odbcli_folder_children': (API, ['OC-TREE1'])}
CHANGED = {'cmd_backup_search_files': (API, ['M13']), 'cmd_backup_suggest_names': (API, ['M14']), 'cmd_help': (API, ['M1']),
           'matrix_inventory': (API, ['PX8']), 'client_cmd_backup_search_files': (API, ['C-K17', 'CK-TREE2']),
           'client_cmd_backup_suggest_names': (API, ['C-K18', 'CK-TREE3']), 'odbcli_search_files': (API, ['O18', 'OC-TREE2']),
           'odbcli_suggest_names': (API, ['O19', 'OC-TREE3']), 'vue_command_contract': (UI, ['V3']), 'vue_command_calls': (UI, ['V4', 'V8']),
           'vue_build': (UI, ['V6'])}
ROW_CHECKS = {'M19': 'cmd_backup_folder_children', 'PL19': 'folder_index_live', 'CK-TREE1': 'client_folder_children',
              'CK-TREE2': 'client_cmd_backup_search_files', 'CK-TREE3': 'client_cmd_backup_suggest_names', 'OC-TREE1': 'odbcli_folder_children',
              'OC-TREE2': 'odbcli_search_files', 'OC-TREE3': 'odbcli_suggest_names'}
V12_CHECKS = ('vue_folder_tree', 'vue_command_calls', 'vue_command_contract', 'vue_build')
RELATIONS = {'RT1': {'M13', 'M14', 'M19'}, 'RT2': {'M13', 'M14'}, 'RT3': {'M13', 'M19'}, 'RT4': {'M19'}, 'RT5': {'M19'},
             'RT6': {'M13', 'M14', 'M19'}, 'RT7': {'M13', 'M14'}, 'RT8': {'M13', 'M14'}, 'RT9': {'M19'}, 'RT10': {'M13', 'M19'}}
CONTRACTS = tuple('TC%d' % number for number in range(1, 17))
OPTIONS = tuple('O-T%d' % number for number in range(1, 13))
COLUMNS = ('site_id', 'drive_id', 'dir', 'recursive')
RECORD_KEYS = ('approval', 'user_words', 'date', 'options', 'interface', 'contract_gaps', 'changed_text')


def _row_problems(rows: dict[str, dict]) -> list[str]:
    '''Return the violations of the rows of 10.21.5.

    Args:
        rows: the matrix rows by id.

    Returns:
        The list of violation texts.
    '''
    found: list[str] = []
    for rid, (surface, tag, wanted) in ROWS.items():
        row = rows.get(rid)
        if row is None:
            found.append('rev13: row %s of matrix TODO 10.21.5 is absent' % rid)
            continue
        if row.get('surface') != surface or row.get('tag') != tag:
            found.append('rev13: row %s is %r/%r, expected %s/%s' % (rid, row.get('surface'), row.get('tag'), surface, tag))
        got = tuple(case.get('id') for case in row.get('cases', []))
        if got != wanted:
            found.append('rev13: row %s cases %s differ from 10.21.6/10.21.7 %s' % (rid, got, wanted))
        if rid in ROW_CHECKS and ROW_CHECKS[rid] not in row.get('checks', []):
            found.append('rev13: row %s does not name the check %s' % (rid, ROW_CHECKS[rid]))
    m19 = rows.get('M19') or {}
    if m19.get('command') != COMMAND or tuple(m19.get('params', {})) != M19_PARAMS:
        found.append('rev13: row M19 must name %s with the cells %s, it has %r %s' % (COMMAND, M19_PARAMS, m19.get('command'), tuple(m19.get('params', {}))))
    if 'file_dir' not in str((rows.get('PL19') or {}).get('name')):
        found.append('rev13: row PL19 does not name the index file_dir')
    found += ['rev13: row V12 maps no check %s' % name for name in V12_CHECKS if name not in (rows.get('V12') or {}).get('checks', [])]
    for rid, wanted in APPENDED.items():
        row = rows.get(rid) or {}
        got = tuple(case.get('id') for case in row.get('cases', []))
        if row.get('tag') != 'CURRENT' or got[-len(wanted):] != wanted:
            found.append('rev13: row %s must stay CURRENT and end with the cases %s, it has %r %s' % (rid, wanted, row.get('tag'), got))
        found += ['rev13: row %s lacks the cell %s (10.21.4)' % (rid, name) for name in SCOPE if name not in row.get('params', {})]
    for rid in ('V3', 'V4', 'V9'):
        if '10.21' not in str((rows.get(rid) or {}).get('name')):
            found.append('rev13: the text of row %s does not carry its 10.21 change' % rid)
    return found


def _contract_problems(data: dict) -> list[str]:
    '''Return the violations of the relations RT1-RT10, the cases TC1-TC16 and the item field drive_id.

    Args:
        data: the loaded matrix.

    Returns:
        The list of violation texts.
    '''
    found: list[str] = []
    relations = {rel.get('id'): rel for rel in data['relations']}
    for rel, wanted in RELATIONS.items():
        got = set(str((relations.get(rel) or {}).get('rows', '')).split(','))
        if got != wanted:
            found.append('rev13: relation %s is keyed by %s, expected %s (10.21.5)' % (rel, sorted(got), sorted(wanted)))
    labels: set[str] = set()
    for rid in ('M13', 'M14', 'M19'):
        for entry in data['result_contracts'].get(rid, {}).get('cases', {}).values():
            labels |= {str(text).split(':')[0] for text in entry.get('assert', [])}
    found += ['rev13: no result contract of M13, M14 or M19 asserts %s (10.21.7)' % tc for tc in CONTRACTS if tc not in labels]
    if 'drive_id' not in str(data['result_contracts'].get('M13', {}).get('baseline', {}).get('result')):
        found.append('rev13: the M13 baseline result contract does not name the item field drive_id (10.21.4)')
    found += ['rev13: parameter column %s is absent' % column for column in COLUMNS if column not in data['parameter_columns']]
    return found


def _registry_problems(names: dict[str, dict]) -> list[str]:
    '''Return the violations of the named checks of 10.21.8.

    Args:
        names: the check registry entries by name.

    Returns:
        The list of violation texts.
    '''
    found: list[str] = []
    for table, statuses in ((NEW, ('pending', 'implemented')), (CHANGED, ('implemented',))):
        for name, (block, rids) in table.items():
            entry = names.get(name) or {}
            if entry.get('rows') != rids or block not in entry.get('blocks', []) or entry.get('status') not in statuses:
                found.append('rev13: check %s is registered as %r, expected block %s, rows %s and status %s' % (name, entry, block, rids, '|'.join(statuses)))
    return found


def _record_problems(identity: dict) -> list[str]:
    '''Return the violations of identity.reconciliations_10_21.

    Args:
        identity: the identity block of the matrix.

    Returns:
        The list of violation texts.
    '''
    record = identity.get('reconciliations_10_21')
    if not isinstance(record, dict):
        return ['rev13: identity.reconciliations_10_21 is absent']
    found = ['rev13: identity.reconciliations_10_21 lacks %s' % key for key in RECORD_KEYS if key not in record]
    chosen = record.get('options')
    if not isinstance(chosen, dict) or tuple(chosen) != OPTIONS or any(not str(value).startswith('A ') for value in chosen.values()):
        found.append('rev13: identity.reconciliations_10_21.options must list %s, each with its RECOMMENDED value (A)' % (OPTIONS,))
    if record.get('user_words') != USER_WORDS or record.get('date') != '2026-11-23':
        found.append('rev13: identity.reconciliations_10_21 must quote the user words of 2026-11-23 verbatim')
    return found


def problems(data: dict, names: dict[str, dict]) -> list[str]:
    '''Return the violations of the revision 13 content of the matrix snapshot.

    Args:
        data: the loaded matrix.
        names: the check registry entries by name.

    Returns:
        The list of violation texts, empty when the snapshot carries revision 13.
    '''
    rows = {row.get('id'): row for row in data['rows']}
    found = _row_problems(rows) + _contract_problems(data) + _registry_problems(names) + _record_problems(data['identity'])
    if len(b4base.COMMANDS) != 18 or COMMAND not in b4base.COMMANDS:
        found.append('rev13: pipeline.b4base.COMMANDS holds %d commands, expected the 17 of revision 12 and %s (18)' % (len(b4base.COMMANDS), COMMAND))
    return found
