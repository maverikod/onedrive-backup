'''snapshot_tag_visibility: the catalog shows snapshots of both tags, each marked with its source (PL5, defect b).

Mode: fixture. The real Catalog runs over a fake restic that honours --tag like restic. The repository
holds a snapshot tagged onedrive, one tagged sharepoint (with its site and drive tags) and one with an
unrelated tag. Decision Q2: the catalog lists the onedrive and the sharepoint snapshots, not the
unrelated one; every item carries a source marker (key source, value onedrive or sharepoint) that tells
them apart; items stay ordered by time, newest first; count is the number of listed snapshots.
'''

from __future__ import annotations

from pathlib import Path

from pipeline import fixtures
from pipeline.report import Report

ROOT = Path(__file__).resolve().parents[2]
SHAREPOINT_TAGS = ['sharepoint', 'site-' + 'c' * 64, 'drive-' + 'd' * 64]
UNRELATED_ID = 'c3d4e5f6' * 8


def _filter_line() -> str:
    text = (ROOT / 'src' / 'onedrive_api' / 'catalog.py').read_text(encoding='utf-8')
    for number, raw in enumerate(text.splitlines(), 1):
        if '--tag' in raw:
            return 'src/onedrive_api/catalog.py:%d (%s)' % (number, raw.strip())
    return 'src/onedrive_api/catalog.py'


def run() -> None:
    '''Raise CheckFailure when a sharepoint snapshot is hidden or the two sources are not distinguishable.'''
    report = Report()
    snapshots = [
        {'id': fixtures.SNAPSHOT_ID, 'short_id': 'a1b2c3d4', 'time': '2026-11-01T00:00:00Z', 'tags': ['onedrive']},
        {'id': fixtures.SECOND_ID, 'short_id': 'b2c3d4e5', 'time': '2026-11-02T00:00:00Z', 'tags': SHAREPOINT_TAGS},
        {'id': UNRELATED_ID, 'short_id': 'c3d4e5f6', 'time': '2026-11-03T00:00:00Z', 'tags': ['manual']},
    ]
    with fixtures.catalog_fixture(snapshots=snapshots) as fx:
        status, value = fx.call(fx.catalog.snapshots, 100)
    if status != 'ok':
        report.product.append('snapshots() failed with status %s: %s' % (status, value))
        report.finish('snapshot_tag_visibility')
    items = {item.get('id'): item for item in value['items']}
    if fixtures.SECOND_ID not in items:
        report.product.append('the snapshot tagged sharepoint is hidden from the catalog: listed ids %s; the filter is at %s'
                              % (sorted(i[:8] for i in items), _filter_line()))
    if fixtures.SNAPSHOT_ID not in items:
        report.product.append('the snapshot tagged onedrive is missing from the catalog')
    if UNRELATED_ID in items:
        report.product.append('a snapshot with an unrelated tag is listed; only onedrive and sharepoint snapshots belong to the catalog')
    for sid, source in ((fixtures.SNAPSHOT_ID, 'onedrive'), (fixtures.SECOND_ID, 'sharepoint')):
        if sid in items and items[sid].get('source') != source:
            report.product.append('snapshot %s must carry source=%s, item has source=%r'
                                  % (sid[:8], source, items[sid].get('source')))
    times = [item.get('time', '') for item in value['items']]
    if times != sorted(times, reverse=True):
        report.product.append('items are not ordered by time, newest first: %s' % times)
    if value['count'] != len(value['items']) or value['count'] != 2:
        report.product.append('count is %r for %d listed items, expected 2 (one onedrive and one sharepoint snapshot)'
                              % (value['count'], len(value['items'])))
    report.finish('snapshot_tag_visibility')
