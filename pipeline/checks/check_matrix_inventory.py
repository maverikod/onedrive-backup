'''matrix_inventory: every matrix row has named checks and every named check is registered.

Mode: source-static. The pipeline cannot reach the deployed service, so the CURRENT command and
route rows are compared with the registration code in src/onedrive_api/server.py. The comparison
with the live help and OpenAPI surface belongs to the planned live checks (cmd_*, surface_*).
A pending check is a stub that always FAILS; this check proves that it fails and never passes.
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
BLOCKS = ('B1', 'B2', 'B3', 'B4', 'UI-VUE')
TAG = re.compile(r'^(CURRENT|PLANNED[(](B1|B2|B3|B4|UI-VUE)[)])$')
STATUSES = ('legacy', 'implemented', 'pending', 'deprecated')
ROW_KEYS = ('id', 'surface', 'name', 'tag', 'source', 'checks')
PARAM_KEYS = ('types', 'required', 'default', 'constraints', 'valid', 'invalid')
TOP_KEYS = ('identity', 'parameter_columns', 'rows', 'relations', 'result_contracts', 'checks',
            'expected_counts')
NAME_LINE = re.compile(r'^[ ]+name = .([a-z_]+).$', re.M)
ROUTE = re.compile(r'@app[.](get|post|delete)[(].(/api/v1[^)]*).[)]')


def _source_problems(data: dict, problems: list[str]) -> None:
    server = (ROOT / 'src/onedrive_api/server.py').read_text(encoding='utf-8')
    tree = ast.parse(server)
    registered: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.For) and isinstance(node.iter, ast.Tuple):
            names = [item.id for item in node.iter.elts if isinstance(item, ast.Name)]
            if names and len(names) == len(node.iter.elts):
                registered |= set(names)
    rows = [row for row in data['rows'] if row['tag'] == 'CURRENT']
    classes = {row['class'] for row in rows if row['surface'] == 'mcp'}
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


def _row_problems(data: dict, names: dict[str, dict], problems: list[str]) -> Counter:
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
            problems.append('row %s: tag %r is not CURRENT or PLANNED(block)' % (rid, row.get('tag')))
        counts['%s/%s' % (row.get('surface'), 'CURRENT' if row.get('tag') == 'CURRENT' else 'PLANNED')] += 1
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
        if entry.get('status') == 'deprecated' and names.get(entry.get('replaced_by'), {}).get('status') in (None, 'deprecated'):
            problems.append('check %s: replaced_by %s is not a live registered check' % (name, entry.get('replaced_by')))
    for name in checks.discover():
        if name not in names:
            problems.append('pipeline/checks/check_%s.py is not registered in the matrix' % name)
    return names


def run() -> None:
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
    if problems:
        raise CheckFailure('%d violation(s):\n  - %s' % (len(problems), '\n  - '.join(problems)))
    print('[INFO] rows %d, checks %d (%s)' % (len(data['rows']), len(names),
          ', '.join('%s %d' % (s, sum(1 for e in names.values() if e['status'] == s)) for s in STATUSES)))
