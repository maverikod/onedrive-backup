'''Cases of matrix row BE3 (keep-both storage, block DUP-KEEP-REV10, matrix TODO 10.17.3 to 10.17.6 and 10.17.10) and the new BE1 case.

Every case runs the REAL backup_libraries over the DupBox stubs and judges the run record, the stub transcripts (rclone, restic, Graph
in one ordered event log), the mirror tree and the stub restic snapshots. h of the naming rule is the first hex digits of
sha256(Graph item id); an extra whose name key clashes with a source name gets 4 more digits per step (10.17.3, R27).
'''

from __future__ import annotations

from pipeline import be1
from pipeline.dupbox import DupBox, Item, excluded, patterns_of, stored_name, suffix
from pipeline.dupcheck import (CA, CB, D1, D2, PLAIN, data_files, entry, exit_code, extra, fields, graph_gets, outcome, pair, standard_fields,
                               start, summary)
from pipeline.report import Report


def _later(box: DupBox, first: tuple[str, ...], second: tuple[str, ...]) -> bool:
    '''True when the last event starting with first precedes the first event starting with second.'''
    left = [n for n, event in enumerate(box.events) if event[:len(first)] == first]
    right = [n for n, event in enumerate(box.events) if event[:len(second)] == second]
    return bool(left and right and max(left) < min(right))


def extra_stored_and_snapshotted(report: Report) -> None:
    '''The extra is fetched, stored at <stem>.dup-<h8><ext>, snapshotted once after the fetch with the unchanged tags; ok plus a WARNING.'''
    label, box = 'BE3 extra_stored_and_snapshotted', DupBox()
    try:
        first, second = pair()
        box.drive(D1, first, second)
        value, bad = start(report, label, box, [D1])
        want = stored_name(PLAIN, 'ID-B')
        if box.stored(D1, want) != CB:
            report.product.append('%s: the stored copy %s is missing or its bytes differ from the object ID-B' % (label, want))
        backups = box.restic_backups(D1)
        tags = ['sharepoint', 'site-' + box.sb.stable_key(be1.SITE), box.tag(D1)]
        if len(backups) != 1 or [backups[0][i + 1] for i, word in enumerate(backups[0]) if word == '--tag'] != tags or str(box.mirror(D1)) not in backups[0]:
            report.product.append('%s: restic backup ran %d time(s), expected once with the mirror path and the tags %s: %r' % (label, len(backups), tags, backups))
        if not _later(box, ('graph', 'GET'), ('restic', 'backup')):
            report.product.append('%s: the restic backup did not run after the fetch; events %r' % (label, box.events))
        if not box.snapshots or not {PLAIN, want} <= set(box.snapshots[-1]['files']):
            report.product.append('%s: the snapshot does not hold both the plain file and the stored copy' % label)
        found = entry(report, label, value, D1)
        if found is None:
            return
        outcome(report, label, found, 'ok', None)
        row = extra(report, label, found, 'ID-B')
        if row is not None:
            fields(report, label, row, **standard_fields(second))
        if not any('ID-B' in item.getMessage() and want.rpartition('/')[2] in item.getMessage() for item in bad):
            report.product.append('%s: no WARNING line names the item ID-B and the stored copy %s (10.17.6)' % (label, want))
    finally:
        box.close()


def name_stable_across_runs(report: Report) -> None:
    '''Two runs of one library give the identical stored_as.'''
    label, box = 'BE3 name_stable_across_runs', DupBox()
    try:
        box.drive(D1, *pair())
        names = []
        for _ in range(2):
            value, _bad = start(report, label, box, [D1])
            found = entry(report, label, value, D1)
            if found is None:
                return
            names.append([row.get('stored_as') for row in found['duplicates']])
        if names[0] != names[1] or names[0] != [stored_name(PLAIN, 'ID-B')]:
            report.product.append('%s: stored_as is %r in the first run and %r in the second, expected [%s] both times' % (label, names[0], names[1], stored_name(PLAIN, 'ID-B')))
    finally:
        box.close()


def name_clash_extends_hex(report: Report) -> None:
    '''A source name that clashes with the 8 digit stored_as under key() (here by case) makes the stored_as use 12 digits.

    The item id ID-2 is chosen because its digest starts with a letter: the upper-case spelling of the clash name is then no reserved
    name (reserved names carry lower-case hex) and no exclude pattern over lower-case hex digits may hide it from the sync.
    '''
    label, box = 'BE3 name_clash_extends_hex', DupBox()
    try:
        clash = 'dir/Report.dup-%s.xlsx' % suffix('ID-2').upper()
        box.drive(D1, Item(PLAIN, 'ID-1', CA), Item(PLAIN, 'ID-2', CB), Item(clash, 'ID-X', b'clash'))
        value, _ = start(report, label, box, [D1])
        found = entry(report, label, value, D1)
        if found is None:
            return
        row = extra(report, label, found, 'ID-2')
        if row is not None:
            fields(report, label, row, stored_as=stored_name(PLAIN, 'ID-2', 12))
        if box.stored(D1, clash) != b'clash':
            report.product.append('%s: the source file %s was not synced as a normal file' % (label, clash))
    finally:
        box.close()


def rerun_no_refetch(report: Report) -> None:
    '''The second run finds the stored copy with equal size and hash: zero content requests, the copy counts as kept.'''
    label, box = 'BE3 rerun_no_refetch', DupBox()
    try:
        box.drive(D1, *pair())
        start(report, label, box, [D1])
        before = len(graph_gets(box))
        value, _ = start(report, label, box, [D1])
        if len(graph_gets(box)) != before:
            report.product.append('%s: the second run made %d content request(s) for a stored copy that was already equal' % (label, len(graph_gets(box)) - before))
        found = entry(report, label, value, D1)
        if found is not None:
            summary(report, label, found, groups=1, kept=1)
    finally:
        box.close()


def sync_does_not_delete_stored_copy(report: Report) -> None:
    '''The sync carries the protection argument, the stored copy survives it, and a copy whose twin is gone stays and is counted stale.'''
    label, box = 'BE3 sync_does_not_delete_stored_copy', DupBox()
    try:
        first, second = pair()
        box.drive(D1, first, second)
        start(report, label, box, [D1])
        want = stored_name(PLAIN, 'ID-B')
        start(report, label, box, [D1])
        command = box.sync_commands(D1)[-1]
        if not excluded(want, patterns_of(command)):
            report.product.append('%s: the sync arguments carry no exclude pattern that protects %s: %r' % (label, want, command))
        if box.stored(D1, want) != CB:
            report.product.append('%s: the stored copy %s did not survive the second sync' % (label, want))
        box.drive(D1, first)
        value, _ = start(report, label, box, [D1])
        if box.stored(D1, want) != CB:
            report.product.append('%s: the stored copy was removed after its twin disappeared from the source (nothing is deleted automatically, O-D)' % label)
        found = entry(report, label, value, D1)
        if found is not None:
            summary(report, label, found, stale=1)
            outcome(report, label, found, 'ok', None)
    finally:
        box.close()


def integrity_hash_mismatch_kept_and_error(report: Report) -> None:
    '''Equal size, different bytes: one re-fetch, the file is kept, integrity mismatch, DUPLICATE_INTEGRITY_MISMATCH, partial and exit 1.'''
    label, box = 'BE3 integrity_hash_mismatch_kept_and_error', DupBox()
    try:
        box.drive(D1, *pair(fetch='mismatch'))
        box.drive(D2, Item('ok.txt', 'ID-C', b'fine'))
        value, _ = start(report, label, box, [D1, D2])
        found = entry(report, label, value, D1)
        if found is None:
            return
        outcome(report, label, found, 'duplicate_incomplete', 'DUPLICATE_INTEGRITY_MISMATCH')
        row = extra(report, label, found, 'ID-B')
        if row is not None:
            fields(report, label, row, integrity='mismatch', error='DUPLICATE_INTEGRITY_MISMATCH')
        want = stored_name(PLAIN, 'ID-B')
        if box.stored(D1, want) is None:
            report.product.append('%s: the mismatching copy %s was not kept (it is never deleted)' % (label, want))
        if len(box.requests_for('ID-B')) != 2:
            report.product.append('%s: ID-B was requested %d time(s), expected 2 (one fetch and one re-fetch)' % (label, len(box.requests_for('ID-B'))))
        if len(box.restic_backups(D1)) != 1:
            report.product.append('%s: restic backup ran %d time(s) for the duplicate_incomplete library, expected once (10.17.9 R29)' % (label, len(box.restic_backups(D1))))
        if not isinstance(value, dict) or value.get('status') != 'partial' or exit_code(box, value) != 1:
            report.product.append('%s: run status %r and exit code %r, expected partial and 1' % (label, value.get('status') if isinstance(value, dict) else value, exit_code(box, value) if isinstance(value, dict) else None))
    finally:
        box.close()


def hash_unavailable_size_checked(report: Report) -> None:
    '''Graph gives no hash: the size is checked, integrity hash_unavailable, not an error, outcome ok.'''
    label, box = 'BE3 hash_unavailable_size_checked', DupBox()
    try:
        first, second = pair(hashed=False)
        box.drive(D1, first, second)
        value, _ = start(report, label, box, [D1])
        found = entry(report, label, value, D1)
        if found is None:
            return
        outcome(report, label, found, 'ok', None)
        row = extra(report, label, found, 'ID-B')
        if row is not None:
            fields(report, label, row, **standard_fields(second, integrity='hash_unavailable'))
        if box.stored(D1, stored_name(PLAIN, 'ID-B')) != CB:
            report.product.append('%s: the stored copy is missing or differs from the object' % label)
    finally:
        box.close()


def fetch_failure_no_file_and_error(report: Report) -> None:
    '''Three failed attempts: no stored file and no temporary file remain, DUPLICATE_FETCH_FAILED, fetch_failed, duplicate_incomplete.'''
    label, box = 'BE3 fetch_failure_no_file_and_error', DupBox()
    try:
        box.drive(D1, *pair(fetch='fail'))
        value, _ = start(report, label, box, [D1])
        found = entry(report, label, value, D1)
        if found is None:
            return
        outcome(report, label, found, 'duplicate_incomplete', 'DUPLICATE_FETCH_FAILED')
        row = extra(report, label, found, 'ID-B')
        if row is not None:
            fields(report, label, row, integrity='fetch_failed', error='DUPLICATE_FETCH_FAILED')
        if len(box.requests_for('ID-B')) != 3:
            report.product.append('%s: ID-B was requested %d time(s), expected the 3 attempts of the retry discipline' % (label, len(box.requests_for('ID-B'))))
        if data_files(box) != [box.mirror(D1).relative_to(box.tmp / 'data').as_posix() + '/' + PLAIN]:
            report.product.append('%s: files under the data directory are %r, expected only the plain file (no stored copy, no temporary file)' % (label, data_files(box)))
        if len(box.restic_backups(D1)) != 1:
            report.product.append('%s: restic backup ran %d time(s) for the duplicate_incomplete library, expected once' % (label, len(box.restic_backups(D1))))
    finally:
        box.close()


def dry_run_writes_nothing(report: Report) -> None:
    '''Dry run: the scan runs, nothing is fetched, written or snapshotted, the extras are listed with integrity not_fetched.'''
    label, box = 'BE3 dry_run_writes_nothing', DupBox()
    try:
        box.drive(D1, *pair())
        value, _ = start(report, label, box, [D1], dry_run=True)
        found = entry(report, label, value, D1)
        if found is not None:
            row = extra(report, label, found, 'ID-B')
            if row is not None:
                fields(report, label, row, integrity='not_fetched', error=None)
        if graph_gets(box) or data_files(box) or box.mirror(D1).exists() or box.restic_backups(D1):
            report.product.append('%s: a dry run fetched %d, left files %r, created the mirror %s, ran %d restic backup(s)'
                                  % (label, len(graph_gets(box)), data_files(box), box.mirror(D1).exists(), len(box.restic_backups(D1))))
    finally:
        box.close()


def source_object_never_written(report: Report) -> None:
    '''Only GET requests reach Graph, the token never goes to another host, and no rclone verb writes to the source.'''
    label, box = 'BE3 source_object_never_written', DupBox()
    try:
        box.drive(D1, *pair())
        start(report, label, box, [D1])
        methods = {(row['method'], row['host']) for row in box.graph}
        if not methods or not methods <= {('GET', 'graph.microsoft.com'), ('POST', 'login.microsoftonline.com')} or ('GET', 'graph.microsoft.com') not in methods:
            report.product.append('%s: the Graph requests are %r, expected GET %s and the token POST only' % (label, sorted(methods), 'graph.microsoft.com'))
        if any(row['auth'] and row['host'] != 'graph.microsoft.com' for row in box.graph):
            report.product.append('%s: an Authorization header was sent to a host other than graph.microsoft.com' % label)
        if box.writes:
            report.product.append('%s: rclone verbs that write to the source were issued: %r' % (label, box.writes))
    finally:
        box.close()


def mixed_run_with_duplicate_incomplete(report: Report) -> None:
    '''BE1: one ok and one duplicate_incomplete library give status partial and exit 1 (a duplicate_incomplete library is an error library).'''
    label, box = 'BE1 mixed_run_with_duplicate_incomplete', DupBox()
    try:
        box.drive(D1, *pair(fetch='fail'))
        box.drive(D2, Item('ok.txt', 'ID-C', b'fine'))
        value, _ = start(report, label, box, [D1, D2])
        found, other = entry(report, label, value, D1), entry(report, label, value, D2)
        if found is not None:
            outcome(report, label, found, 'duplicate_incomplete', 'DUPLICATE_FETCH_FAILED')
        if other is not None:
            outcome(report, label, other, 'ok', None)
        if not isinstance(value, dict) or value.get('status') != 'partial' or exit_code(box, value) != 1:
            report.product.append('%s: run status %r and exit code %r, expected partial and 1' % (label, value.get('status') if isinstance(value, dict) else value, exit_code(box, value) if isinstance(value, dict) else None))
    finally:
        box.close()


def run_all(report: Report) -> None:
    '''Run the ten BE3 cases.'''
    for case in (extra_stored_and_snapshotted, name_stable_across_runs, name_clash_extends_hex, rerun_no_refetch, sync_does_not_delete_stored_copy,
                 integrity_hash_mismatch_kept_and_error, hash_unavailable_size_checked, fetch_failure_no_file_and_error, dry_run_writes_nothing,
                 source_object_never_written):
        case(report)
