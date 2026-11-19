'''Sandbox and executors of matrix row BE1 (backup cycle per library, block BACKUP-EMPTY, matrix TODO 10.14 and 10.14.1).

The REAL backup code path runs: onedrive_api.sharepoint_backup.backup_libraries over a configuration loaded by the real
load_config, the real inventory validation, the real library_mirror and the real assert_repository. Only the two process
boundaries are replaced, in this process and for the duration of one call: run_command (rclone and restic) of both
modules, and subprocess.run / subprocess.Popen, which refuse every call. The fake rclone answers lsjson and sync over a
dictionary that stands for the SharePoint libraries; the fake restic keeps snapshots in memory. Every path lives under one
temporary directory of the checkout (.test-run); the fakes refuse a command that is not rclone or restic and any absolute
path outside that directory, so nothing of the host (/srv/backup, /srv/archive, /var/lib/onedrive-backup), the network or
the real SharePoint is reached and no real backup runs.

What is normative (user decision, 10.14): the per-library outcome values ok / empty / source_emptied and their side effects.
What is a planner proposal (10.14.1 (1)): the form of the run record {status, libraries: [{site_id, drive_id, outcome, error}]},
the run status values and the exit semantics. The proposals are reported as INFO and never block; the outcome and the recorded
error of each library must be observable, in the record returned by backup_libraries.
'''

from __future__ import annotations

import hashlib
import importlib
import json
import logging
import sys
from pathlib import Path
from unittest import mock

from pipeline import fixtures
from pipeline.report import Report

SITE = 'site-a'
NEW_EMPTY, EMPTIED, FULL = 'drive-1-new-empty', 'drive-2-emptied', 'drive-3-with-files'
FILES = {'a.txt': 'alpha', 'dir/b.txt': 'bravo'}
HOST_PATHS = ('/srv/backup', '/srv/archive', '/var/lib/onedrive-backup')


class Refused(Exception):
    '''A command or path the sandbox does not admit.'''


def _refuse(*args, **kwargs):
    raise Refused('subprocess is refused inside the BE1 sandbox: %r' % (args[:1],))


class Sandbox:
    '''One temporary world: configuration, mirror, repository, a fake SharePoint remote and a fake restic.'''

    def __init__(self) -> None:
        for item in (str(fixtures.SRC), str(fixtures.ROOT)):
            if item not in sys.path:
                sys.path.insert(0, item)
        self.sb = importlib.import_module('onedrive_api.sharepoint_backup')
        self.ob = importlib.import_module('onedrive_backup')
        self.tmp = fixtures._work_dir('be1-').resolve()
        for sub in ('data/mirror', 'data/restic-repo', 'secrets', 'lock'):
            (self.tmp / sub).mkdir(parents=True, exist_ok=True)
        (self.tmp / 'data/restic-repo/config').write_text('stub', encoding='utf-8')
        (self.tmp / 'secrets/restic-password').write_text('stub', encoding='utf-8')
        (self.tmp / 'rclone.conf').write_text('[onedrive]', encoding='utf-8')
        settings = {'onedrive_remote': 'onedrive:', 'rclone_config': str(self.tmp / 'rclone.conf'),
                    'mirror_dir': str(self.tmp / 'data/mirror'), 'repository_dir': str(self.tmp / 'data/restic-repo'),
                    'password_file': str(self.tmp / 'secrets/restic-password'), 'lock_file': str(self.tmp / 'lock/backup.lock')}
        (self.tmp / 'backup.json').write_text(json.dumps(settings), encoding='utf-8')
        self.cfg = self.ob.load_config(self.tmp / 'backup.json')
        self.remote: dict[str, dict[str, str]] = {}
        self.snapshots: list[dict] = []
        self.calls: list[list[str]] = []

    def close(self) -> None:
        fixtures._remove(self.tmp)

    def mirror(self, drive: str) -> Path:
        return self.sb.library_mirror(self.cfg, SITE, drive)

    def tag(self, drive: str) -> str:
        return 'drive-' + self.sb.stable_key(drive)

    def tree(self, folder: Path) -> dict[str, str]:
        if not folder.is_dir():
            return {}
        return {str(item.relative_to(folder)): hashlib.sha256(item.read_bytes()).hexdigest()
                for item in sorted(folder.rglob('*')) if item.is_file()}

    def seed_backed_up(self, drive: str) -> None:
        '''A library that already has a mirror and one snapshot (it was backed up before it was emptied).'''
        target = self.mirror(drive)
        for name, text in FILES.items():
            (target / name).parent.mkdir(parents=True, exist_ok=True)
            (target / name).write_text(drive + ':' + text, encoding='utf-8')
        self.snapshots.append({'tags': ['sharepoint', 'site-' + self.sb.stable_key(SITE), self.tag(drive)], 'files': self.tree(target)})

    def snapshots_of(self, drive: str) -> list[dict]:
        return [item for item in self.snapshots if self.tag(drive) in item['tags']]

    def commands(self, drive: str, tool: str, verb: str) -> list[list[str]]:
        found = []
        for cmd in self.calls:
            if Path(cmd[0]).name == tool and verb in cmd and (tool == 'restic' and self.tag(drive) in cmd
                                                              or tool == 'rclone' and drive in cmd):
                found.append(cmd)
        return found

    def _paths_ok(self, cmd: list[str]) -> None:
        for arg in cmd[1:]:
            if isinstance(arg, str) and arg.startswith('/') and not Path(arg).resolve().is_relative_to(self.tmp):
                raise Refused('the path %s is outside the sandbox' % arg)
            if isinstance(arg, str) and any(arg.startswith(item) for item in HOST_PATHS):
                raise Refused('the host path %s is not admitted' % arg)

    def _rclone(self, cmd: list[str]) -> str:
        drive = cmd[cmd.index('--onedrive-drive-id') + 1]
        if drive not in self.remote:
            raise self.ob.BackupError('rclone: unknown drive %s' % drive)
        if 'lsjson' in cmd:
            return json.dumps([{'Path': name, 'IsDir': False} for name in sorted(self.remote[drive])])
        if 'sync' not in cmd:
            raise Refused('rclone verb outside lsjson and sync: %r' % cmd)
        target = Path(cmd[cmd.index('sync') + 2])
        limit = int(cmd[cmd.index('--max-delete') + 1])
        stale = [name for name in self.tree(target) if name not in self.remote[drive]]
        if len(stale) > limit:
            raise self.ob.BackupError('rclone: --max-delete %d exceeded by %d deletions' % (limit, len(stale)))
        for name in stale:
            (target / name).unlink()
        for name, text in self.remote[drive].items():
            (target / name).parent.mkdir(parents=True, exist_ok=True)
            (target / name).write_text(drive + ':' + text, encoding='utf-8')
        return ''

    def fake(self, cmd, env=None, *, capture=False) -> str:
        '''The stand-in of run_command: rclone lsjson and sync, restic cat and backup; anything else is refused.'''
        cmd = [str(item) for item in cmd]
        self.calls.append(cmd)
        self._paths_ok(cmd)
        tool = Path(cmd[0]).name
        if tool == 'rclone':
            return self._rclone(cmd)
        if tool == 'restic' and 'cat' in cmd:
            return '{}'
        if tool == 'restic' and 'backup' in cmd:
            target = Path(cmd[cmd.index('backup') + 1])
            self.snapshots.append({'tags': [cmd[i + 1] for i, item in enumerate(cmd) if item == '--tag'], 'files': self.tree(target)})
            return ''
        raise Refused('command outside rclone lsjson/sync and restic cat/backup: %r' % cmd[:3])

    def run(self, drives: list[str]):
        '''Run backup_libraries for the drives; return (value, exception, log records of WARNING and above, all records).'''
        found = {'sites': [{'site_id': SITE, 'display_name': 'stub', 'source_status': 'ok'}],
                 'libraries': [{'site_id': SITE, 'drive_id': drive, 'status': 'ok'} for drive in drives],
                 'complete': True, 'errors': []}
        records: list[logging.LogRecord] = []
        handler = logging.Handler(0)
        handler.emit = records.append
        log = logging.getLogger('onedrive_backup')
        log.addHandler(handler)
        value, error = None, None
        try:
            with mock.patch.object(self.sb, 'run_command', self.fake), mock.patch.object(self.ob, 'run_command', self.fake), \
                    mock.patch.object(self.ob.subprocess, 'run', _refuse), mock.patch.object(self.ob.subprocess, 'Popen', _refuse):
                value = self.sb.backup_libraries(self.cfg, found, dry_run=False)
        except Exception as exc:
            error = exc
        finally:
            log.removeHandler(handler)
        return value, error, [item for item in records if item.levelno >= logging.WARNING]


def outcomes(value) -> dict[str, tuple] | None:
    '''Return {drive_id: (outcome, error)} from the run record, or None when the run record carries no per-library outcome.'''
    rows = value.get('libraries') if isinstance(value, dict) else value
    if not isinstance(rows, list) or not rows or any(not (isinstance(row, dict) and row.get('drive_id')) for row in rows):
        return None
    return {row['drive_id']: (row.get('outcome', row.get('status')), row.get('error')) for row in rows}


def _logged(box: Sandbox, drive: str, records: list) -> bool:
    return any(drive in item.getMessage() or box.sb.stable_key(drive) in item.getMessage() for item in records)


def _run_record(report: Report, label: str, value, error, expected: dict[str, str]) -> dict | None:
    '''Report the observability of the per-library outcomes (normative values, proposal form) and the run status (proposal).'''
    found = outcomes(value) if error is None else None
    if found is None:
        if error is None:
            report.product.append('%s: backup_libraries returned %r, which carries no per-library outcome; the outcomes %s must be observable in the run record '
                                  '{status, libraries: [{site_id, drive_id, outcome, error}]} (form: planner proposal 10.14.1 (1) (d); values: normative)' % (label, value, expected))
        return None
    for drive, wanted in expected.items():
        got = found.get(drive, (None, None))[0]
        if got != wanted:
            report.product.append('%s: the outcome of %s is %r, expected %r' % (label, drive, got, wanted))
    if isinstance(value, dict):
        report.info.append('PROPOSAL (10.14.1 (1) (e), not asserted): %s run status %r' % (label, value.get('status')))
    return found


def _untouched(report: Report, label: str, box: Sandbox, drive: str, before: dict) -> None:
    '''The library was not synced, not snapshotted, its mirror was neither created nor changed and nothing was deleted.'''
    for tool, verb in (('rclone', 'sync'), ('restic', 'backup')):
        if box.commands(drive, tool, verb):
            report.product.append('%s: %s %s was run for %s although the source is empty (a sync of an empty source deletes the mirror)' % (label, tool, verb, drive))
    if box.tree(box.mirror(drive)) != before['mirror'] or box.mirror(drive).exists() != before['exists']:
        report.product.append('%s: the mirror of %s was created or changed (before %d files, after %d)' % (label, drive, len(before['mirror']), len(box.tree(box.mirror(drive)))))
    if box.snapshots_of(drive) != before['snapshots']:
        report.product.append('%s: the snapshots of %s changed (before %d, after %d)' % (label, drive, len(before['snapshots']), len(box.snapshots_of(drive))))


def _before(box: Sandbox, drive: str) -> dict:
    return {'mirror': box.tree(box.mirror(drive)), 'exists': box.mirror(drive).exists(), 'snapshots': list(box.snapshots_of(drive))}


def _no_abort(report: Report, label: str, error) -> None:
    if error is not None:
        report.product.append('%s: the run aborted with %s: %s (expected: the library is handled and the run continues with the others)' % (label, type(error).__name__, error))


def _synced(report: Report, label: str, box: Sandbox, drive: str) -> None:
    '''A library with files is synced once with the unchanged max-delete and snapshotted once with its tags.'''
    syncs = box.commands(drive, 'rclone', 'sync')
    if len(syncs) != 1 or syncs[0][syncs[0].index('--max-delete') + 1] != str(box.cfg['max_delete']):
        report.product.append('%s: %s was synced %d time(s), expected once with --max-delete %s' % (label, drive, len(syncs), box.cfg['max_delete']))
    if len(box.snapshots_of(drive)) != 1 or box.tree(box.mirror(drive)) != {name: hashlib.sha256((drive + ':' + text).encode()).hexdigest() for name, text in FILES.items()}:
        report.product.append('%s: %s has %d snapshot(s) and a mirror that differs from its source, expected one snapshot of the mirror' % (label, drive, len(box.snapshots_of(drive))))


def control(report: Report) -> None:
    '''Control: a library with files is synced and snapshotted as before; a failure is a defect of the sandbox, never of the product.'''
    box = Sandbox()
    try:
        box.remote[FULL] = dict(FILES)
        value, error, _ = box.run([FULL])
        problems = Report()
        _no_abort(problems, 'control', error)
        _synced(problems, 'control', box, FULL)
        report.env.extend('BE1 sandbox control (an ok library alone): ' + item for item in problems.product)
        if not problems.product:
            report.info.append('BE1 sandbox control GREEN: an ok library is synced once and snapshotted once over the stubs (no process, network or host path)')
    finally:
        box.close()


def empty_new_library_skipped(report: Report) -> None:
    '''A never backed up empty library: skipped, status empty, nothing copied or created, no snapshot, no error, the run does not abort.'''
    label = 'BE1 empty_new_library_skipped'
    box = Sandbox()
    try:
        box.remote[NEW_EMPTY] = {}
        before = _before(box, NEW_EMPTY)
        value, error, bad = box.run([NEW_EMPTY])
        _no_abort(report, label, error)
        _untouched(report, label, box, NEW_EMPTY, before)
        if any(item.levelno >= logging.ERROR for item in bad):
            report.product.append('%s: an error was logged for an empty library that was never backed up (it is skipped, not an error): %s' % (label, bad[0].getMessage()[:120]))
        found = _run_record(report, label, value, error, {NEW_EMPTY: 'empty'})
        if found and found[NEW_EMPTY][1]:
            report.product.append('%s: an error %r is recorded for the skipped empty library' % (label, found[NEW_EMPTY][1]))
    finally:
        box.close()


def emptied_library_not_synced_error(report: Report) -> None:
    '''A library with snapshots that is now empty: not synced, mirror and snapshots untouched, status source_emptied, an error recorded.'''
    label = 'BE1 emptied_library_not_synced_error'
    box = Sandbox()
    try:
        box.seed_backed_up(EMPTIED)
        box.remote[EMPTIED] = {}
        before = _before(box, EMPTIED)
        value, error, bad = box.run([EMPTIED])
        _untouched(report, label, box, EMPTIED, before)
        found = _run_record(report, label, value, error, {EMPTIED: 'source_emptied'})
        recorded = bool(found and found[EMPTIED][1]) or _logged(box, EMPTIED, bad)
        if not recorded:
            report.product.append('%s: no error is recorded for %s (neither in the run record nor as a warning or error log naming the library); raised %s' % (label, EMPTIED, '%s: %s' % (type(error).__name__, error) if error else 'nothing'))
    finally:
        box.close()


def mixed_run_continues(report: Report) -> None:
    '''One empty, one emptied and one ok library in one run (the ok one sorts last): the ok library is backed up, the others are handled.'''
    label = 'BE1 mixed_run_continues'
    box = Sandbox()
    try:
        box.seed_backed_up(EMPTIED)
        box.remote.update({NEW_EMPTY: {}, EMPTIED: {}, FULL: dict(FILES)})
        before = {NEW_EMPTY: _before(box, NEW_EMPTY), EMPTIED: _before(box, EMPTIED)}
        value, error, bad = box.run([NEW_EMPTY, EMPTIED, FULL])
        _no_abort(report, label, error)
        _untouched(report, label, box, NEW_EMPTY, before[NEW_EMPTY])
        _untouched(report, label, box, EMPTIED, before[EMPTIED])
        _synced(report, label, box, FULL)
        found = _run_record(report, label, value, error, {NEW_EMPTY: 'empty', EMPTIED: 'source_emptied', FULL: 'ok'})
        if not ((found and found[EMPTIED][1]) or _logged(box, EMPTIED, bad)):
            report.product.append('%s: no error is recorded for %s' % (label, EMPTIED))
        if found and (found[NEW_EMPTY][1] or found[FULL][1]):
            report.product.append('%s: an error is recorded for the empty or the ok library: %r' % (label, {k: v[1] for k, v in found.items() if k != EMPTIED and v[1]}))
    finally:
        box.close()


def run_all(report: Report) -> None:
    '''Run the control and the three cases of row BE1.'''
    control(report)
    empty_new_library_skipped(report)
    emptied_library_not_synced_error(report)
    mixed_run_continues(report)
    report.info.append('isolation: temporary directory under .test-run only; stub rclone and restic in this process, subprocess refused, host paths '
                       'and network never reached; the PROPOSAL items (run status, exit 0/1/1, record form) are reported, not asserted')
