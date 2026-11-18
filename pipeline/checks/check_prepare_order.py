'''prepare_order: backup_prepare_download validates file_path before any side effect (row PL6, defects F1, F2).

Mode: fixture plus one live case. Order of rule R2: snapshot_id, then file_path, and only then the
exports directory, the storage gate (_config) and restic. In the fixture an invalid file_path (relative
escape, absolute, empty) answers 400 in scaffold mode and in normal mode, creates no exports directory
and never starts restic; a valid file_path in scaffold mode answers 503 and still creates no exports
directory; an invalid snapshot_id answers 400 first. Live: backup_prepare_download with the invalid
file_path ../x must answer a command error 400, never the scaffold 503.
'''

from __future__ import annotations

from pipeline import fixtures, live
from pipeline.report import Report

BAD_PATHS = ('../x', '/x', '')


def _fixture_cases(report: Report) -> int:
    cases = 0
    for scaffold in (True, False):
        mode = 'scaffold' if scaffold else 'normal'
        for bad in BAD_PATHS:
            with fixtures.catalog_fixture(scaffold=scaffold) as fx:
                status, value = fx.call(fx.catalog.prepare, fixtures.SNAPSHOT_ID, bad)
                cases += 1
                if status != 400:
                    report.product.append('%s mode, file_path %r: answered %s (%s), expected 400' % (mode, bad, status, value))
                if fx.catalog.exports.exists():
                    report.product.append('%s mode, file_path %r: the exports directory was created before the refusal' % (mode, bad))
                if fx.restic_calls():
                    report.product.append('%s mode, file_path %r: restic was started before file_path was validated: %s'
                                          % (mode, bad, fx.restic_calls()))
    with fixtures.catalog_fixture(scaffold=True) as fx:
        status, value = fx.call(fx.catalog.prepare, fixtures.SNAPSHOT_ID, 'dir/file.txt')
        cases += 1
        if status != 503:
            report.product.append('scaffold mode, valid file_path: answered %s (%s), expected 503' % (status, value))
        if fx.catalog.exports.exists():
            report.product.append('scaffold mode, valid file_path: the exports directory was created before the 503 refusal')
    with fixtures.catalog_fixture(scaffold=True) as fx:
        status, value = fx.call(fx.catalog.prepare, 'xyz', '../x')
        cases += 1
        if status != 400 or fx.catalog.exports.exists():
            report.product.append('scaffold mode, invalid snapshot_id: answered %s, exports directory exists: %s, expected 400 and no side effect'
                                  % (status, fx.catalog.exports.exists()))
    with fixtures.catalog_fixture(scaffold=False) as fx:
        status, value = fx.call(fx.catalog.prepare, fixtures.SNAPSHOT_ID, 'no/such.txt')
        cases += 1
        if status != 404:
            report.product.append('normal mode, file missing in the snapshot: answered %s (%s), expected 404' % (status, value))
        status, value = fx.call(fx.catalog.prepare, fixtures.SNAPSHOT_ID, 'dir/file.txt')
        cases += 1
        if status != 'ok':
            report.env.append('control prepare of a valid file failed in the fixture: %s %s' % (status, value))
    return cases


def run() -> None:
    '''Raise CheckFailure when prepare acts or reports in the wrong order.'''
    report = Report()
    count = _fixture_cases(report)
    report.info.append('%d fixture cases run' % count)
    try:
        kind, code, message, _ = live.request('backup_prepare_download', {'snapshot_id': 'abcdef12', 'file_path': '../x'})
    except live.LiveUnreachable as exc:
        report.env.append('live case not executed, production service unreachable: %s' % exc)
    else:
        if not (kind == 'command_error' and code == 400):
            report.product.append('live backup_prepare_download(file_path=../x): %s %s %r, expected command error 400 before the storage gate'
                                  % (kind, code, message))
    report.finish('prepare_order')
