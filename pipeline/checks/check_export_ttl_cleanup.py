'''export_ttl_cleanup: expired temporary exports are removed from the exports directory (PL7, finding F3).

Mode: fixture. Three exports are written: one expired and queried, one expired and never queried, one
valid. Asking for the status of the expired one still answers 410 (the matrix contract) and afterwards
its data file and metadata file are gone. A later prepare, the normal activity that fills the directory,
removes the expired export nobody asked for. The valid export stays intact and readable.
'''

from __future__ import annotations

from pipeline import fixtures
from pipeline.report import Report

QUERIED, UNQUERIED, VALID = '1' * 32, '2' * 32, '3' * 32


def run() -> None:
    '''Raise CheckFailure when an expired export survives the activity of the catalog.'''
    report = Report()
    with fixtures.catalog_fixture() as fx:
        fx.write_export(QUERIED, expired=True)
        fx.write_export(UNQUERIED, expired=True)
        fx.write_export(VALID, expired=False)
        status, value = fx.call(fx.catalog.export_status, QUERIED)
        if status != 410:
            report.product.append('status of an expired export answered %s (%s), expected 410' % (status, value))
        if fx.export_files(QUERIED):
            report.product.append('expired export %s still has %s after it was answered with 410 (no cleanup, F3)'
                                  % (QUERIED, fx.export_files(QUERIED)))
        status, value = fx.call(fx.catalog.prepare, fixtures.SNAPSHOT_ID, 'dir/file.txt')
        if status != 'ok':
            report.env.append('control prepare failed in the fixture: %s %s' % (status, value))
        if fx.export_files(UNQUERIED):
            report.product.append('expired export %s nobody asked for still has %s after a later prepare (no TTL sweep, F3)'
                                  % (UNQUERIED, fx.export_files(UNQUERIED)))
        status, value = fx.call(fx.catalog.export_status, VALID)
        if status != 'ok' or len(fx.export_files(VALID)) != 2:
            report.product.append('the valid export must stay intact: status %s, files %s' % (status, fx.export_files(VALID)))
    report.finish('export_ttl_cleanup')
