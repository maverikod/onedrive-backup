'''Cases of matrix row BE2 (collision detection, block DUP-KEEP-REV10, matrix TODO 10.17.2, 10.17.4 (1) and 10.17.10).

Every case runs the REAL backup_libraries over the DupBox stubs and judges the run record, the stub transcripts and the mirror.
Probe P1 (2026-11-21, deployed 0.3.20) settled the rule: the two collision groups of library 1 differ only in the Unicode form of
the name (NFC against NFD), the extension is the same inside each pair; pair_case_or_nfc_group reproduces exactly that.
'''

from __future__ import annotations

import json
import unicodedata

from pipeline.dupbox import DupBox, Item
from pipeline.dupcheck import (CA, CB, D1, PLAIN, entry, extra, fields, outcome, pair, scans, standard_fields, start, summary, graph_gets)
from pipeline.dupbox import extras_of, stored_name
from pipeline.report import Report


def no_collision(report: Report) -> None:
    '''No collision: duplicates [] and an all-zero summary, a recursive scan ran, no Graph content request.'''
    label, box = 'BE2 no_collision', DupBox()
    try:
        box.drive(D1, Item('a.txt', 'ID-C', b'alpha'), Item('dir/b.txt', 'ID-D', b'bravo'))
        value, _ = start(report, label, box, [D1])
        found = entry(report, label, value, D1)
        if found is None:
            return
        outcome(report, label, found, 'ok', None)
        summary(report, label, found)
        if extras_of(found) != []:
            report.product.append('%s: duplicates is %r, expected []' % (label, extras_of(found)))
        if not scans(box, D1):
            report.product.append('%s: no recursive rclone lsjson scan ran (the scan of 10.17.4 (1))' % label)
        if graph_gets(box):
            report.product.append('%s: %d Graph request(s) were made for a library without a collision' % (label, len(graph_gets(box))))
    finally:
        box.close()


def pair_same_name_group(report: Report) -> None:
    '''Two objects of one name give one group and one extra; the primary is the one whose bytes rclone mirrored.'''
    label, box = 'BE2 pair_same_name_group', DupBox()
    try:
        first, second = pair()
        box.drive(D1, first, second)
        value, _ = start(report, label, box, [D1])
        found = entry(report, label, value, D1)
        if found is None:
            return
        summary(report, label, found, groups=1, kept=1)
        row = extra(report, label, found, 'ID-B')
        if row is not None:
            fields(report, label, row, **standard_fields(second))
        if len(extras_of(found) or []) != 1:
            report.product.append('%s: the primary was counted as an extra: duplicates %r' % (label, extras_of(found)))
    finally:
        box.close()


def pair_case_or_nfc_group(report: Report) -> None:
    '''Names that differ only in case, and names that differ only in NFC/NFD form (the observed cause), group together.'''
    label, box = 'BE2 pair_case_or_nfc_group', DupBox()
    try:
        cafe = 'dir/Café.txt'
        nfd = 'dir/' + unicodedata.normalize('NFD', 'Café.txt')
        items = [Item('dir/Fiche.xlsx', 'ID-A', CA), Item('dir/fiche.XLSX', 'ID-B', CB), Item(cafe, 'ID-C', b'cafe nfc'), Item(nfd, 'ID-D', b'cafe nfd')]
        box.drive(D1, *items)
        value, _ = start(report, label, box, [D1])
        found = entry(report, label, value, D1)
        if found is None:
            return
        summary(report, label, found, groups=2, kept=2)
        for item, plain in ((items[1], 'dir/Fiche.xlsx'), (items[3], cafe)):
            row = extra(report, label, found, item.item)
            if row is not None:
                fields(report, label, row, **standard_fields(item, path=plain, name=item.path.rpartition('/')[2]))
    finally:
        box.close()


def three_member_group(report: Report) -> None:
    '''Three objects of one name give one group, two extras and two distinct stored_as.'''
    label, box = 'BE2 three_member_group', DupBox()
    try:
        box.drive(D1, Item(PLAIN, 'ID-A', CA), Item(PLAIN, 'ID-B', CB), Item(PLAIN, 'ID-C', b'charlie: the third object'))
        value, _ = start(report, label, box, [D1])
        found = entry(report, label, value, D1)
        if found is None:
            return
        summary(report, label, found, groups=1, kept=2)
        names = sorted(str(row.get('stored_as')) for row in extras_of(found) or [])
        if sorted(str(row.get('item_id')) for row in extras_of(found) or []) != ['ID-B', 'ID-C'] or len(set(names)) != 2:
            report.product.append('%s: expected the extras ID-B and ID-C with two distinct stored_as, got %r' % (label, extras_of(found)))
    finally:
        box.close()


def primary_by_hash(report: Report) -> None:
    '''The primary is the member whose size and hash equal the plain-path file, not the smallest item id.'''
    label, box = 'BE2 primary_by_hash', DupBox()
    try:
        box.drive(D1, Item(PLAIN, 'ID-Z', CA), Item(PLAIN, 'ID-A', CB))
        value, _ = start(report, label, box, [D1])
        found = entry(report, label, value, D1)
        if found is None:
            return
        if [row.get('item_id') for row in extras_of(found) or []] != ['ID-A']:
            report.product.append('%s: rclone mirrored ID-Z (first listed), so the only extra is ID-A; duplicates is %r' % (label, extras_of(found)))
    finally:
        box.close()


def _tie(order: list[str]) -> tuple[list[object], list[object]]:
    box = DupBox()
    try:
        items = {name: Item(PLAIN, name, CA) for name in ('ID-A', 'ID-B')}
        box.drive(D1, *(items[name] for name in order))
        value, error, _ = box.run([D1])
        rows = (value.get('libraries') or [{}])[0].get('duplicates') if error is None and isinstance(value, dict) else None
        return [row.get('item_id') for row in rows or []], [row.get('stored_as') for row in rows or []]
    finally:
        box.close()


def primary_by_smallest_id_tie(report: Report) -> None:
    '''Identical bytes: the smallest item id is the primary, the same in two runs with reversed listing order.'''
    label = 'BE2 primary_by_smallest_id_tie'
    forward, reverse = _tie(['ID-A', 'ID-B']), _tie(['ID-B', 'ID-A'])
    if forward != reverse or forward[0] != ['ID-B'] or forward[1] != [stored_name(PLAIN, 'ID-B')]:
        report.product.append('%s: extras and stored_as are %r (listing A,B) and %r (listing B,A), expected the same set ([ID-B], [%s]) in both'
                              % (label, forward, reverse, stored_name(PLAIN, 'ID-B')))


def reserved_name_in_source(report: Report) -> None:
    '''A real source object named like a stored copy is not synced; DUPLICATE_NAME_RESERVED, duplicate_incomplete, the record names it.'''
    label, box = 'BE2 reserved_name_in_source', DupBox()
    try:
        reserved = 'dir/Report.dup-0123abcd.xlsx'
        box.drive(D1, Item('a.txt', 'ID-C', b'alpha'), Item(reserved, 'ID-R', CB))
        value, bad = start(report, label, box, [D1])
        found = entry(report, label, value, D1)
        if found is None:
            return
        outcome(report, label, found, 'duplicate_incomplete', 'DUPLICATE_NAME_RESERVED')
        if box.stored(D1, reserved) is not None:
            report.product.append('%s: the reserved name %s was synced into the mirror (it would be hidden by the sync protection)' % (label, reserved))
        named = json.dumps(found, ensure_ascii=False) + ' '.join(item.getMessage() for item in bad)
        if 'Report.dup-0123abcd.xlsx' not in named:
            report.product.append('%s: neither the record entry nor a WARNING or ERROR log line names the object %s (10.17.6): %r' % (label, reserved, found))
    finally:
        box.close()


def scan_failure(report: Report) -> None:
    '''The scan exits non-zero: DUPLICATE_SCAN_FAILED, the sync still runs once, the outcome is duplicate_incomplete.'''
    label, box = 'BE2 scan_failure', DupBox()
    try:
        box.drive(D1, *pair())
        box.scan_fails = True
        value, _ = start(report, label, box, [D1])
        found = entry(report, label, value, D1)
        if found is None:
            return
        outcome(report, label, found, 'duplicate_incomplete', 'DUPLICATE_SCAN_FAILED')
        if len(box.sync_commands(D1)) != 1:
            report.product.append('%s: the sync ran %d time(s), expected once although the scan failed' % (label, len(box.sync_commands(D1))))
    finally:
        box.close()


def duplicate_directory_unsupported(report: Report) -> None:
    '''Two directories of one name: DUPLICATE_DIRECTORY_UNSUPPORTED recorded, nothing merged or dropped, the files are still synced.'''
    label, box = 'BE2 duplicate_directory_unsupported', DupBox()
    try:
        box.drive(D1, Item('a.txt', 'ID-C', b'alpha'))
        box.dirs[D1] = ['dir/Sub', 'dir/SUB']
        value, _ = start(report, label, box, [D1])
        found = entry(report, label, value, D1)
        if found is None:
            return
        outcome(report, label, found, 'duplicate_incomplete', 'DUPLICATE_DIRECTORY_UNSUPPORTED')
        if box.stored(D1, 'a.txt') != b'alpha' or len(box.sync_commands(D1)) != 1:
            report.product.append('%s: the files of the library were not synced once (nothing may be dropped)' % label)
    finally:
        box.close()


def run_all(report: Report) -> None:
    '''Run the nine BE2 cases.'''
    for case in (no_collision, pair_same_name_group, pair_case_or_nfc_group, three_member_group, primary_by_hash, primary_by_smallest_id_tie,
                 reserved_name_in_source, scan_failure, duplicate_directory_unsupported):
        case(report)
