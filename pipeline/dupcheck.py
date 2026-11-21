'''Shared fixtures and assertions of the DUP-KEEP-REV10 stub checks (rows BE1-BE3, matrix TODO 10.17.6 and 10.17.10).

Record contract asserted here (10.17.6): every library entry of the run record carries duplicates (ALWAYS a list, one object per
extra: path, name, item_id, stored_as, size, quickxor, integrity, error) and duplicate_summary {groups, kept, failed, stale}.
item_id is the Graph item id, the part of the rclone ID after '#' (the rclone ID is <drive_id>#<item id>; the content URL takes
the item id), and h of the naming rule is the first hex digits of sha256(item id as UTF-8).
'''

from __future__ import annotations

from typing import Any
from unittest import mock

from pipeline import be1
from pipeline.dupbox import DupBox, Item, b64, entry_of, extras_of, stored_name
from pipeline.report import Report

D1, D2 = 'drive-dup-1', 'drive-dup-2'
PLAIN = 'dir/Report.xlsx'
CA = b'alpha: the bytes of the first object of the pair'
CB = b'bravo: the different bytes of the second object of the pair'
ZERO = {'groups': 0, 'kept': 0, 'failed': 0, 'stale': 0}


def pair(*, fetch: str = 'ok', hashed: bool = True) -> tuple[Item, Item]:
    '''Two objects of one name in one folder: the first is the one rclone mirrors, the second is the extra.'''
    return Item(PLAIN, 'ID-A', CA), Item(PLAIN, 'ID-B', CB, hashed=hashed, fetch=fetch)


def start(report: Report, label: str, box: DupBox, drives: list[str], *, dry_run: bool = False) -> tuple[Any, list]:
    '''Run the cycle; an exception out of backup_libraries is a product finding (problems are recorded, never raised).'''
    value, error, bad = box.run(drives, dry_run=dry_run)
    if error is not None:
        report.product.append('%s: the run aborted with %s: %s (a library problem of revision 10 is recorded in the run record)'
                              % (label, type(error).__name__, str(error)[:120]))
    return value, bad


def entry(report: Report, label: str, value: Any, drive: str) -> dict[str, Any] | None:
    '''The library entry when it carries duplicates and duplicate_summary; otherwise one product finding and None.'''
    found = entry_of(value, drive)
    if found is None:
        report.product.append('%s: the run record %r has no entry for %s' % (label, value, drive))
        return None
    if extras_of(found) is None or not isinstance(found.get('duplicate_summary'), dict):
        report.product.append('%s: the entry of %s lacks duplicates (always a list) or duplicate_summary (10.17.6); its keys are %s'
                              % (label, drive, sorted(found)))
        return None
    return found


def outcome(report: Report, label: str, found: dict[str, Any], wanted: str, error: str | None) -> None:
    '''The library outcome and its first error code.'''
    if found.get('outcome') != wanted or found.get('error') != error:
        report.product.append('%s: outcome %r error %r, expected %r and %r' % (label, found.get('outcome'), found.get('error'), wanted, error))


def summary(report: Report, label: str, found: dict[str, Any], **counts: int) -> None:
    '''duplicate_summary equals the zero summary with the given counts.'''
    wanted = dict(ZERO, **counts)
    if found.get('duplicate_summary') != wanted:
        report.product.append('%s: duplicate_summary is %r, expected %r' % (label, found.get('duplicate_summary'), wanted))


def extra(report: Report, label: str, found: dict[str, Any], item_id: str) -> dict[str, Any] | None:
    '''The one duplicates object of an item id, or None after a product finding.'''
    rows = [row for row in extras_of(found) or [] if row.get('item_id') == item_id]
    if len(rows) != 1:
        report.product.append('%s: duplicates holds %d object(s) for item %s, expected exactly one; it holds %r'
                              % (label, len(rows), item_id, [row.get('item_id') for row in extras_of(found) or []]))
        return None
    return rows[0]


def fields(report: Report, label: str, row: dict[str, Any], **wanted: object) -> None:
    '''Every named field of a duplicates object equals its expected value.'''
    bad = ['%s=%r (expected %r)' % (name, row.get(name), value) for name, value in wanted.items() if row.get(name) != value]
    if bad:
        report.product.append('%s: the duplicates object of %s differs: %s' % (label, row.get('item_id'), '; '.join(bad)))


def standard_fields(item: Item, **more: object) -> dict[str, object]:
    '''The expected fields of the duplicates object of one extra whose copy was stored and verified.'''
    wanted: dict[str, object] = {'path': PLAIN, 'name': item.path.rpartition('/')[2], 'stored_as': stored_name(item.path, item.item),
                                 'size': len(item.content), 'quickxor': b64(item.content) if item.hashed else None,
                                 'integrity': 'ok', 'error': None}
    wanted.update(more)
    return wanted


def exit_code(box: DupBox, record: dict[str, Any]) -> object:
    '''The process exit code of one cycle whose backup_libraries returns this run record (D3: ok 0, partial 1, failed 1).'''
    data = box.tmp / 'data'
    patches: list[Any] = [
        mock.patch.object(box.sb, 'configure_logging', lambda *a, **k: None),
        mock.patch.object(box.sb.Path, 'is_mount', lambda self: True),
        mock.patch.object(box.sb, 'load_config', lambda path: dict(box.cfg, required_mountpoint=data.resolve())),
        mock.patch.object(box.sb, 'preflight', lambda cfg: None),
        mock.patch.object(box.sb, 'assert_repository', lambda cfg: None),
        mock.patch.object(box.sb, 'discover', lambda *a, **k: {}),
        mock.patch.object(box.sb, 'backup_libraries', lambda *a, **k: record),
    ]
    for item in patches:
        item.start()
    try:
        return box.sb.main(['--config', str(box.tmp / 'backup.json'), '--data', str(data)])
    except BaseException as exc:
        return 'raised %s: %s' % (type(exc).__name__, exc)
    finally:
        for item in patches:
            item.stop()


def data_files(box: DupBox) -> list[str]:
    '''Every regular file below the data directory except the repository stub, relative to it (a leftover temporary file shows here).'''
    base = box.tmp / 'data'
    return sorted(str(path.relative_to(base)) for path in base.rglob('*') if path.is_file() and path.name != 'config')


def scans(box: DupBox, drive: str) -> list[list[str]]:
    '''The recursive rclone lsjson commands of one library (the scan of 10.17.4 (1)).'''
    return [cmd for cmd in box.commands(drive, 'rclone', 'lsjson') if '-R' in cmd or '--recursive' in cmd]


def graph_gets(box: DupBox) -> list[dict[str, Any]]:
    '''The recorded Graph requests other than the token POST.'''
    return [row for row in box.graph if row['method'] != 'POST']


def control(report: Report) -> None:
    '''Control: a library without a collision is synced and snapshotted once over these stubs; a failure is a sandbox defect.'''
    box = DupBox()
    try:
        box.drive(D1, Item('a.txt', 'ID-C', b'alpha'), Item('dir/b.txt', 'ID-D', b'bravo'))
        value, error, _ = box.run([D1])
        problems = [] if error is None else ['aborted with %s: %s' % (type(error).__name__, error)]
        if error is None and (len(box.sync_commands(D1)) != 1 or len(box.restic_backups(D1)) != 1 or box.stored(D1, 'dir/b.txt') != b'bravo'):
            problems.append('the library was not synced once and snapshotted once')
        report.env.extend('DUP sandbox control (a library without a collision): ' + item for item in problems)
        if not problems:
            report.info.append('DUP sandbox control GREEN: a library without a collision is synced once and snapshotted once over the stubs; '
                               'the stub rclone, restic and Graph run in this process, subprocess is refused (record %s)' % be1.outcomes(value))
    finally:
        box.close()
