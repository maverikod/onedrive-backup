'''folder_index_live: row PL19, the index file_dir of the host file index (matrix TODO 10.21.2 PERFORMANCE AND INDEX, INDEX MIGRATION, 10.21.8).

The file name index /srv/archive/onedrive-backup/file-index/index.sqlite3 is read on the host the pipeline runs on (the service host, as
schedule_host_timer reads systemctl there). It is opened READ-ONLY with the sqlite URI mode=ro, and with immutable=1 while no -wal file
exists, so that no -wal or -shm file is created by this process; a -wal file without its -shm file means the index is being written and
the check reports STATE without opening it. Only SELECT statements and the read-only PRAGMA index_info run; nothing is written.
Cases: index_file_dir_exists (sqlite_master lists file_dir on file (snapshot_id, dir) beside file_snapshot and file_name),
snapshot_rows_unchanged (the 12 snapshots of F3 with their file row counts, every snapshot row equal to its file rows recomputed
relationally, the index counts of backup_filter_options, and no change between the first and the last read of the run) and
schedule_unchanged (backup_schedule_get.revision, 10.21.1 F7). The data grows nightly: later snapshots are allowed.
'''

from __future__ import annotations

import os
import sqlite3
from pathlib import Path
from typing import Any

from pipeline import live, rev13
from pipeline.report import Report

INDEX_PATH = Path('/srv/archive/onedrive-backup/file-index/index.sqlite3')
F3_BEFORE = '2026-11-23T00:00:00Z'
F3_ROWS = {'a1e970cc': [66446, 66446, 66448, 66448], '402dc92a': [19666, 19666, 19666, 19666], 'c4857718': [347, 347, 347, 347]}
F3_TOTAL = 345840
F3_SNAPSHOTS = 12
OLD_INDEXES = ('file_name', 'file_snapshot')


def _connect(report: Report) -> sqlite3.Connection | None:
    '''Open the host index read-only; None after an ENVIRONMENT or STATE finding.

    Args:
        report: the findings collector.

    Returns:
        The read-only connection or None.
    '''
    if not INDEX_PATH.is_file():
        report.env.append('PL19: %s is not a file here: this check needs the service host' % INDEX_PATH)
        return None
    names = set(os.listdir(INDEX_PATH.parent))
    wal, shm = INDEX_PATH.name + '-wal' in names, INDEX_PATH.name + '-shm' in names
    if wal and not shm:
        report.state.append('PL19: %s-wal exists without its -shm file: the index is being written, not opened' % INDEX_PATH)
        return None
    uri = 'file:%s?mode=ro%s' % (INDEX_PATH, '' if wal else '&immutable=1')
    try:
        return sqlite3.connect(uri, uri=True, timeout=30)
    except sqlite3.Error as exc:
        report.env.append('PL19: %s cannot be opened read-only: %s' % (INDEX_PATH, exc))
        return None


def _read(report: Report) -> dict[str, Any] | None:
    '''Open the index read-only, read the snapshot rows, the file rows per snapshot and the indexes of the table file, close it.

    Args:
        report: the findings collector.

    Returns:
        {snapshots: [(snapshot_id, time_utc, drive_key, files)], rows: {snapshot_id: count}, indexes: {name: [columns]}}, or None.
    '''
    conn = _connect(report)
    if conn is None:
        return None
    try:
        snapshots = [tuple(row) for row in conn.execute('SELECT snapshot_id, time_utc, drive_key, files FROM snapshot ORDER BY time_utc, snapshot_id')]
        rows = {str(sid): int(count) for sid, count in conn.execute('SELECT snapshot_id, COUNT(*) FROM file GROUP BY snapshot_id')}
        names = [str(row[0]) for row in conn.execute("SELECT name FROM sqlite_master WHERE type = 'index' AND tbl_name = 'file' ORDER BY name")]
        indexes = {name: [str(col[2]) for col in conn.execute('SELECT * FROM pragma_index_info(?)', (name,))] for name in names}
    finally:
        conn.close()
    return {'snapshots': snapshots, 'rows': rows, 'indexes': indexes}


def _index_case(report: Report, first: dict[str, Any]) -> None:
    '''Case index_file_dir_exists: file_dir on file (snapshot_id, dir) beside file_snapshot and file_name.

    Args:
        report: the findings collector.
        first: the first read.

    Returns:
        None.
    '''
    indexes = first['indexes']
    if indexes.get('file_dir') != ['snapshot_id', 'dir'] or any(name not in indexes for name in OLD_INDEXES):
        report.product.append('PL19 index_file_dir_exists: sqlite_master lists the indexes %s on file, expected file_dir on file (snapshot_id, dir) '
                              'beside file_snapshot and file_name (10.21.2 PERFORMANCE AND INDEX; 0.3.25 has only file_snapshot and file_name, F2)' % indexes)
    else:
        report.info.append('PL19 index_file_dir_exists conformant: %s' % indexes)


def _rows_case(report: Report, first: dict[str, Any], last: dict[str, Any], index: Any) -> None:
    '''Case snapshot_rows_unchanged: F3 snapshots and counts, files == file rows per snapshot, index counts, no change within the run.

    Args:
        report: the findings collector.
        first: the first read (start of the run).
        last: the last read (a second connection after the live reads).
        index: the index object of backup_filter_options.

    Returns:
        None.
    '''
    before = len(report.product)
    snapshots, rows = first['snapshots'], first['rows']
    old = [snap for snap in snapshots if str(snap[1]) < F3_BEFORE]
    found = {key: sorted(int(snap[3]) for snap in old if str(snap[2]).startswith(key)) for key in F3_ROWS}
    if len(old) != F3_SNAPSHOTS or found != F3_ROWS or sum(rows.get(str(snap[0]), 0) for snap in old) != F3_TOTAL:
        report.product.append('PL19 snapshot_rows_unchanged: %d snapshots before %s with file counts %s (%d rows), expected the %d of 10.21.1 F3 %s (%d rows)'
                              % (len(old), F3_BEFORE, found, sum(rows.get(str(snap[0]), 0) for snap in old), F3_SNAPSHOTS, F3_ROWS, F3_TOTAL))
    differing = [(str(snap[0])[:8], snap[3], rows.get(str(snap[0]), 0)) for snap in snapshots if int(snap[3]) != rows.get(str(snap[0]), 0)]
    orphans = sorted(sid[:8] for sid in rows if sid not in {str(snap[0]) for snap in snapshots})
    if differing or orphans:
        report.product.append('PL19 snapshot_rows_unchanged: snapshot rows whose files column differs from the file rows %s, file rows without a snapshot row %s'
                              % (differing, orphans))
    if len(snapshots) < F3_SNAPSHOTS or sum(rows.values()) < F3_TOTAL:
        report.product.append('PL19 snapshot_rows_unchanged: %d snapshot rows and %d file rows, expected at least %d and %d' % (len(snapshots), sum(rows.values()), F3_SNAPSHOTS, F3_TOTAL))
    counts = (index.get('complete'), index.get('snapshots_total'), index.get('snapshots_indexed')) if isinstance(index, dict) else None
    if counts != (True, len(snapshots), len(snapshots)):
        report.product.append('PL19 snapshot_rows_unchanged: backup_filter_options index %s, expected complete true with %d of %d snapshots (the snapshot rows)'
                              % (index, len(snapshots), len(snapshots)))
    if last['snapshots'] != snapshots or last['rows'] != rows:
        report.product.append('PL19 snapshot_rows_unchanged: the index changed within the run: %d -> %d snapshot rows, %d -> %d file rows'
                              % (len(snapshots), len(last['snapshots']), sum(rows.values()), sum(last['rows'].values())))
    if len(report.product) == before:
        report.info.append('PL19 snapshot_rows_unchanged conformant: %d snapshot rows, %d file rows, F3 %s, unchanged within the run'
                           % (len(snapshots), sum(rows.values()), found))


def _schedule(report: Report, label: str) -> None:
    '''Case schedule_unchanged: the non-writing backup_schedule_get answers the revision of 10.21.1 F7.

    Args:
        report: the findings collector.
        label: when the read happens.

    Returns:
        None.
    '''
    kind, code, message, data = live.request('backup_schedule_get', {})
    revision = data.get('revision') if kind == 'success' and isinstance(data, dict) else None
    if revision != rev13.SCHEDULE_REVISION:
        report.product.append('PL19 schedule_unchanged (%s): backup_schedule_get answers %s %s revision %s, expected %s'
                              % (label, kind, code, revision, rev13.SCHEDULE_REVISION))
    else:
        report.info.append('PL19 schedule_unchanged (%s) conformant: revision %s' % (label, revision[:8]))


def folder_index_live() -> None:
    '''PL19: read the host index read-only twice (two connections) around the live reads and judge the three cases.

    Returns:
        None.
    '''
    report = Report()
    listing = sorted(os.listdir(INDEX_PATH.parent)) if INDEX_PATH.parent.is_dir() else []
    try:
        _schedule(report, 'start')
        first = _read(report)
        kind, _, _, options = live.request('backup_filter_options', {})
        index = options.get('index') if kind == 'success' and isinstance(options, dict) else None
        _schedule(report, 'end')
        last = _read(report) if first is not None else None
        if first is not None and last is not None:
            _index_case(report, first)
            _rows_case(report, first, last, index)
    except live.LiveUnreachable as exc:
        report.env.append('PL19: not executed, production service unreachable: %s' % exc)
    except sqlite3.Error as exc:
        report.env.append('PL19: the read-only index read failed: %s: %s' % (type(exc).__name__, exc))
    after = sorted(os.listdir(INDEX_PATH.parent)) if INDEX_PATH.parent.is_dir() else []
    if after != listing:
        report.env.append('PL19: the index directory listing changed during the check: %s -> %s' % (listing, after))
    report.finish('folder_index_live')
