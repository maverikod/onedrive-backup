'''Revision 14 executor of the rows of pipeline.cmdcases (M3 backup_snapshots, M4, M5, M6; matrix TODO 10.22.4, 10.22.6.2, 10.22.6.3).

The earlier cases run exactly as pipeline.cmdcases.run_row runs them; the revision 14 cases (ids td*, tm*, rm*) run through
pipeline.rev14.judge on the project client. Every export staged by a revision 14 case is deleted at the end.
'''

from __future__ import annotations

import json
from typing import Any, Callable

from pipeline import cmdcases, live, matrix
from pipeline.report import Report
from pipeline.rev14 import PREFIXES, ErrorChecks, Tree14, Validators, judge


def run_cmd_row(row_id: str, name: str, validators: Validators, errors: ErrorChecks, setup: Callable[[Tree14], Any] | None = None) -> None:
    '''Execute a row of pipeline.cmdcases (M3-M6): the earlier cases as cmdcases.run_row, then the revision 14 cases through the client.

    For M5 the earlier cases send snapshot_id as before: RM1 makes it required unless file_id is given, and no earlier case gives file_id.

    Args:
        row_id: the matrix row.
        name: the named check.
        validators: the ok: validators of the revision 14 cases.
        errors: the error.data predicates of the revision 14 cases.
        setup: registers the lazy placeholders of the row, or None.

    Returns:
        None.
    '''
    data: Any = matrix.load()
    row = next(item for item in data['rows'] if item['id'] == row_id)
    contracts = data['result_contracts'][row_id]['cases']
    report = Report()
    old_row = json.loads(json.dumps(row))
    if row_id == 'M5':
        old_row['params']['snapshot_id']['required'] = True
    try:
        state: Any = live.service_state()
    except live.LiveUnreachable as exc:
        report.env.append('production service unreachable: %s' % exc)
        state = None
    else:
        report.info.append('production state of %s: %s' % (row['command'], state))
    new = [case for case in row['cases'] if str(case['id']).startswith(PREFIXES)]
    for case in [case for case in row['cases'] if case not in new]:
        if case['id'] not in contracts:
            report.product.append('%s %s: no result contract in pipeline/matrix.yaml' % (row_id, case['id']))
            continue
        try:
            cmdcases._execute(report, old_row, case, contracts[case['id']], state)
        except live.LiveUnreachable as exc:
            report.env.append('%s %s: not executed, production service unreachable: %s' % (row_id, case['id'], exc))
    if row_id == 'M3':
        cmdcases._tag_fixture(report)
    if row_id in ('M5', 'M6') and state is not None:
        kind, code, message, help_data = live.request('help', {'cmdname': row['command']})
        documented = ((help_data.get('metadata') or {}).get('return_value') or {}).get('success', {}).get('data', {}) if kind == 'success' and isinstance(help_data, dict) else {}
        if 'url' not in documented:
            report.product.append('%s: the help metadata documents the success fields %s and no url (block B4 adds the field url = /downloads/<export_id>/<filename>)' % (row['command'], sorted(documented) if isinstance(documented, dict) else documented))
    tree: Tree14 | None = None
    try:
        if state == 'S1':
            tree = Tree14(report)
            if setup is not None:
                setup(tree)
        elif state is not None:
            report.state.append('%s: the revision 14 cases need an S1 service, production answers %s' % (row_id, state))
        for case in new:
            if tree is None:
                break
            cid = str(case['id'])
            expect = contracts.get(cid, {}).get('expect')
            params = tree.resolve(case['params'] or {})
            desc = '%s %s %s(%s)' % (row_id, cid, row['command'], json.dumps(params, ensure_ascii=False)[:300])
            before = len(report.product) + len(report.state) + len(report.env)
            if expect is None:
                report.product.append('%s: no result contract with an expectation in pipeline/matrix.yaml' % desc)
            else:
                judge(tree, report, desc, row, cid, params, expect, validators, errors)
            report.info.append('%s %s: %s' % (row_id, cid, 'GREEN' if len(report.product) + len(report.state) + len(report.env) == before else 'RED'))
    except live.LiveUnreachable as exc:
        report.env.append('%s: revision 14 cases not executed, production service unreachable: %s' % (row_id, exc))
    finally:
        if tree is not None:
            tree.cleanup()
    report.info.append('%d cases of row %s executed (%d of revision 14)' % (len(row['cases']), row_id, len(new)))
    report.finish(name)
