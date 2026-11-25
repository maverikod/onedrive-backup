'''Revision 14 snapshot attributes of the host file index (matrix TODO 10.22.2.5, 10.22.9 TD13 and TD17; row PL20; block DATES-REV14).

Checks index_attributes_live and snapshot_tags_live. The index /srv/archive/onedrive-backup/file-index/index.sqlite3 is read on the service host through
the read-only opening of rev13index (sqlite URI mode=ro, immutable while no -wal file exists); only SELECT and PRAGMA table_info run, nothing is
written and no backup is ever started. index_attributes_live: table_info(snapshot) lists backup_type, trigger, run_id, type_source; the 15 original
snapshots carry the values of 10.22.2.5 (FX5: five runs, two 'record' and three 'derived'), their ids, times and file rows are unchanged (never
fewer rows), they still carry only their original restic tags (read through backup_snapshots) and the schedule revision is unchanged. The invariant
parts are GREEN on 0.3.28 and must stay. snapshot_tags_live is LAGGING: the three newest snapshots (one run) must carry type_source 'tag', trigger
'scheduled' and one run_id equal to backup_schedule_status.last_run.run_id; until such a run exists it is RED with the reason 'no run after
deployment yet' (STATE, never skipped).
'''

from __future__ import annotations

import os
import sqlite3
from typing import Any

from pipeline import live, rev13, rev13index
from pipeline.report import Report

NEW_COLUMNS = ('backup_type', 'trigger', 'run_id', 'type_source')
OLD_COLUMNS = ('snapshot_id', 'time_utc', 'site_key', 'drive_key', 'files', 'indexed_at')
RECORD_A, RECORD_B = '4196b9cc-e6f8-4006-8c7f-b54b20b85eb1', '623a9abd-4aa9-4c58-93f1-c7d6622aa296'
LEGACY = {'19': 'legacy-20261119T191240Z', '21': 'legacy-20261121T124752Z', '22': 'legacy-20261122T085549Z'}
# FX5: snapshot id prefix -> (UTC time to the second, library key prefix, file rows, run_id, trigger, type_source)
FX5 = {
    'b38a12b1': ('2026-11-19T19:12:40', 'a1e970cc', 66446, LEGACY['19'], 'unknown', 'derived'),
    '75d19f21': ('2026-11-19T20:56:53', '402dc92a', 19666, LEGACY['19'], 'unknown', 'derived'),
    '1e6a5ffb': ('2026-11-19T20:59:48', 'c4857718', 347, LEGACY['19'], 'unknown', 'derived'),
    '50a6076f': ('2026-11-21T12:47:52', 'a1e970cc', 66446, LEGACY['21'], 'unknown', 'derived'),
    'e68bd0fb': ('2026-11-21T13:05:27', '402dc92a', 19666, LEGACY['21'], 'unknown', 'derived'),
    '71b12dcb': ('2026-11-21T13:08:33', 'c4857718', 347, LEGACY['21'], 'unknown', 'derived'),
    '67c282b6': ('2026-11-22T08:55:49', 'a1e970cc', 66448, LEGACY['22'], 'unknown', 'derived'),
    '801eefb7': ('2026-11-22T09:13:50', '402dc92a', 19666, LEGACY['22'], 'unknown', 'derived'),
    '1213f444': ('2026-11-22T09:14:51', 'c4857718', 347, LEGACY['22'], 'unknown', 'derived'),
    '42209038': ('2026-11-22T23:19:33', 'a1e970cc', 66448, RECORD_A, 'scheduled', 'record'),
    '51103c8c': ('2026-11-22T23:38:11', '402dc92a', 19666, RECORD_A, 'scheduled', 'record'),
    '5a6cc896': ('2026-11-22T23:39:12', 'c4857718', 347, RECORD_A, 'scheduled', 'record'),
    '0ec6899f': ('2026-11-23T23:22:01', 'a1e970cc', 66450, RECORD_B, 'scheduled', 'record'),
    'ba87e802': ('2026-11-23T23:40:09', '402dc92a', 19666, RECORD_B, 'scheduled', 'record'),
    'f2f7813f': ('2026-11-23T23:41:13', 'c4857718', 347, RECORD_B, 'scheduled', 'record'),
}
TRIGGERS = ('scheduled', 'manual', 'unknown')
SOURCES = ('tag', 'record', 'derived')
ORIGINAL_TAGS = ('sharepoint', 'site-', 'drive-')


def _read(report: Report) -> dict[str, Any] | None:
    '''Open the index read-only and read the snapshot table with every column, the file rows per snapshot and the user_version.

    Args:
        report: the findings collector.

    Returns:
        {columns, snapshots: [dict by column], rows: {snapshot_id: count}}, or None after an ENVIRONMENT or STATE finding.
    '''
    conn = rev13index._connect(report)
    if conn is None:
        return None
    try:
        columns = [str(row[1]) for row in conn.execute('PRAGMA table_info(snapshot)')]
        snapshots = [dict(zip(columns, row)) for row in conn.execute('SELECT * FROM snapshot ORDER BY time_utc, snapshot_id')]
        rows = {str(sid): int(count) for sid, count in conn.execute('SELECT snapshot_id, COUNT(*) FROM file GROUP BY snapshot_id')}
    finally:
        conn.close()
    return {'columns': columns, 'snapshots': snapshots, 'rows': rows}


def _original(snapshots: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    '''Pick the 15 original snapshots (FX5) by their id prefix.

    Args:
        snapshots: the snapshot rows.

    Returns:
        {id prefix: row} for the original snapshots found.
    '''
    return {prefix: row for row in snapshots for prefix in FX5 if str(row['snapshot_id']).startswith(prefix)}


def _columns_case(report: Report, first: dict[str, Any]) -> None:
    '''TD13 td13_columns: table_info(snapshot) lists the four attribute columns beside the six original ones.

    Args:
        report: the findings collector.
        first: the first read.

    Returns:
        None.
    '''
    columns = first['columns']
    missing = [name for name in NEW_COLUMNS + OLD_COLUMNS if name not in columns]
    if missing:
        report.product.append('PL20 td13_columns: pragma table_info(snapshot) lists %s, missing %s (10.22.2.5 INDEX COLUMNS)' % (columns, missing))
    else:
        report.info.append('PL20 td13_columns conformant: %s' % columns)


def _values_case(report: Report, first: dict[str, Any]) -> None:
    '''TD13 td13_backfill_values: the 15 original snapshots carry the backfilled values, later ones obey RD6.

    Args:
        report: the findings collector.
        first: the first read.

    Returns:
        None.
    '''
    if any(name not in first['columns'] for name in NEW_COLUMNS):
        report.product.append('PL20 td13_backfill_values: the 15 snapshots of FX5 carry no run attributes: the columns %s are absent from the table snapshot'
                              % [name for name in NEW_COLUMNS if name not in first['columns']])
        return
    found, before = _original(first['snapshots']), len(report.product)
    for prefix, (_, _, _, run_id, trigger, source) in FX5.items():
        row = found.get(prefix)
        got = (row['backup_type'], row['trigger'], row['run_id'], row['type_source']) if row else None
        if got != ('full', trigger, run_id, source):
            report.product.append('PL20 td13_backfill_values: snapshot %s has (backup_type, trigger, run_id, type_source) %s, expected %s'
                                  % (prefix, got, ('full', trigger, run_id, source)))
    for row in first['snapshots']:
        if row in found.values():
            continue
        if row['backup_type'] != 'full' or row['trigger'] not in TRIGGERS or not row['run_id'] or row['type_source'] not in SOURCES:
            report.product.append('PL20 td13_backfill_values (RD6): the later snapshot %s has %s' % (str(row['snapshot_id'])[:8], [row[name] for name in NEW_COLUMNS]))
    if len(report.product) == before:
        report.info.append('PL20 td13_backfill_values conformant: 15 snapshots in 5 runs, %d later snapshots' % (len(first['snapshots']) - len(found)))


def _tags_through_m3(report: Report, found: dict[str, dict[str, Any]]) -> None:
    '''The original snapshots read through backup_snapshots still carry only their three original restic tags.

    Args:
        report: the findings collector.
        found: the original index rows by id prefix.

    Returns:
        None.
    '''
    kind, code, message, data = live.request('backup_snapshots', {})
    items = data.get('items', []) if kind == 'success' and isinstance(data, dict) else []
    seen = {str(item.get('id', ''))[:8]: item.get('tags') for item in items if isinstance(item, dict)}
    originals = {prefix: tags for prefix, tags in seen.items() if prefix in FX5}
    extra = {prefix: tags for prefix, tags in originals.items() if not (isinstance(tags, list) and len(tags) == 3 and all(str(tag).startswith(ORIGINAL_TAGS) for tag in tags))}
    if kind != 'success' or any(prefix not in seen for prefix in found):
        report.product.append('PL20 td13_rows_unchanged: backup_snapshots answered %s %s with %d items, expected the original snapshots %s among them'
                              % (kind, code, len(items), sorted(set(found) - set(seen))))
    if extra:
        report.product.append('PL20 td13_rows_unchanged: original snapshots carry other tags than sharepoint, site-<key>, drive-<key>: %s' % extra)


def _rows_case(report: Report, first: dict[str, Any], last: dict[str, Any]) -> None:
    '''TD13 td13_rows_unchanged: ids, times, libraries and file rows of the 15 (never fewer), no change within the run, original tags.

    Args:
        report: the findings collector.
        first: the first read.
        last: the last read.

    Returns:
        None.
    '''
    found, rows, before = _original(first['snapshots']), first['rows'], len(report.product)
    for prefix, (when, library, count, _, _, _) in FX5.items():
        row = found.get(prefix)
        if row is None:
            report.product.append('PL20 td13_rows_unchanged: the snapshot %s of FX5 is absent from the index' % prefix)
            continue
        have = rows.get(str(row['snapshot_id']), 0)
        if str(row['time_utc'])[:19] != when or not str(row['drive_key']).startswith(library) or have < count or int(row['files']) != have:
            report.product.append('PL20 td13_rows_unchanged: snapshot %s time %s library %s files %s file rows %s, expected %s %s and at least %d rows'
                                  % (prefix, row['time_utc'], str(row['drive_key'])[:8], row['files'], have, when, library, count))
    if [(r['snapshot_id'], r['time_utc']) for r in first['snapshots']] != [(r['snapshot_id'], r['time_utc']) for r in last['snapshots']] or first['rows'] != last['rows']:
        report.product.append('PL20 td13_rows_unchanged: the index changed within the run: %d -> %d snapshot rows' % (len(first['snapshots']), len(last['snapshots'])))
    _tags_through_m3(report, found)
    if len(report.product) == before:
        report.info.append('PL20 td13_rows_unchanged conformant: %d snapshot rows, %d file rows, original tags only' % (len(first['snapshots']), sum(rows.values())))


def _schedule(report: Report, label: str) -> None:
    '''TD13 td13_schedule_unchanged: backup_schedule_get answers the revision of 10.21.1 F7 (RD7).

    Args:
        report: the findings collector.
        label: when the read happens.

    Returns:
        None.
    '''
    kind, code, message, data = live.request('backup_schedule_get', {})
    revision = data.get('revision') if kind == 'success' and isinstance(data, dict) else None
    if revision != rev13.SCHEDULE_REVISION:
        report.product.append('PL20 td13_schedule_unchanged (%s): backup_schedule_get answers %s %s revision %s, expected %s' % (label, kind, code, revision, rev13.SCHEDULE_REVISION))
    else:
        report.info.append('PL20 td13_schedule_unchanged (%s) conformant: revision %s' % (label, revision[:8]))


def index_attributes_live(name: str) -> None:
    '''PL20 TD13: read the host index twice (two connections) around the live reads and judge the four cases.

    Args:
        name: the name of the named check.

    Returns:
        None.
    '''
    report = Report()
    directory = rev13index.INDEX_PATH.parent
    listing = sorted(os.listdir(directory)) if directory.is_dir() else []
    try:
        _schedule(report, 'start')
        first = _read(report)
        last = None
        if first is not None:
            _columns_case(report, first)
            _values_case(report, first)
            last = _read(report)
        if first is not None and last is not None:
            _rows_case(report, first, last)
        _schedule(report, 'end')
    except live.LiveUnreachable as exc:
        report.env.append('PL20: not executed, production service unreachable: %s' % exc)
    except sqlite3.Error as exc:
        report.env.append('PL20: the read-only index read failed: %s: %s' % (type(exc).__name__, exc))
    after = sorted(os.listdir(directory)) if directory.is_dir() else []
    if after != listing:
        report.env.append('PL20: the index directory listing changed during the check: %s -> %s' % (listing, after))
    report.finish(name)


def snapshot_tags_live(name: str) -> None:
    '''PL20 TD17 (LAGGING): the three newest snapshots are one run tagged by the backup command; RED 'no run after deployment yet' until then.

    Args:
        name: the name of the named check.

    Returns:
        None.
    '''
    report = Report()
    try:
        kind, code, message, status = live.request('backup_schedule_status', {})
        last_run = (status.get('last_run') or {}) if kind == 'success' and isinstance(status, dict) else {}
        first = _read(report)
        if first is not None:
            newest = sorted(first['snapshots'], key=lambda row: str(row['time_utc']))[-3:]
            have = all(column in first['columns'] for column in NEW_COLUMNS)
            sources = [row['type_source'] for row in newest] if have else []
            if not have or sources != ['tag'] * len(newest) or not newest:
                report.state.append('PL20 td17_new_run_tagged: no run after deployment yet: the newest snapshots %s carry type_source %s (columns present %s), expected tag; last run %s %s'
                                    % ([str(row['snapshot_id'])[:8] for row in newest], sources, have, str(last_run.get('run_id'))[:8], last_run.get('status')))
            else:
                found = sorted({str(row['trigger']) for row in newest}), sorted({str(row['run_id']) for row in newest})
                if len(newest) != 3 or found[0] != ['scheduled'] or found[1] != [last_run.get('run_id')]:
                    report.product.append('PL20 td17_new_run_tagged: the %d newest snapshots carry triggers %s and run ids %s, expected three with trigger scheduled and the run id %s of backup_schedule_status.last_run'
                                          % (len(newest), found[0], found[1], last_run.get('run_id')))
                else:
                    report.info.append('PL20 td17_new_run_tagged conformant: run %s' % found[1][0])
    except live.LiveUnreachable as exc:
        report.env.append('PL20 td17_new_run_tagged: not executed, production service unreachable: %s' % exc)
    except sqlite3.Error as exc:
        report.env.append('PL20 td17_new_run_tagged: the read-only index read failed: %s: %s' % (type(exc).__name__, exc))
    report.finish(name)
