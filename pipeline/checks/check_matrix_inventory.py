'''matrix_inventory: every matrix row has named checks and every named check is registered.

Mode: source-static. The pipeline cannot reach the deployed service, so the CURRENT command and
route rows are compared with the registration code in src/onedrive_api/server.py. The comparison
with the live help and OpenAPI surface belongs to the planned live checks (cmd_*, surface_*).
A pending check is a stub that always FAILS; this check proves that it fails and never passes.

Tags: CURRENT, PLANNED(block) and RETIRED(block). A RETIRED row (capability removed by an approved decision delivered by that
block) must be ABSENT from the registration code, must name a registered implemented check that asserts the absence, and is
excluded from the CURRENT comparison; a RETIRED row found registered is RED. Every CURRENT mcp row carries its command class.
'''

from __future__ import annotations

import ast
import re
from collections import Counter
from pathlib import Path

from pipeline import checks, matrix
from pipeline.checks import CheckFailure

ROOT = Path(__file__).resolve().parents[2]
SURFACES = ('mcp', 'rest', 'framework', 'client', 'cli', 'odbcli', 'ui', 'vue', 'auth', 'platform',
            'version', 'pipeline')
BLOCKS = ('B1', 'B2', 'B3', 'B4', 'UI-VUE', 'B-SPLIT', 'FIRST-RUN', 'BACKUP-EMPTY', 'RCLONE-ACCESS', 'DATA-ARCHIVE-REV9', 'TRANSPORT-REV8', 'TIMER-PRESERVE', 'UI-ROUTES',
          'DUP-KEEP-REV10')
TAG = re.compile(r'^(CURRENT|(PLANNED|RETIRED)[(](B1|B2|B3|B4|UI-VUE|FIRST-RUN|BACKUP-EMPTY|RCLONE-ACCESS|DATA-ARCHIVE-REV9|TRANSPORT-REV8|TIMER-PRESERVE|UI-ROUTES|DUP-KEEP-REV10)[)])$')
STATUSES = ('legacy', 'implemented', 'pending', 'deprecated')
ROW_KEYS = ('id', 'surface', 'name', 'tag', 'source', 'checks')
PARAM_KEYS = ('types', 'required', 'default', 'constraints', 'valid', 'invalid')
TOP_KEYS = ('identity', 'parameter_columns', 'rows', 'relations', 'result_contracts', 'checks',
            'expected_counts')
NAME_LINE = re.compile(r'^[ ]+name = .([a-z_]+).$', re.M)
ROUTE = re.compile(r'@app[.](get|post|delete)[(].(/api/v1[^)]*).[)]')
REV10 = 'DUP-KEEP-REV10'
REV10_CASES = {
    'BE2': ('no_collision', 'pair_same_name_group', 'pair_case_or_nfc_group', 'three_member_group', 'primary_by_hash',
            'primary_by_smallest_id_tie', 'reserved_name_in_source', 'scan_failure', 'duplicate_directory_unsupported'),
    'BE3': ('extra_stored_and_snapshotted', 'name_stable_across_runs', 'name_clash_extends_hex', 'rerun_no_refetch',
            'sync_does_not_delete_stored_copy', 'integrity_hash_mismatch_kept_and_error', 'hash_unavailable_size_checked',
            'fetch_failure_no_file_and_error', 'dry_run_writes_nothing', 'source_object_never_written'),
    'BE4': ('both_objects_listed', 'prepare_download_of_copy', 'plain_name_unchanged'),
}
REV10_CHECKS = {'backup_duplicate_names': ['BE2', 'BE3'], 'duplicate_collision_probe': ['BE2'], 'duplicate_copies_in_snapshot': ['BE4']}
REV10_RELATIONS = ('R32', 'R33', 'R34', 'R35', 'R36')


def _source_problems(data: dict, problems: list[str]) -> None:
    '''Compare the CURRENT and RETIRED rows with the registration code of src/onedrive_api/server.py.

    Args:
        data: the loaded matrix.
        problems: the list the violations are appended to.

    Returns:
        None.
    '''
    server = (ROOT / 'src/onedrive_api/server.py').read_text(encoding='utf-8')
    tree = ast.parse(server)
    registered: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.For) and isinstance(node.iter, ast.Tuple):
            names = [item.id for item in node.iter.elts if isinstance(item, ast.Name)]
            if names and len(names) == len(node.iter.elts):
                registered |= set(names)
    rows = [row for row in data['rows'] if row['tag'] == 'CURRENT']
    for row in rows:
        if row['surface'] == 'mcp' and not row.get('class'):
            problems.append('source: CURRENT mcp row %s carries no registered command class' % row['id'])
    classes = {row['class'] for row in rows if row['surface'] == 'mcp' and row.get('class')}
    if classes != registered:
        problems.append('source: registered command classes %s differ from CURRENT mcp rows %s'
                        % (sorted(registered), sorted(classes)))
    declared = {row['command'] for row in rows if row['surface'] == 'mcp'}
    in_server = set(NAME_LINE.findall(server))
    missing = in_server - declared
    if missing:
        problems.append('source: server.py defines commands without a CURRENT mcp row: %s' % sorted(missing))
    routes = {(verb.upper(), path) for verb, path in ROUTE.findall(server)}
    rest = {(row['method'], row['path']) for row in rows if row['surface'] == 'rest'}
    if routes != rest:
        problems.append('source: server.py REST routes %s differ from CURRENT rest rows %s'
                        % (sorted(routes), sorted(rest)))
    status = {entry.get('name'): entry.get('status') for entry in data['checks']}
    for row in (item for item in data['rows'] if str(item.get('tag')).startswith('RETIRED(')):
        if (row.get('method'), row.get('path')) in routes:
            problems.append('source: RETIRED row %s (%s %s) is still registered in server.py' % (row['id'], row.get('method'), row.get('path')))
        if row.get('surface') == 'mcp' and (row.get('command') in in_server or row.get('class') in registered):
            problems.append('source: RETIRED row %s command %s is still registered in server.py' % (row['id'], row.get('command')))
        if not any(status.get(name) == 'implemented' for name in row.get('checks', [])):
            problems.append('row %s: RETIRED but names no implemented check that asserts the absence' % row['id'])


def _row_problems(data: dict, names: dict[str, dict], problems: list[str]) -> Counter:
    '''Check every row, its parameter cells, relations, cases and result contracts, and count the rows per surface and tag.

    Args:
        data: the loaded matrix.
        names: the check registry entries by name.
        problems: the list the violations are appended to.

    Returns:
        The row counts keyed by surface and CURRENT, PLANNED or RETIRED.
    '''
    columns = set(data['parameter_columns'])
    rels = {rel['id'] for rel in data['relations']}
    contracts = data['result_contracts']
    ids: set[str] = set()
    counts: Counter = Counter()
    used: set[str] = set()
    for row in data['rows']:
        rid = row.get('id', '?')
        for key in ROW_KEYS:
            if key not in row:
                problems.append('row %s: missing key %s' % (rid, key))
        if rid in ids:
            problems.append('row %s: duplicate id' % rid)
        ids.add(rid)
        if row.get('surface') not in SURFACES:
            problems.append('row %s: unknown surface %r' % (rid, row.get('surface')))
        if not TAG.match(str(row.get('tag'))):
            problems.append('row %s: tag %r is not CURRENT, PLANNED(block) or RETIRED(block)' % (rid, row.get('tag')))
        kind = str(row.get('tag', '')).split('(')[0]
        counts['%s/%s' % (row.get('surface'), kind if kind in ('CURRENT', 'RETIRED') else 'PLANNED')] += 1
        if not row.get('checks'):
            problems.append('row %s: no named check' % rid)
        for name in row.get('checks', []):
            used.add(name)
            if name not in names:
                problems.append('row %s: check %s is not registered in the matrix check registry' % (rid, name))
        params = row.get('params', {})
        for pname, spec in params.items():
            if pname not in columns:
                problems.append('row %s: parameter %s is not a matrix column' % (rid, pname))
            for key in PARAM_KEYS:
                if key not in spec:
                    problems.append('row %s: parameter %s lacks field %s' % (rid, pname, key))
        for rel in row.get('relations', []):
            if rel not in rels:
                problems.append('row %s: unknown relation %s' % (rid, rel))
        contract = contracts.get(rid)
        if not isinstance(contract, dict) or not contract.get('baseline'):
            problems.append('row %s: no baseline result contract' % rid)
            continue
        for case in row.get('cases', []):
            entry = contract.get('cases', {}).get(case['id'])
            if not entry or entry.get('outcome') not in ('success', 'error') or not entry.get('assert'):
                problems.append('row %s: case %s has no complete result contract' % (rid, case['id']))
        extra = set(contract.get('cases', {})) - {case['id'] for case in row.get('cases', [])}
        if extra:
            problems.append('row %s: contract for unknown cases %s' % (rid, sorted(extra)))
    for rid in sorted(set(contracts) - ids):
        problems.append('result_contracts: entry %s has no row' % rid)
    for name in sorted(set(names) - used):
        problems.append('check %s is registered but no row maps to it' % name)
    for column in sorted(columns - {p for row in data['rows'] for p in row.get('params', {})}):
        problems.append('parameter column %s is used by no row' % column)
    return counts


def _registry_problems(data: dict, problems: list[str]) -> dict[str, dict]:
    '''Check the check registry against the check files, the legacy functions and the pending stubs.

    Args:
        data: the loaded matrix.
        problems: the list the violations are appended to.

    Returns:
        The registry entries by check name.
    '''
    names: dict[str, dict] = {}
    legacy = {node.name for node in ast.parse((ROOT / 'pipeline/__main__.py').read_text()).body
              if isinstance(node, ast.FunctionDef)}
    for entry in data['checks']:
        name = entry.get('name', '?')
        if name in names:
            problems.append('check %s: duplicate registry entry' % name)
        names[name] = entry
        status = entry.get('status')
        if status not in STATUSES:
            problems.append('check %s: status %r is not one of %s' % (name, status, STATUSES))
        blocks = entry.get('blocks')
        if not blocks or any(item not in BLOCKS for item in blocks):
            problems.append('check %s: blocks %r must be a non-empty subset of %s' % (name, blocks, BLOCKS))
        has_file = (ROOT / 'pipeline/checks' / ('check_%s.py' % name)).is_file()
        if status == 'legacy' and name not in legacy:
            problems.append('check %s: legacy but pipeline/__main__.py defines no such function' % name)
        if status == 'implemented' and not has_file:
            problems.append('check %s: implemented but pipeline/checks/check_%s.py is missing' % (name, name))
        if status == 'pending' and has_file:
            problems.append('check %s: has a check file but is still registered as pending' % name)
        if status == 'deprecated':
            target = entry.get('replaced_by')
            if has_file or name in checks.all_names():
                problems.append('check %s: deprecated but still served by the pipeline' % name)
            if not target or target == name:
                problems.append('check %s: deprecated without a replaced_by check' % name)
        if status == 'pending':
            if name not in checks.pending_entries():
                problems.append('check %s: pending but not served by the pipeline as a failing stub' % name)
            else:
                try:
                    checks.run(name)
                except CheckFailure:
                    pass
                else:
                    problems.append('check %s: the pending stub PASSED; a stub must always fail' % name)
    for name, entry in names.items():
        if entry.get('status') == 'deprecated' and names.get(str(entry.get('replaced_by')), {}).get('status') in (None, 'deprecated'):
            problems.append('check %s: replaced_by %s is not a live registered check' % (name, entry.get('replaced_by')))
    for name in checks.discover():
        if name not in names:
            problems.append('pipeline/checks/check_%s.py is not registered in the matrix' % name)
    return names


def _rev10_problems(data: dict, names: dict[str, dict], problems: list[str]) -> None:
    '''Check that the matrix carries revision 10 (matrix TODO 10.17.8 to 10.17.11, block DUP-KEEP-REV10).

    Args:
        data: the loaded matrix.
        names: the check registry entries by name.
        problems: the list the violations are appended to.

    Returns:
        None.
    '''
    rows = {row.get('id'): row for row in data['rows']}
    for rid, wanted in REV10_CASES.items():
        row = rows.get(rid)
        if row is None:
            problems.append('rev10: row %s of matrix TODO 10.17.8 is absent' % rid)
            continue
        if row.get('surface') != 'platform' or row.get('tag') != 'PLANNED(%s)' % REV10:
            problems.append('rev10: row %s is %r/%r, expected platform/PLANNED(%s)' % (rid, row.get('surface'), row.get('tag'), REV10))
        got = tuple(case.get('id') for case in row.get('cases', []))
        if got != wanted:
            problems.append('rev10: row %s cases %s differ from 10.17.10 and 10.17.11 %s' % (rid, got, wanted))
    be1 = rows.get('BE1') or {}
    if 'mixed_run_with_duplicate_incomplete' not in [case.get('id') for case in be1.get('cases', [])]:
        problems.append('rev10: row BE1 lacks the case mixed_run_with_duplicate_incomplete (10.17.11 (3))')
    baseline = str(data['result_contracts'].get('BE1', {}).get('baseline'))
    for word in ('duplicates', 'duplicate_summary', 'duplicate_incomplete'):
        if word not in baseline:
            problems.append('rev10: the BE1 baseline result contract does not name %s (10.17.6)' % word)
    relations = {rel.get('id') for rel in data['relations']}
    for rel in REV10_RELATIONS:
        if rel not in relations:
            problems.append('rev10: relation %s is absent (10.17.9, numbered R32-R36 in the snapshot)' % rel)
    for name, wanted_rows in REV10_CHECKS.items():
        entry = names.get(name) or {}
        if REV10 not in entry.get('blocks', []) or entry.get('rows') != wanted_rows:
            problems.append('rev10: check %s is registered as %r, expected block %s and rows %s' % (name, entry, REV10, wanted_rows))
    if REV10 not in (names.get('backup_empty_library') or {}).get('blocks', []):
        problems.append('rev10: backup_empty_library is not registered under block %s' % REV10)
    if 'reconciliations_10_17' not in data['identity']:
        problems.append('rev10: identity.reconciliations_10_17 is absent')


def run() -> None:
    '''Raise CheckFailure when the matrix rows, registry, counts, source or revision 10 content do not match.

    Returns:
        None.
    '''
    try:
        data = matrix.load()
    except (OSError, ValueError) as exc:
        raise CheckFailure('pipeline/matrix.yaml cannot be loaded: %s' % exc)
    absent = [key for key in TOP_KEYS if key not in data]
    if absent:
        raise CheckFailure('pipeline/matrix.yaml: missing top-level keys %s' % absent)
    problems: list[str] = []
    names = _registry_problems(data, problems)
    counts = _row_problems(data, names, problems)
    if dict(counts) != data['expected_counts']:
        problems.append('row counts %s differ from the counts recorded from the matrix TODO %s'
                        % (dict(sorted(counts.items())), data['expected_counts']))
    _source_problems(data, problems)
    _rev10_problems(data, names, problems)
    if problems:
        raise CheckFailure('%d violation(s):\n  - %s' % (len(problems), '\n  - '.join(problems)))
    print('[INFO] rows %d, checks %d (%s)' % (len(data['rows']), len(names),
          ', '.join('%s %d' % (s, sum(1 for e in names.values() if e['status'] == s)) for s in STATUSES)))
