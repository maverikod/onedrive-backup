'''Revision 12 assertions of matrix_inventory (matrix TODO 10.20, block SCHEDULE-REV12).

The matrix snapshot must carry the three commands M15-M17 with their cases, the client and odbcli rows, the platform rows PL15-PL18, the
UI row V11, the retired PL13, the relations RS1-RS12, E1-E8, RG1 and RG2, the named checks of 10.20.10 and the reconciliation record of the
user authorization ("Delat po rekom.": every option O-S1..O-S15 takes its recommended value). The live command list of pipeline.b4base
holds 17 commands.
'''

from __future__ import annotations

from pipeline import b4base

TAG = 'CURRENT'
BLOCK = 'SCHEDULE-REV12'
BAD = ('range', 'fields', 'extra', 'step0', 'freq', 'never', 'macro', 'tz', 'jit61', 'jitnounit', 'catch200', 'enabled', 'twotz', 'foo', 'entries21',
       'nul', 'ctl', 'surrogate', 'long257', 'lines201', 'twobad')
M15 = ('baseline', 'next_count_0', 'next_count_20', 'next_count_21', 'next_count_neg', 'next_count_type', 'unknown_param', 'writes_nothing')
M16 = ('dry_valid', 'warn_empty', 'warn_domdow', 'warn_dup', 'full_16384', 'too_large', 'conflict', 'conflict_dry', 'actor_space', 'revision_bad',
       'omit_text', 'text_type', 'dry_run_type', 'next_count_21', 'unknown_param') + tuple('bad_' + name for name in BAD)
M17 = ('baseline', 'history_0', 'history_50', 'history_51', 'history_type', 'unknown_param', 'writes_nothing')
PK = ('pk1_upgrade_active', 'pk2_upgrade_paused', 'pk3_fresh_install', 'pk4_remove', 'pk5_only_when_absent', 'pk6_migration_record')
ST = ('st1_bootstrap', 'st2_modes_and_history', 'st3_replace_fails', 'st4_concurrent_sets', 'st5_history_50', 'st6_corrupt_at_start', 'st7_corrupt_held',
      'st8_deleted_file', 'st9_hand_edit')
EN = tuple('en%02d' % number for number in range(1, 21))
RR = ('rr1_records_and_trigger', 'rr2_end_line_in_finally', 'rr3_unwritable_file', 'rr4_dry_run_marked', 'rr5_concurrent_appends')
V11 = ('l10_open', 'l11_check_is_dry_run', 'l12_invalid_text', 'l13_poll', 'l14_save', 'l15_conflict', 'vitest_groups')
ROWS = {
    'M15': ('mcp', M15), 'M16': ('mcp', M16), 'M17': ('mcp', M17), 'CK-SCH1': ('client', None), 'CK-SCH2': ('client', None), 'CK-SCH3': ('client', None),
    'OC-SCH1': ('odbcli', None), 'OC-SCH2': ('odbcli', None), 'OC-SCH3': ('odbcli', None), 'PL15': ('platform', PK), 'PL16': ('platform', ST),
    'PL17': ('platform', EN), 'PL18': ('platform', RR), 'V11': ('vue', V11),
}
CHECKS = {
    'cmd_backup_schedule_get': ['M15'], 'cmd_backup_schedule_set': ['M16'], 'cmd_backup_schedule_status': ['M17'],
    'client_cmd_backup_schedule_get': ['CK-SCH1'], 'client_cmd_backup_schedule_set': ['CK-SCH2'], 'client_cmd_backup_schedule_status': ['CK-SCH3'],
    'odbcli_schedule_get': ['OC-SCH1'], 'odbcli_schedule_set': ['OC-SCH2'], 'odbcli_schedule_status': ['OC-SCH3'], 'schedule_file': ['PL16'],
    'schedule_engine': ['PL17'], 'run_records': ['PL18'], 'timer_retired': ['PL15'], 'schedule_host_timer': ['PL15'],
    'schedule_live': ['M15', 'M16', 'M17'], 'vue_schedule': ['V11'],
}
RELATIONS = tuple('RS%d' % number for number in range(1, 13)) + tuple('E%d' % number for number in range(1, 9)) + ('RG1', 'RG2')
OPTIONS = ('O-S1', 'O-S2', 'O-S3', 'O-S4', 'O-S5', 'O-S5b', 'O-S6a', 'O-S6b', 'O-S7', 'O-S8', 'O-S9', 'O-S10', 'O-S11', 'O-S12', 'O-S13', 'O-S14', 'O-S15')
COLUMNS = ('text', 'expected_revision', 'dry_run', 'next_count', 'actor', 'history_limit')
SCHEDULE_COMMANDS = ('backup_schedule_get', 'backup_schedule_set', 'backup_schedule_status')


def problems(data: dict, names: dict[str, dict]) -> list[str]:
    '''Return the violations of the revision 12 content of the matrix snapshot.

    Args:
        data: the loaded matrix.
        names: the check registry entries by name.

    Returns:
        The list of violation texts, empty when the snapshot carries revision 12.
    '''
    found: list[str] = []
    rows = {row.get('id'): row for row in data['rows']}
    for rid, (surface, wanted) in ROWS.items():
        row = rows.get(rid)
        if row is None:
            found.append('rev12: row %s of matrix TODO 10.20 is absent' % rid)
            continue
        if row.get('surface') != surface or row.get('tag') != TAG:
            found.append('rev12: row %s is %r/%r, expected %s/%s' % (rid, row.get('surface'), row.get('tag'), surface, TAG))
        got = tuple(case.get('id') for case in row.get('cases', []))
        if wanted is not None and got != wanted:
            found.append('rev12: row %s cases %s differ from 10.20 %s' % (rid, got, wanted))
    for rid, command in zip(('M15', 'M16', 'M17'), SCHEDULE_COMMANDS):
        if (rows.get(rid) or {}).get('command') != command:
            found.append('rev12: row %s must name the command %s' % (rid, command))
    old = rows.get('PL13') or {}
    if old.get('tag') != 'RETIRED(%s)' % BLOCK or 'timer_retired' not in old.get('checks', []):
        found.append('rev12: row PL13 is %r with the checks %s, expected RETIRED(%s) naming timer_retired' % (old.get('tag'), old.get('checks'), BLOCK))
    for name, rids in CHECKS.items():
        entry = names.get(name) or {}
        if entry.get('rows') != rids or BLOCK not in entry.get('blocks', []) or entry.get('status') != 'implemented':
            found.append('rev12: check %s is registered as %r, expected implemented, block %s and rows %s' % (name, entry, BLOCK, rids))
    old_check = names.get('timer_state_preserved') or {}
    if old_check.get('status') != 'deprecated' or old_check.get('replaced_by') != 'timer_retired':
        found.append('rev12: timer_state_preserved must be deprecated and replaced_by timer_retired, it is %r' % old_check)
    mapped = {check for check in (rows.get('V11') or {}).get('checks', [])}
    for name in ('vue_command_calls', 'vue_command_contract', 'vue_static_serve', 'vue_build', 'vue_polling', 'vue_schedule'):
        if name not in mapped:
            found.append('rev12: row V11 maps no changed check %s' % name)
    relations = {rel.get('id') for rel in data['relations']}
    found += ['rev12: relation %s is absent (10.20.3, 10.20.5, 10.20.10)' % rel for rel in RELATIONS if rel not in relations]
    found += ['rev12: parameter column %s is absent' % column for column in COLUMNS if column not in data['parameter_columns']]
    record = data['identity'].get('reconciliations_10_20')
    if not isinstance(record, dict):
        found.append('rev12: identity.reconciliations_10_20 is absent')
    else:
        chosen = record.get('options')
        if not isinstance(chosen, dict) or tuple(chosen) != OPTIONS or any(not str(value).startswith('A ') for value in (chosen or {}).values()):
            found.append('rev12: identity.reconciliations_10_20.options must list %s, each with its RECOMMENDED value (A)' % (OPTIONS,))
        for key in ('approval', 'user_words', 'date', 'interface', 'contract_gaps', 'changed_text'):
            if key not in record:
                found.append('rev12: identity.reconciliations_10_20 lacks %s' % key)
    if len(b4base.COMMANDS) != 18 or any(command not in b4base.COMMANDS for command in SCHEDULE_COMMANDS):
        found.append('rev12: pipeline.b4base.COMMANDS holds %d commands %s, expected the 14 of revision 11, the three schedule commands and backup_folder_children of revision 13 (18)' % (len(b4base.COMMANDS), sorted(set(SCHEDULE_COMMANDS) - set(b4base.COMMANDS))))
    return found
