'''Sandbox and executors of matrix row BE1 (backup cycle per library, block BACKUP-EMPTY, matrix TODO 10.14 and 10.14.1).

The REAL backup code path runs: onedrive_api.sharepoint_backup.backup_libraries over a configuration loaded by the real
load_config, the real inventory validation, the real library_mirror and the real assert_repository. Only the two process
boundaries are replaced, in this process and for the duration of one call: run_command (rclone and restic) of both
modules, and subprocess.run / subprocess.Popen, which refuse every call. The fake rclone answers lsjson and sync over a
dictionary that stands for the SharePoint libraries; the fake restic keeps snapshots in memory. Every path lives under one
temporary directory of the checkout (.test-run); the fakes refuse a command that is not rclone or restic and any absolute
path outside that directory, so nothing of the host (/srv/backup, /srv/archive, /var/lib/onedrive-backup), the network or
the real SharePoint is reached and no real backup runs.

What is normative (user decision 10.14 and, since revision 8, D3 of 10.15.9.4 APPROVED): the per-library outcome values ok / empty /
source_emptied and their side effects, the run record {status, libraries: [{site_id, drive_id, outcome, error}]}, the run status ok |
partial | failed (ok when every library is ok or empty, an all-empty run included; partial when at least one library is source_emptied or
errored and at least one other completed; failed when none completed and at least one errored) and the exit codes ok 0, partial 1,
failed 1 (refusals 2 unchanged). The outcome and the recorded error of each library are observable in the record returned by
backup_libraries.
'''

from __future__ import annotations

import hashlib
import importlib
import json
import logging
import sys
from pathlib import Path
from typing import Any
from unittest import mock

from pipeline import fixtures
from pipeline.report import Report

SITE = 'site-a'
NEW_EMPTY, EMPTIED, FULL = 'drive-1-new-empty', 'drive-2-emptied', 'drive-3-with-files'
FILES = {'a.txt': 'alpha', 'dir/b.txt': 'bravo'}
HOST_PATHS = ('/srv/backup', '/srv/archive', '/var/lib/onedrive-backup')


class Refused(Exception):
    '''A command or path the sandbox does not admit.'''


def _refuse(*args: Any, **kwargs: Any) -> None:
    '''Refuse every subprocess call made inside the BE1 sandbox.

    Args:
        *args: the positional arguments of the refused call.
        **kwargs: the keyword arguments of the refused call.

    Returns:
        Nothing; the call always raises Refused.
    '''
    raise Refused('subprocess is refused inside the BE1 sandbox: %r' % (args[:1],))


class Sandbox:
    '''One temporary world: configuration, mirror, repository, a fake SharePoint remote and a fake restic.

    Attributes:
        sb: the imported onedrive_api.sharepoint_backup module.
        ob: the imported onedrive_backup module.
        tmp: the temporary directory of the sandbox.
        cfg: the configuration loaded by the real load_config.
        remote: the fake SharePoint, drive id to relative file path to text.
        snapshots: the in-memory restic snapshots.
        calls: every command line the stubs received.
    '''

    def __init__(self) -> None:
        '''Build the temporary world: configuration, mirror, repository and the empty fake remote and restic.

        Returns:
            None.
        '''
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
        '''Remove the temporary directory of the sandbox.

        Returns:
            None.
        '''
        fixtures._remove(self.tmp)

    def mirror(self, drive: str) -> Path:
        '''Return the mirror directory of one library.

        Args:
            drive: the drive id of the library.

        Returns:
            The mirror path of the library under the sandbox mirror directory.
        '''
        return self.sb.library_mirror(self.cfg, SITE, drive)

    def tag(self, drive: str) -> str:
        '''Return the restic tag of one library.

        Args:
            drive: the drive id of the library.

        Returns:
            The tag the product puts on the snapshots of the library.
        '''
        return 'drive-' + self.sb.stable_key(drive)

    def tree(self, folder: Path) -> dict[str, str]:
        '''Return the file tree of a folder as relative path to sha256.

        Args:
            folder: the folder to read.

        Returns:
            A dictionary of relative file path to content hash, empty when the folder does not exist.
        '''
        if not folder.is_dir():
            return {}
        return {str(item.relative_to(folder)): hashlib.sha256(item.read_bytes()).hexdigest()
                for item in sorted(folder.rglob('*')) if item.is_file()}

    def seed_backed_up(self, drive: str) -> None:
        '''A library that already has a mirror and one snapshot (it was backed up before it was emptied).

        Args:
            drive: the drive id of the library to seed.

        Returns:
            None.
        '''
        target = self.mirror(drive)
        for name, text in FILES.items():
            (target / name).parent.mkdir(parents=True, exist_ok=True)
            (target / name).write_text(drive + ':' + text, encoding='utf-8')
        self.snapshots.append({'tags': ['sharepoint', 'site-' + self.sb.stable_key(SITE), self.tag(drive)], 'files': self.tree(target)})

    def snapshots_of(self, drive: str) -> list[dict]:
        '''Return the snapshots that carry the tag of one library.

        Args:
            drive: the drive id of the library.

        Returns:
            The matching snapshot records.
        '''
        return [item for item in self.snapshots if self.tag(drive) in item['tags']]

    def commands(self, drive: str, tool: str, verb: str) -> list[list[str]]:
        '''Return the recorded commands of one tool and verb that concern one library.

        Args:
            drive: the drive id of the library.
            tool: rclone or restic.
            verb: the verb to look for in the command line.

        Returns:
            The recorded command lines.
        '''
        found = []
        for cmd in self.calls:
            if Path(cmd[0]).name == tool and verb in cmd and (tool == 'restic' and self.tag(drive) in cmd
                                                              or tool == 'rclone' and drive in cmd):
                found.append(cmd)
        return found

    def _paths_ok(self, cmd: list[str]) -> None:
        '''Refuse a command that names a path outside the sandbox or a host path.

        Args:
            cmd: the command line.

        Returns:
            None when every path is admitted.
        '''
        for arg in cmd[1:]:
            if isinstance(arg, str) and arg.startswith('/') and not Path(arg).resolve().is_relative_to(self.tmp):
                raise Refused('the path %s is outside the sandbox' % arg)
            if isinstance(arg, str) and any(arg.startswith(item) for item in HOST_PATHS):
                raise Refused('the host path %s is not admitted' % arg)

    def _rclone(self, cmd: list[str]) -> str:
        '''Answer a stub rclone lsjson or sync over the dictionary that stands for the libraries.

        Args:
            cmd: the rclone command line.

        Returns:
            The stub standard output.
        '''
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

    def fake(self, cmd: Any, env: Any = None, *, capture: bool = False) -> str:
        '''The stand-in of run_command: rclone lsjson and sync, restic cat and backup; anything else is refused.

        Args:
            cmd: the command line.
            env: the environment the product passes, unused.
            capture: whether the product captures the output, unused.

        Returns:
            The stub standard output.
        '''
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

    def run(self, drives: list[str]) -> tuple[Any, Exception | None, list[logging.LogRecord]]:
        '''Run backup_libraries for the drives.

        Args:
            drives: the drive ids to back up.

        Returns:
            The value, the exception and the log records of WARNING and above.
        '''
        found = {'sites': [{'site_id': SITE, 'display_name': 'stub', 'source_status': 'ok'}],
                 'libraries': [{'site_id': SITE, 'drive_id': drive, 'status': 'ok'} for drive in drives],
                 'complete': True, 'errors': []}
        records: list[logging.LogRecord] = []
        handler = logging.Handler(0)
        setattr(handler, 'emit', records.append)
        log = logging.getLogger('onedrive_backup')
        log.addHandler(handler)
        value: Any = None
        error: Exception | None = None
        try:
            with mock.patch.object(self.sb, 'run_command', self.fake), mock.patch.object(self.ob, 'run_command', self.fake):
                with mock.patch.object(self.ob.subprocess, 'run', _refuse), mock.patch.object(self.ob.subprocess, 'Popen', _refuse):
                    value = self.sb.backup_libraries(self.cfg, found, dry_run=False)
        except Exception as exc:
            error = exc
        finally:
            log.removeHandler(handler)
        return value, error, [item for item in records if item.levelno >= logging.WARNING]


def outcomes(value: Any) -> dict[str, tuple[Any, Any]] | None:
    '''Return {drive_id: (outcome, error)} from the run record, or None when it carries no per-library outcome.

    Args:
        value: the value returned by backup_libraries.

    Returns:
        The outcome and error of each library, or None.
    '''
    rows = value.get('libraries') if isinstance(value, dict) else value
    if not isinstance(rows, list) or not rows or any(not (isinstance(row, dict) and row.get('drive_id')) for row in rows):
        return None
    return {row['drive_id']: (row.get('outcome', row.get('status')), row.get('error')) for row in rows}


def _logged(box: Sandbox, drive: str, records: list) -> bool:
    '''Tell whether a log record names the library.

    Args:
        box: the sandbox.
        drive: the drive id of the library.
        records: the collected log records.

    Returns:
        True when a record names the drive or its stable key.
    '''
    return any(drive in item.getMessage() or box.sb.stable_key(drive) in item.getMessage() for item in records)


def _run_record(report: Report, label: str, value: Any, error: Any, expected: dict[str, str], status: str | None = None) -> dict[str, tuple[Any, Any]] | None:
    '''Report the observability of the per-library outcomes and the run status (all normative since revision 8, D3).

    Args:
        report: the report to extend.
        label: the case label.
        value: the value returned by backup_libraries.
        error: the exception raised by the run, if any.
        expected: the expected outcome of each drive.
        status: the expected run status, or None.

    Returns:
        The per-library outcomes, or None when the run record carries none.
    '''
    found = outcomes(value) if error is None else None
    if found is None:
        if error is None:
            report.product.append('%s: backup_libraries returned %r, which carries no per-library outcome; the outcomes %s must be observable in the run record '
                                  '{status, libraries: [{site_id, drive_id, outcome, error}]} (approved form, D3)' % (label, value, expected))
        return None
    for drive, wanted in expected.items():
        got = found.get(drive, (None, None))[0]
        if got != wanted:
            report.product.append('%s: the outcome of %s is %r, expected %r' % (label, drive, got, wanted))
    if status is not None and (not isinstance(value, dict) or value.get('status') != status):
        report.product.append('%s: the run status is %r, expected %r (ok | partial | failed, D3)' % (label, value.get('status') if isinstance(value, dict) else value, status))
    return found


def _untouched(report: Report, label: str, box: Sandbox, drive: str, before: dict[str, Any]) -> None:
    '''The library was not synced, not snapshotted, its mirror was neither created nor changed and nothing was deleted.

    Args:
        report: the report to extend.
        label: the case label.
        box: the sandbox.
        drive: the drive id of the library.
        before: the state captured before the run.

    Returns:
        None.
    '''
    for tool, verb in (('rclone', 'sync'), ('restic', 'backup')):
        if box.commands(drive, tool, verb):
            report.product.append('%s: %s %s was run for %s although the source is empty (a sync of an empty source deletes the mirror)' % (label, tool, verb, drive))
    if box.tree(box.mirror(drive)) != before['mirror'] or box.mirror(drive).exists() != before['exists']:
        report.product.append('%s: the mirror of %s was created or changed (before %d files, after %d)' % (label, drive, len(before['mirror']), len(box.tree(box.mirror(drive)))))
    if box.snapshots_of(drive) != before['snapshots']:
        report.product.append('%s: the snapshots of %s changed (before %d, after %d)' % (label, drive, len(before['snapshots']), len(box.snapshots_of(drive))))


def _before(box: Sandbox, drive: str) -> dict[str, Any]:
    '''Capture the mirror and the snapshots of one library before a run.

    Args:
        box: the sandbox.
        drive: the drive id of the library.

    Returns:
        The mirror tree, its existence and the snapshots.
    '''
    return {'mirror': box.tree(box.mirror(drive)), 'exists': box.mirror(drive).exists(), 'snapshots': list(box.snapshots_of(drive))}


def _no_abort(report: Report, label: str, error: Any) -> None:
    '''Report a run that aborted instead of continuing with the other libraries.

    Args:
        report: the report to extend.
        label: the case label.
        error: the exception raised by the run, if any.

    Returns:
        None.
    '''
    if error is not None:
        report.product.append('%s: the run aborted with %s: %s (expected: the library is handled and the run continues with the others)' % (label, type(error).__name__, error))


def _synced(report: Report, label: str, box: Sandbox, drive: str) -> None:
    '''A library with files is synced once with the unchanged max-delete and snapshotted once with its tags.

    Args:
        report: the report to extend.
        label: the case label.
        box: the sandbox.
        drive: the drive id of the library.

    Returns:
        None.
    '''
    syncs = box.commands(drive, 'rclone', 'sync')
    if len(syncs) != 1 or syncs[0][syncs[0].index('--max-delete') + 1] != str(box.cfg['max_delete']):
        report.product.append('%s: %s was synced %d time(s), expected once with --max-delete %s' % (label, drive, len(syncs), box.cfg['max_delete']))
    if len(box.snapshots_of(drive)) != 1 or box.tree(box.mirror(drive)) != {name: hashlib.sha256((drive + ':' + text).encode()).hexdigest() for name, text in FILES.items()}:
        report.product.append('%s: %s has %d snapshot(s) and a mirror that differs from its source, expected one snapshot of the mirror' % (label, drive, len(box.snapshots_of(drive))))


def control(report: Report) -> None:
    '''Control: a library with files is synced and snapshotted as before; a failure is a defect of the sandbox, never of the product.

    Args:
        report: the report to extend.

    Returns:
        None.
    '''
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
    '''A never backed up empty library: skipped, status empty, nothing copied or created, no snapshot, no error, the run does not abort.

    Args:
        report: the report to extend.

    Returns:
        None.
    '''
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
        found = _run_record(report, label, value, error, {NEW_EMPTY: 'empty'}, 'ok')
        if found and found[NEW_EMPTY][1]:
            report.product.append('%s: an error %r is recorded for the skipped empty library' % (label, found[NEW_EMPTY][1]))
    finally:
        box.close()


def emptied_library_not_synced_error(report: Report) -> None:
    '''A library with snapshots that is now empty: not synced, mirror and snapshots untouched, status source_emptied, an error recorded.

    Args:
        report: the report to extend.

    Returns:
        None.
    '''
    label = 'BE1 emptied_library_not_synced_error'
    box = Sandbox()
    try:
        box.seed_backed_up(EMPTIED)
        box.remote[EMPTIED] = {}
        before = _before(box, EMPTIED)
        value, error, bad = box.run([EMPTIED])
        _untouched(report, label, box, EMPTIED, before)
        found = _run_record(report, label, value, error, {EMPTIED: 'source_emptied'}, 'failed')
        recorded = bool(found and found[EMPTIED][1]) or _logged(box, EMPTIED, bad)
        if not recorded:
            report.product.append('%s: no error is recorded for %s (neither in the run record nor as a warning or error log naming the library); raised %s' % (label, EMPTIED, '%s: %s' % (type(error).__name__, error) if error else 'nothing'))
    finally:
        box.close()


def mixed_run_continues(report: Report) -> None:
    '''One empty, one emptied and one ok library in one run (the ok one sorts last): the ok library is backed up, the others are handled.

    Args:
        report: the report to extend.

    Returns:
        None.
    '''
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
        found = _run_record(report, label, value, error, {NEW_EMPTY: 'empty', EMPTIED: 'source_emptied', FULL: 'ok'}, 'partial')
        if not ((found and found[EMPTIED][1]) or _logged(box, EMPTIED, bad)):
            report.product.append('%s: no error is recorded for %s' % (label, EMPTIED))
        if found and (found[NEW_EMPTY][1] or found[FULL][1]):
            report.product.append('%s: an error is recorded for the empty or the ok library: %r' % (label, {k: v[1] for k, v in found.items() if k != EMPTIED and v[1]}))
    finally:
        box.close()


def exit_codes(report: Report) -> None:
    '''D3: the process exit code of one backup cycle is 0 for ok and 1 for partial and for failed (the status values come from the real cases above).

    Args:
        report: the report to extend.

    Returns:
        None.
    '''
    box = Sandbox()
    try:
        for status, wanted in (('ok', 0), ('partial', 1), ('failed', 1)):
            record = {'status': status, 'libraries': []}
            data = box.tmp / 'data'
            patches: tuple[Any, ...] = (mock.patch.object(box.sb, 'configure_logging', lambda *a, **k: None), mock.patch.object(box.sb.Path, 'is_mount', lambda self: True),
                                        mock.patch.object(box.sb, 'load_config', lambda path: dict(box.cfg, required_mountpoint=data.resolve())),
                                        mock.patch.object(box.sb, 'preflight', lambda cfg: None), mock.patch.object(box.sb, 'assert_repository', lambda cfg: None),
                                        mock.patch.object(box.sb, 'discover', lambda *a, **k: {}), mock.patch.object(box.sb, 'backup_libraries', lambda *a, **k: record))
            for item in patches:
                item.start()
            try:
                code = box.sb.main(['--config', str(box.tmp / 'backup.json'), '--data', str(data)])
            except BaseException as exc:
                code = 'raised %s: %s' % (type(exc).__name__, exc)
            finally:
                for item in patches:
                    item.stop()
            if code != wanted:
                report.product.append('BE1 exit code of a run with status %s: %r, expected %d (ok 0, partial 1, failed 1)' % (status, code, wanted))
    finally:
        box.close()


def run_all(report: Report) -> None:
    '''Run the control and the three cases of row BE1.

    Args:
        report: the report to extend.

    Returns:
        None.
    '''
    control(report)
    empty_new_library_skipped(report)
    emptied_library_not_synced_error(report)
    mixed_run_continues(report)
    exit_codes(report)
    report.info.append('isolation: temporary directory under .test-run only; stub rclone and restic in this process, subprocess refused, host paths '
                       'and network never reached; run status, record form and exit 0/1/1 are asserted (D3, approved)')
