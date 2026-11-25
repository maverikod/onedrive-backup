'''Revision 14 run classification unit check (matrix TODO 10.23.R.3, 10.23.R.6 TR3; row PL25; check run_classification, block RUN-CLASS).

The REAL run function onedrive_api.backup_run.main (which calls sharepoint_backup.main and writes the run record and the run log) runs over a
temporary data directory with a fake discovery and a fake run_command; nothing reaches the service, rclone or restic. Seam, as in
tests/test_sharepoint_backup.py: the names load_config, preflight, exclusive_lock, assert_repository, discover and run_command of the module
onedrive_api.sharepoint_backup are replaced, Path.is_mount answers True and backup_run.index_new_snapshots does nothing. The outcome is read
from the END record of <data>/schedule/runs.jsonl (exit_code, reason) and from <data>/schedule/logs/<run_id>.log. TESTER ASSUMPTIONS (the coder
aligns the product): the outcome of a run is its end record, even when an unexpected exception leaves backup_run.main; a library is named in
the reason by its discovery name (the key name of the discovery library entry) or, failing that, by its drive id; the phase words of RR1 are
guard, discovery, library and unexpected (a guard refusal is judged by the guard code only, as on 0.3.28); the tool is the executable name
(rclone or restic) and the exit code is the number of the BackupError text of run_command; per-library isolation (O-RD3 B) means the fake sees
the commands of the second library after the first failed.
'''

from __future__ import annotations

import contextlib
import importlib
import io
import json
import logging
import os
import tempfile
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Callable
from unittest import mock

from pipeline import fixtures
from pipeline.report import Report

SITE = 'host,1,2'
LIBRARIES = (('drive-A', 'ДЕНЬГИ'), ('drive-B', 'ПЛАНЫ'))
PLANTED = ('SECRETTOKEN4711', 'abcdefghij0123456789', 'PASSW0RDVALUE')
FAILED_TEXT = 'Команда завершилась с кодом %d: %s'
STATUS_OF_CODE = {0: 'ok', 1: 'errors', 2: 'refused'}
Fault = Callable[[], BaseException]


def _config(root: Path, mirror: Path, data: Path) -> dict[str, Any]:
    '''Build the isolated local backup configuration of tests/test_sharepoint_backup.py plus the keys of sharepoint_backup.main.

    Args:
        root: a temporary directory.
        mirror: the mirror directory.
        data: the data directory, also the required mount point.

    Returns:
        The configuration dict.
    '''
    return {'mirror_dir': mirror, 'repository_dir': root / 'repo', 'rclone_bin': 'rclone', 'restic_bin': 'restic', 'rclone_config': root / 'rclone.conf',
            'password_file': root / 'password', 'onedrive_remote': 'onedrive:', 'max_delete': 100, 'transfers': 4, 'checkers': 8, 'allow_empty_source': False,
            'lock_file': root / 'lock', 'required_mountpoint': data}


def _report(libraries: tuple[tuple[str, str], ...]) -> dict[str, Any]:
    '''Build a complete, clean discovery report of one site and the given libraries.

    Args:
        libraries: (drive id, name) pairs.

    Returns:
        The discovery report.
    '''
    return {'complete': True, 'errors': [], 'sites': [{'site_id': SITE, 'source_status': 'ok'}],
            'libraries': [{'site_id': SITE, 'drive_id': drive, 'status': 'ok', 'name': name, 'display_name': name} for drive, name in libraries]}


def _read(folder: Path) -> str:
    '''Return the text of every file of a directory in name order, or an empty text.

    Args:
        folder: the directory.

    Returns:
        The concatenated texts.
    '''
    return ''.join(path.read_text(encoding='utf-8', errors='replace') for path in sorted(folder.glob('*'))) if folder.is_dir() else ''


def _drive(backup: Any, argv: list[str]) -> str:
    '''Name the library drive id a fake command belongs to (rclone: its drive option, restic: the mirror path of the drive).

    Args:
        backup: the module onedrive_api.sharepoint_backup.
        argv: the command.

    Returns:
        The drive id, or an empty text.
    '''
    if '--onedrive-drive-id' in argv:
        return argv[argv.index('--onedrive-drive-id') + 1]
    line = ' '.join(argv)
    return next((drive for drive, _ in LIBRARIES if backup.stable_key(drive) in line), '')


def run_once(modules: tuple[Any, Any], *, libraries: tuple[tuple[str, str], ...] = LIBRARIES[:1], faults: dict[tuple[str, str, str], Fault] | None = None,
             discovery: Fault | None = None, scaffold: bool = False, blocked: bool = False) -> SimpleNamespace:
    '''Run the real backup_run.main once over fakes and return what it left behind.

    Args:
        modules: (backup_run, sharepoint_backup).
        libraries: the (drive id, name) pairs the fake discovery reports.
        faults: (drive id, tool, verb) -> factory of the exception the fake run_command raises.
        discovery: factory of the exception the fake discovery raises, or None.
        scaffold: set ONEDRIVE_SCAFFOLD_MODE=1 (a guard refusal before discovery).
        blocked: make the mirror path unusable (its parent is a file), so the mirror write raises an OSError.

    Returns:
        A namespace: code (exit code of the end record or None), raised, reason, log, runs, calls, discovered.
    '''
    backup_run, backup = modules
    calls: list[tuple[str, str, str]] = []
    seen = {'discover': 0}

    def fake_run(command: list[str], env: dict[str, str] | None = None, *, capture: bool = False) -> str:
        '''Answer lsjson like a non-empty remote, record every command and raise the planned fault.

        Args:
            command: the argv.
            env: the environment, unused.
            capture: whether the output is wanted, unused.

        Returns:
            The command output.
        '''
        argv = [str(value) for value in command]
        verb = next((word for word in ('lsjson', 'sync', 'backup') if word in argv), '')
        key = (_drive(backup, argv), Path(argv[0]).name, verb)
        calls.append(key)
        if key in (faults or {}):
            raise (faults or {})[key]()
        return ('[]' if '-R' in argv else '[{"Name":"file.txt","IsDir":false}]') if verb == 'lsjson' else ''

    def fake_discover(*args: Any, **kwargs: Any) -> dict[str, Any]:
        '''Return the planned discovery report or raise the planned discovery error.

        Args:
            args: ignored.
            kwargs: ignored.

        Returns:
            The discovery report.
        '''
        seen['discover'] += 1
        if discovery is not None:
            raise discovery()
        return _report(libraries)

    logger = logging.getLogger('onedrive_backup')
    saved = (list(logger.handlers), logger.level)
    with tempfile.TemporaryDirectory(prefix='t123-class-') as tmp:
        root = Path(tmp).resolve()
        data = root / 'data'
        data.mkdir()
        (root / 'blocker').write_text('a file, not a directory', encoding='utf-8')
        cfg = _config(root, root / 'blocker' / 'mirror' if blocked else data / 'mirror', data)
        raised: BaseException | None = None
        with contextlib.ExitStack() as stack:
            stack.enter_context(mock.patch.dict(os.environ, {'ONEDRIVE_BACKUP_DATA': str(data)}))
            os.environ.pop('ONEDRIVE_SCAFFOLD_MODE', None)
            if scaffold:
                os.environ['ONEDRIVE_SCAFFOLD_MODE'] = '1'
            stack.enter_context(mock.patch.object(Path, 'is_mount', lambda self: True))
            for name, value in (('load_config', lambda path: cfg), ('preflight', lambda config: None), ('exclusive_lock', lambda path: contextlib.nullcontext()),
                                ('assert_repository', lambda config: None), ('discover', fake_discover), ('run_command', fake_run)):
                stack.enter_context(mock.patch.object(backup, name, value))
            stack.enter_context(mock.patch.object(backup_run, 'index_new_snapshots', lambda: None))
            stack.enter_context(contextlib.redirect_stdout(io.StringIO()))
            stack.enter_context(contextlib.redirect_stderr(io.StringIO()))
            try:
                backup_run.main(['--config', str(root / 'backup.json'), '--data', str(data)])
            except Exception as exc:  # noqa: BLE001 - an unexpected exception is the case under test
                raised = exc
        logger.handlers[:] = saved[0]
        logger.setLevel(saved[1])
        runs = (data / 'schedule' / 'runs.jsonl').read_text(encoding='utf-8') if (data / 'schedule' / 'runs.jsonl').is_file() else ''
        ends = [json.loads(line) for line in runs.splitlines() if line.strip().startswith('{') and '"end"' in line]
        end = ends[-1] if ends else {}
        return SimpleNamespace(code=end.get('exit_code'), raised=raised, reason=end.get('reason') or '', log=_read(data / 'schedule' / 'logs'), runs=runs,
                               calls=calls, discovered=seen['discover'])


def _tool_failure(tool: str, verb: str, code: int, extra: str = '') -> Fault:
    '''Build the factory of the BackupError that run_command raises for a failed tool.

    Args:
        tool: rclone or restic.
        verb: the sub-command.
        code: the exit code of the tool.
        extra: more text, for example a planted secret.

    Returns:
        The factory.
    '''
    error_class = importlib.import_module('onedrive_backup').BackupError
    return lambda: error_class(FAILED_TEXT % (code, '%s %s onedrive: /mirror %s' % (tool, verb, extra)))


def _verdict(outcome: SimpleNamespace, code: int, words: tuple[str, ...], lower: bool = True) -> list[str]:
    '''Compare the end record with the wanted exit code, its status and the words the reason must hold.

    Args:
        outcome: the result of run_once.
        code: the wanted exit code.
        words: the texts the reason must contain (compared in lower case when lower is true).
        lower: compare in lower case.

    Returns:
        The problems.
    '''
    found: list[str] = []
    if outcome.code != code:
        raised = '; raised %s' % type(outcome.raised).__name__ if outcome.raised else ''
        got = (outcome.code, STATUS_OF_CODE.get(outcome.code, '?'), code, STATUS_OF_CODE[code], raised)
        found.append('the end record has exit_code %r (%s), expected %d (%s)%s' % got)
    reason = outcome.reason.lower() if lower else outcome.reason
    missing = [word for word in words if (word.lower() if lower else word) not in reason]
    if missing or not outcome.reason or len(outcome.reason) > 500:
        found.append('the reason %r lacks %s or is empty or longer than 500 characters' % (outcome.reason[:160], missing))
    return found


def check_cases(modules: tuple[Any, Any], report: Report) -> None:
    '''Judge the eight cases of row PL25 (TR3) and add one finding per violated assertion.

    Args:
        modules: (backup_run, sharepoint_backup).
        report: the findings collector.

    Returns:
        None.
    '''
    discovery_error = modules[1].DiscoveryError
    first, second = LIBRARIES
    a_sync = (first[0], 'rclone', 'sync')

    def library_case(outcome: SimpleNamespace, tool: str, code: int) -> list[str]:
        '''Judge a failed library: exit 1, phase library, tool, exit code and one identity of the library in the reason.

        Args:
            outcome: the result of run_once.
            tool: the failed tool.
            code: its exit code.

        Returns:
            The problems.
        '''
        problems = _verdict(outcome, 1, ('library', tool, str(code)))
        if not any(word.lower() in outcome.reason.lower() for word in (first[1], first[0])):
            problems.append('the reason %r names neither the library %s nor its drive id %s' % (outcome.reason[:160], first[1], first[0]))
        return problems

    def guard() -> list[str]:
        '''Judge a guard refusal before discovery.'''
        outcome = run_once(modules, scaffold=True)
        problems = _verdict(outcome, 2, ('SCAFFOLD_ONLY',), lower=False)
        return problems + (['discovery ran (%d call) although a guard stopped the run before it' % outcome.discovered] if outcome.discovered else [])

    def discovery() -> list[str]:
        '''Judge a DiscoveryError.'''
        outcome = run_once(modules, discovery=lambda: discovery_error('DISCOVERY_FAILED'))
        return _verdict(outcome, 1, ('discovery', 'DISCOVERY_FAILED'))

    def unexpected() -> list[str]:
        '''Judge an unexpected exception.'''
        return _verdict(run_once(modules, faults={(first[0], 'rclone', 'lsjson'): lambda: RuntimeError('boom')}), 1, ('unexpected: RuntimeError',), lower=False)

    def both() -> list[str]:
        '''Judge two libraries where the first fails.'''
        outcome = run_once(modules, libraries=LIBRARIES, faults={a_sync: _tool_failure('rclone', 'sync', 5)})
        problems = library_case(outcome, 'rclone', 5)
        if (second[0], 'restic', 'backup') not in outcome.calls:
            problems.append('the second library %s was never attempted (commands seen: %s); O-RD3 B wants it attempted after the first failed' % (second[0], sorted(set(outcome.calls))))
        if second[0] not in outcome.log and second[1] not in outcome.log:
            problems.append('the run log holds no line of the second library %s' % second[0])
        return problems

    def secret() -> list[str]:
        '''Judge scrubbing of planted secrets in a tool failure and in an unexpected exception.'''
        text = 'access_token=%s password=%s Authorization: Bearer %s' % PLANTED
        plans = [('rclone failure', a_sync, _tool_failure('rclone', 'sync', 5, text)), ('unexpected exception', (first[0], 'rclone', 'lsjson'), lambda: RuntimeError(text))]
        problems: list[str] = []
        for label, key, fault in plans:
            outcome = run_once(modules, faults={key: fault})
            where = [place for place, body in (('reason', outcome.reason), ('log', outcome.log), ('runs.jsonl', outcome.runs)) if any(value in body for value in PLANTED)]
            if where:
                problems.append('a planted secret of the %s survives into %s' % (label, where))
            if not outcome.reason:
                problems.append('the %s left no reason' % label)
        return problems

    cases: tuple[tuple[str, Callable[[], list[str]]], ...] = (
        ('tr3_guard_refused', guard), ('tr3_discovery_errors', discovery),
        ('tr3_rclone_exit5', lambda: library_case(run_once(modules, faults={a_sync: _tool_failure('rclone', 'sync', 5)}), 'rclone', 5)),
        ('tr3_restic_exit1', lambda: library_case(run_once(modules, faults={(first[0], 'restic', 'backup'): _tool_failure('restic', 'backup', 1)}), 'restic', 1)),
        ('tr3_mirror_oserror', lambda: _verdict(run_once(modules, blocked=True), 1, ('library',))), ('tr3_unexpected', unexpected),
        ('tr3_second_library_attempted', both), ('tr3_secret_scrubbed', secret))
    for cid, case in cases:
        try:
            problems = case()
        except Exception as exc:  # noqa: BLE001 - a harness or product crash is a finding
            problems = ['raised %s: %s' % (type(exc).__name__, exc)]
        for problem in problems:
            report.product.append('PL25 %s: %s (10.23.R.3 EXIT-CODE RECLASSIFICATION)' % (cid, problem))
        report.info.append('PL25 %s: %s' % (cid, 'RED' if problems else 'GREEN'))


def run_classification(name: str) -> None:
    '''Run the eight TR3 cases of the real run function and finish the report.

    Args:
        name: the name of the named check.

    Returns:
        None.
    '''
    report = Report()
    fixtures.catalog_module()
    modules = (importlib.import_module('onedrive_api.backup_run'), importlib.import_module('onedrive_api.sharepoint_backup'))
    check_cases(modules, report)
    report.finish(name)
