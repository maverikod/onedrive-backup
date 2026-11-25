'''Revision 14 group A assertions of matrix_inventory (matrix TODO 10.22 groups DOCS, BYTES, DATES and 10.23.R RUN-REASON, RUN-CLASS).

The user chose every recommended option on 2026-11-25 ("Всё по реком. (реком.)", TODOs f6af3091 and 9bf67676). The snapshot must carry
the new commands M21 backup_download_chunk and M24 backup_run_log, the changed rows M1-M6, M12-M14, M17 and M19 with their new cells and
cases, the client rows CK-BYTE1/2, CK-DATE1-3, CK-RUN1/2, the odbcli rows OC-BYTE1/2, OC-DATE1-3, OC-RUN1/2, the platform rows PL20 (snapshot
attributes), PL22 (file id resolver) and PL25 (run classification), the task-121 row renamed PL20r (10.23.8 (6)), the relations RD1-RD8,
RM1-RM4, RM6-RM8 and RR1-RR8, the result contracts TD1-TD17, TM1-TM12, TM14, TR1-TR3, TR5, the named checks of 10.22.10 and 10.23.R.7 of this
group and the reconciliation records of the user's choice. Group B (M20, M22, PL21), the UI rows and RUN-RETRY (PL26, O-RD4 A) are absent.
The command list of pipeline.b4base holds 20 commands.
'''

from __future__ import annotations

from pipeline import b4base

MODEL = 'MODEL-REV14'
DATES = 'DATES-REV14'
REASON = 'RUN-REASON'
CLASS = 'RUN-CLASS'
USER_WORDS = 'Всё по реком. (реком.)'
DATE = '2026-11-25'
NEW_COMMANDS = ('backup_download_chunk', 'backup_run_log')
M21 = ('baseline', 'tm4_reassembly', 'tm4_eof_at_total', 'tm4_offset_beyond', 'tm4_limit_max', 'tm4_limit_over', 'tm4_limit_0',
       'tm4_export_id_value', 'tm4_unknown_export', 'omit_export_id', 'unknown_param', 'tm4_writes_nothing', 'tm5_too_large', 'tm12_latency',
       'tm14_model_recipe')
M24 = ('baseline_tail', 'tr5_slices_reassemble', 'tr5_tail_last_bytes', 'rr3_tail_with_offset', 'tr5_unknown_run_id', 'tr5_run_without_log',
       'rr4_limit_65537', 'rr4_limit_0', 'rr4_offset_beyond', 'rr4_run_id_upper', 'rr4_run_id_35', 'omit_run_id', 'unknown_param',
       'rr8_writes_nothing')
PL20 = ('td13_columns', 'td13_backfill_values', 'td13_rows_unchanged', 'td13_schedule_unchanged', 'td16_tags_builder', 'td16_trigger_manual',
        'td16_trigger_unknown', 'td16_reader_keys', 'td17_new_run_tagged')
PL22 = ('tm7_resolve_form_a', 'tm7_resolve_form_c', 'tm12_resolver_bound')
PL25 = ('tr3_guard_refused', 'tr3_discovery_errors', 'tr3_rclone_exit5', 'tr3_restic_exit1', 'tr3_mirror_oserror', 'tr3_unexpected',
        'tr3_second_library_attempted', 'tr3_secret_scrubbed')
ROWS = {
    'M21': ('mcp', MODEL, M21), 'M24': ('mcp', REASON, M24), 'PL20': ('platform', DATES, PL20), 'PL22': ('platform', MODEL, PL22),
    'PL25': ('platform', CLASS, PL25), 'CK-BYTE1': ('client', MODEL, ()), 'CK-BYTE2': ('client', MODEL, ()), 'CK-DATE1': ('client', DATES, ()),
    'CK-DATE2': ('client', DATES, ()), 'CK-DATE3': ('client', DATES, ()), 'CK-RUN1': ('client', REASON, ()), 'CK-RUN2': ('client', REASON, ()),
    'OC-BYTE1': ('odbcli', MODEL, ()), 'OC-BYTE2': ('odbcli', MODEL, ()), 'OC-DATE1': ('odbcli', DATES, ()), 'OC-DATE2': ('odbcli', DATES, ()),
    'OC-DATE3': ('odbcli', DATES, ()), 'OC-RUN1': ('odbcli', REASON, ()), 'OC-RUN2': ('odbcli', REASON, ()),
}
APPENDED = {
    'M1': (MODEL, ('tm9_help_lists_20', 'tm9_start_here', 'tm9_prepare_examples', 'tm9_dates_text', 'tm9_schedule_set_dry_run',
                   'tm10_sites_list_display_name', 'tm10_documented_keys')),
    'M2': (MODEL, ('tm9_info_toc', 'tm9_recipes_page', 'tm9_pages_kept', 'tr_info_run_recipe')),
    'M3': (DATES, ('td10_library_identity', 'td10_no_host_paths')),
    'M4': (MODEL, ('tm8_file_ids', 'td14_unknown_snapshot_warning')),
    'M5': (MODEL, ('tm1_form_a', 'tm1_form_b', 'tm1_form_c', 'tm1_archive', 'tm2_inline_small', 'tm2_inline_large', 'tm2_inline_65537',
                   'tm2_inline_neg', 'tm2_inline_type', 'tm2_inline_no_address', 'tm3_file_id_bad', 'tm3_file_id_with_snapshot',
                   'tm3_snapshot_alone_mixed', 'tm3_file_id_with_path', 'tm3_form_c_no_name', 'tm3_name_dotdot', 'tm3_unknown_file_id',
                   'tm3_path_without_prefix', 'tm3_copy_index_neg', 'tm6_hint_not_found', 'tm6_form_c_checked', 'tm11_writes_nothing',
                   'tm12_latency')),
    'M6': (MODEL, ('rm8_kind_file', 'rm8_kind_snapshot')),
    'M12': (DATES, ('td9_date_attributes', 'td9_latest', 'td14_unknown_site_warning')),
    'M13': (DATES, ('td1_default_latest', 'td1_unknown_site', 'td2_all_compat', 'td3_scope_conflict_latest', 'td3_scope_conflict_all',
                    'td3_dates_mode_value', 'td3_dates_mode_type', 'td3_collapse_value', 'td3_collapse_upper', 'td3_order_by_value',
                    'td3_fields_type', 'td3_fields_empty', 'td3_fields_duplicate', 'td3_fields_unknown', 'td3_fields_31',
                    'td3_unknown_latest_only', 'td4_collapse_version', 'td5_collapse_file', 'td5_one_date_equal', 'td6_order_snapshot_time',
                    'td6_order_mtime', 'td6_order_size', 'td6_order_name', 'td6_paging', 'td7_fields_three', 'td7_fields_all',
                    'td8_added_keys', 'td14_unknown_site_warning', 'td14_no_snapshot_for_date', 'td15_date_detail', 'td15_feb30_detail',
                    'td15_site_ids_index', 'tm7_file_id', 'tm12_latency')),
    'M14': (DATES, ('td2_suggest_all', 'td12_suggest_rf3', 'td12_scope_conflict', 'td14_suggest_warnings')),
    'M17': (REASON, ('tr1_last_run_keys', 'tr1_history_keys', 'tr1_current_run_keys', 'tr2_last_run_diagnosable')),
    'M19': (DATES, ('td11_default_latest', 'td11_all_version', 'td11_all_none_compat', 'td3_m19_scope_conflict', 'td3_m19_collapse_value')),
}
CELLS = {
    'M5': ('file_id', 'site_id', 'drive_id', 'dir', 'name', 'copy_index', 'inline_max_bytes'), 'M13': ('dates_mode', 'collapse', 'order_by', 'fields'),
    'M14': ('dates_mode',), 'M19': ('dates_mode', 'collapse'), 'M21': ('export_id', 'offset', 'limit'), 'M24': ('run_id', 'offset', 'limit', 'tail'),
}
COLUMNS = ('collapse', 'copy_index', 'dates_mode', 'fields', 'file_id', 'inline_max_bytes', 'name', 'order_by', 'run_id', 'tail')
NEW = {
    'cmd_backup_download_chunk': (MODEL, ['M21']), 'client_download_chunk': (MODEL, ['CK-BYTE2']), 'odbcli_chunk': (MODEL, ['OC-BYTE2']),
    'help_text_contract': (MODEL, ['M1', 'M2']), 'model_recipe': (MODEL, ['M21', 'PL22']), 'index_attributes_live': (DATES, ['PL20']),
    'unit_backup_tags': (DATES, ['PL20']), 'snapshot_tags_live': (DATES, ['PL20']), 'cmd_backup_run_log': (REASON, ['M24']),
    'client_run_log': (REASON, ['CK-RUN2']), 'odbcli_run_log': (REASON, ['OC-RUN2']), 'last_run_diagnosable': (REASON, ['M17']),
    'run_classification': (CLASS, ['PL25']),
}
ROW_CHECKS = {
    'M1': 'cmd_help', 'M2': 'cmd_info', 'M3': 'cmd_backup_snapshots', 'M4': 'cmd_backup_list_files', 'M5': 'cmd_backup_prepare_download',
    'M6': 'cmd_backup_download_status', 'M12': 'cmd_backup_filter_options', 'M13': 'cmd_backup_search_files', 'M14': 'cmd_backup_suggest_names',
    'M17': 'cmd_backup_schedule_status', 'M19': 'cmd_backup_folder_children', 'CK-BYTE1': 'client_cmd_backup_prepare_download',
    'CK-DATE1': 'client_cmd_backup_search_files', 'CK-DATE2': 'client_cmd_backup_suggest_names', 'CK-DATE3': 'client_folder_children',
    'CK-RUN1': 'client_cmd_backup_schedule_status', 'OC-BYTE1': 'odbcli_prepare', 'OC-DATE1': 'odbcli_search_files',
    'OC-DATE2': 'odbcli_suggest_names', 'OC-DATE3': 'odbcli_folder_children', 'OC-RUN1': 'odbcli_schedule_status',
}
RELATIONS = {
    'RD1': 'M13,M14,M19', 'RD2': 'M12,M13,M14,M19', 'RD3': 'M13,M14,M19', 'RD4': 'M13', 'RD5': 'M13,M19', 'RD6': 'PL20,M3,M12,M13',
    'RD7': 'PL20,M3,M12,M13,M14,M19', 'RD8': 'M13', 'RM1': 'M5', 'RM2': 'M4,M5,M13', 'RM3': 'M4,M5,M13', 'RM4': 'M5',
    'RM6': 'M5,M12,M13,M14,M19,M21', 'RM7': 'M3,M4,M5,M6,M12,M13,M14,M17,M19', 'RM8': 'M5,M6,M21', 'RR1': 'M17', 'RR2': 'M17,M24',
    'RR3': 'M24', 'RR4': 'M24', 'RR5': 'M17,PL25', 'RR6': 'M24,PL25', 'RR7': 'M17', 'RR8': 'M17,M24',
}
CONTRACTS = tuple('TD%d' % n for n in range(1, 18)) + tuple('TM%d' % n for n in range(1, 13)) + ('TM14', 'TR1', 'TR2', 'TR3', 'TR5')
ABSENT_ROWS = ('M20', 'M22', 'PL21', 'PL26', 'V13', 'V14', 'V16')
OPTIONS_10_22 = {'O-DT1': 'A ', 'O-DT2': 'A ', 'O-DT3': 'A ', 'O-DT4': 'T2 ', 'O-DT5': 'A ', 'O-PV1': 'A+ ', 'O-PV2': 'A ', 'O-PV3': 'A ',
                 'O-PV4': 'A ', 'O-MD1': 'A ', 'O-MD2': 'A ', 'O-MD3': 'A ', 'O-MD4': 'A ', 'O-MD5': 'A '}
OPTIONS_10_23R = {'O-RD1': 'A ', 'O-RD2': 'B ', 'O-RD3': 'B ', 'O-RD4': 'A '}
RECORD_KEYS = ('approval', 'user_words', 'date', 'todo', 'options', 'interface', 'contract_gaps', 'changed_text')
ALIAS = {'10.18.12a': 'HAND-OFF AND RENAME RULE', '10.18.12b': 'APPROVAL 2026-11-20'}
DATES_DEFAULT = {
    'M13': ['baseline_empty', 'name_case', 'name_glob_pdf', 'name_contains_pdf', 'writes_nothing', 'tc10_site_not_in_filter', 'tc14_rt7_empty',
            'tc14_rt7_name_pdf'],
    'M14': ['text_akt', 'text_glob', 'text_rf3', 'writes_nothing', 'tc13_scope_suggest', 'tc13_rt7_no_scope'],
    'M19': ['tc1_roots', 'tc2_libraries', 'tc5_name_nothing', 'tc6_paging_wide', 'tc6_offset_beyond', 'tc15_writes_nothing', 'tc16_latency'],
}


def _cases(row: dict) -> tuple:
    '''Return the case ids of one row in order.

    Args:
        row: one matrix row.

    Returns:
        The tuple of case ids.
    '''
    return tuple(case.get('id') for case in row.get('cases', []))


def _row_problems(rows: dict[str, dict]) -> list[str]:
    '''Return the violations of the new and changed rows of group A.

    Args:
        rows: the matrix rows by id.

    Returns:
        The list of violation texts.
    '''
    found: list[str] = []
    for rid, (surface, block, wanted) in ROWS.items():
        row = rows.get(rid)
        if row is None:
            found.append('rev14: row %s of matrix TODO 10.22/10.23.R is absent' % rid)
            continue
        if row.get('surface') != surface or row.get('tag') != 'PLANNED(%s)' % block:
            found.append('rev14: row %s is %r/%r, expected %s/PLANNED(%s)' % (rid, row.get('surface'), row.get('tag'), surface, block))
        if _cases(row) != wanted:
            found.append('rev14: row %s cases %s differ from 10.22.9/10.23.R.6 %s' % (rid, _cases(row), wanted))
    for rid, command in zip(('M21', 'M24'), NEW_COMMANDS):
        if (rows.get(rid) or {}).get('command') != command:
            found.append('rev14: row %s must name the command %s' % (rid, command))
    for rid, (block, wanted) in APPENDED.items():
        row = rows.get(rid) or {}
        got = _cases(row)
        if row.get('tag') != 'CURRENT' or got[-len(wanted):] != wanted:
            found.append('rev14: row %s must stay CURRENT and end with the cases %s, it has %r %s' % (rid, wanted, row.get('tag'), got))
        if block not in row.get('check_blocks', []):
            found.append('rev14: row %s does not carry the check block %s' % (rid, block))
    for rid, names in CELLS.items():
        params = (rows.get(rid) or {}).get('params', {})
        found += ['rev14: row %s lacks the cell %s (10.22.8, 10.23.R.5)' % (rid, name) for name in names if name not in params]
    if ((rows.get('M5') or {}).get('params', {}).get('snapshot_id') or {}).get('required') is not False:
        found.append('rev14: M5 snapshot_id must be conditionally required (required false, RM1)')
    for rid, name in ROW_CHECKS.items():
        if name not in (rows.get(rid) or {}).get('checks', []):
            found.append('rev14: row %s does not name the check %s' % (rid, name))
    for name, (block, rids) in NEW.items():
        found += ['rev14: row %s does not name the check %s' % (rid, name) for rid in rids if name not in (rows.get(rid) or {}).get('checks', [])]
    old = rows.get('PL20r') or {}
    if old.get('tag') != 'CURRENT' or 'run_log' not in old.get('checks', []):
        found.append('rev14: the run-log row of task 121 must be renamed PL20r (10.23.8 (6)), CURRENT with the check run_log')
    if 'snapshot attributes' not in str((rows.get('PL20') or {}).get('name')):
        found.append('rev14: row PL20 must be the snapshot attributes row of 10.22.8 (DATES)')
    found += ['rev14: row %s belongs to a later group and must not be materialized now' % rid for rid in ABSENT_ROWS if rid in rows]
    return found


def _contract_problems(data: dict) -> list[str]:
    '''Return the violations of the relations, the result-contract labels and the parameter columns of group A.

    Args:
        data: the loaded matrix.

    Returns:
        The list of violation texts.
    '''
    found: list[str] = []
    relations = {rel.get('id'): rel for rel in data['relations']}
    for rel, rows in RELATIONS.items():
        if (relations.get(rel) or {}).get('rows') != rows:
            found.append('rev14: relation %s is keyed by %r, expected %s' % (rel, (relations.get(rel) or {}).get('rows'), rows))
    labels: set[str] = set()
    for contract in data['result_contracts'].values():
        for entry in contract.get('cases', {}).values():
            labels |= {str(text).split(':')[0] for text in entry.get('assert', [])}
    found += ['rev14: no result contract asserts %s (10.22.9, 10.23.R.6)' % label for label in CONTRACTS if label not in labels]
    found += ['rev14: parameter column %s is absent' % column for column in COLUMNS if column not in data['parameter_columns']]
    return found


def _registry_problems(names: dict[str, dict]) -> list[str]:
    '''Return the violations of the named checks of 10.22.10 and 10.23.R.7 of group A.

    Args:
        names: the check registry entries by name.

    Returns:
        The list of violation texts.
    '''
    found: list[str] = []
    for name, (block, rids) in NEW.items():
        entry = names.get(name) or {}
        if entry.get('rows') != rids or block not in entry.get('blocks', []) or entry.get('status') not in ('pending', 'implemented'):
            found.append('rev14: check %s is registered as %r, expected block %s, rows %s and status pending|implemented' % (name, entry, block, rids))
    for name in sorted(set(ROW_CHECKS.values())):
        if (names.get(name) or {}).get('status') != 'implemented':
            found.append('rev14: the changed check %s must stay implemented' % name)
    if (names.get('run_log') or {}).get('rows') != ['PL20r']:
        found.append('rev14: check run_log must map the renamed row PL20r')
    return found


def _options_problems(record: object, key: str, options: dict[str, str]) -> list[str]:
    '''Return the violations of one reconciliation record of the user's choice.

    Args:
        record: the record found in the identity block.
        key: the identity key of the record.
        options: the option ids with the prefix of their recommended value.

    Returns:
        The list of violation texts.
    '''
    if not isinstance(record, dict):
        return ['rev14: identity.%s is absent' % key]
    found = ['rev14: identity.%s lacks %s' % (key, name) for name in RECORD_KEYS if name not in record]
    chosen = record.get('options')
    if (not isinstance(chosen, dict) or tuple(chosen) != tuple(options)
            or any(not str(chosen[option]).startswith(prefix) for option, prefix in options.items())):
        found.append('rev14: identity.%s.options must list %s, each with its RECOMMENDED value' % (key, tuple(options)))
    if record.get('user_words') != USER_WORDS or record.get('date') != DATE:
        found.append('rev14: identity.%s must quote the user words of %s verbatim' % (key, DATE))
    return found


def _record_problems(identity: dict) -> list[str]:
    '''Return the violations of identity.reconciliations_10_22 and identity.reconciliations_10_23R.

    Args:
        identity: the identity block of the matrix.

    Returns:
        The list of violation texts.
    '''
    record = identity.get('reconciliations_10_22')
    found = _options_problems(record, 'reconciliations_10_22', OPTIONS_10_22)
    found += _options_problems(identity.get('reconciliations_10_23R'), 'reconciliations_10_23R', OPTIONS_10_23R)
    if isinstance(record, dict):
        if record.get('alias_10_18_12') != ALIAS:
            found.append('rev14: reconciliations_10_22.alias_10_18_12 must be %r (10.22.0, TODO efacea94)' % ALIAS)
        if (record.get('rev14_dates_default') or {}).get('cases') != DATES_DEFAULT:
            found.append('rev14: reconciliations_10_22.rev14_dates_default.cases must list the success cases without dates %r (10.22.10)' % DATES_DEFAULT)
    return found


def problems(data: dict, names: dict[str, dict]) -> list[str]:
    '''Return the violations of the revision 14 group A content of the matrix snapshot.

    Args:
        data: the loaded matrix.
        names: the check registry entries by name.

    Returns:
        The list of violation texts, empty when the snapshot carries revision 14 group A.
    '''
    rows = {row.get('id'): row for row in data['rows']}
    found = _row_problems(rows) + _contract_problems(data) + _registry_problems(names) + _record_problems(data['identity'])
    if len(b4base.COMMANDS) != 20 or tuple(b4base.COMMANDS[18:]) != NEW_COMMANDS:
        found.append('rev14: pipeline.b4base.COMMANDS holds %d commands, expected the 18 of revision 13 and %s (20)' % (len(b4base.COMMANDS), NEW_COMMANDS))
    return found
