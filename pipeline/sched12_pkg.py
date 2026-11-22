'''Revision 12 packaging, run record and host checks (matrix TODO 10.20.5, 10.20.6 PL18, 10.20.8 PL15, 10.20.10).

timer_retired (PK1-PK6): COPIES of packaging/prerm and packaging/postinst run over the stateful systemctl stub of pipeline.timerfix, with a
systemctl show answer added; nothing of the real host is read or written. run_records (RR1-RR5): backup_run.main runs in a temporary
data directory with the backup stubbed; no backup is started. schedule_host_timer: read-only systemctl queries on the host the
pipeline runs on (the service host); when systemctl is not there the check is an ENVIRONMENT finding.
'''

from __future__ import annotations

import json
import logging
import os
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any
from unittest import mock

from pipeline import sched12, timerfix
from pipeline.report import Report

ROOT = timerfix.postinstfix.ROOT
UNITS = ('onedrive-backup.timer', 'onedrive-backup.service')
OLD = {'OnCalendar': '*-*-* 02:30:00', 'RandomizedDelaySec': '15min', 'Persistent': 'yes'}
WRAPPER = ('#!' + sys.executable + '\nimport json, os, sys\nsys.path.insert(0, %r)\nfrom pipeline.host_stubs import main\n'
           'args = sys.argv[1:]\nif args[:1] == ["show"] and os.environ.get("STUB_SHOW"):\n'
           '    props = json.loads(os.environ["STUB_SHOW"]).get(args[1], {})\n'
           '    for key, value in props.items():\n        print("%%s=%%s" %% (key, value))\n    sys.exit(0)\nsys.exit(main("systemctl"))\n')
CHILD = ('import sys\nsys.path[:0] = [%r]\nfrom onedrive_api import backup_run, sharepoint_backup\nsharepoint_backup.main = lambda argv=None: 0\n'
         'backup_run.index_new_snapshots = lambda: None\nfor _ in range(125):\n    backup_run.main([])\n')


class Host(timerfix.Packaging):
    '''A temporary host whose systemctl stub also answers show.

    Attributes:
        runs: the prerm and postinst runs of the last upgrade.
    '''

    def __init__(self) -> None:
        '''Replace the systemctl stub by a wrapper that answers show from STUB_SHOW.'''
        super().__init__()
        stub = self.bin / 'systemctl'
        stub.write_text(WRAPPER % str(ROOT), encoding='utf-8')
        stub.chmod(0o755)
        self.runs: list[Any] = []

    def __enter__(self) -> 'Host':
        '''Enter the context.

        Returns:
            This host.
        '''
        return self

    def upgrade(self, state: tuple[bool, bool] | None, old: dict[str, str] | None = None) -> None:
        '''Run prerm upgrade and postinst configure of an upgrade over a timer in the given (enabled, active) state.

        Args:
            state: the state of the old timer, or None for a fresh install (no unit state at all).
            old: the properties systemctl show answers for the old timer.

        Returns:
            None.
        '''
        if state is not None:
            self.set_units(timer=state, api=(True, True))
            self.extra_env['STUB_SHOW'] = json.dumps({timerfix.TIMER: dict(old or OLD)})
        self.runs = [self.package_step('prerm', 'upgrade', '0.3.22'), self.package_step('postinst', 'configure', '0.3.22' if state is not None else '')]

    def schedule(self) -> Path:
        '''Return the schedule file path of the fixture.

        Returns:
            The path under the data directory.
        '''
        return self.data / 'schedule' / 'schedule.cron'

    def called(self, word: str) -> bool:
        '''Return True when a recorded systemctl call of the last upgrade holds the word.

        Args:
            word: an argument such as daemon-reload.

        Returns:
            True when one call holds it.
        '''
        return any(call[0] == 'systemctl' and word in call for run in self.runs for call in run.calls)


def _file(report: Report, label: str, host: Host, enabled: bool) -> None:
    '''PRODUCT finding unless the schedule file exists with the default entry, the modes and ENABLED as wanted.

    Args:
        report: the findings collector.
        label: the case id.
        host: the fixture host.
        enabled: the ENABLED value the file must carry (yes, or absent, versus no).

    Returns:
        None.
    '''
    path = host.schedule()
    if not path.is_file():
        report.product.append('%s: packaging/postinst created no %s (10.20.8 PK5)' % (label, path.relative_to(host.tmp)))
        return
    text = path.read_text(encoding='utf-8')
    modes = (path.stat().st_mode & 0o777, path.parent.stat().st_mode & 0o777)
    off = 'ENABLED=no' in text
    if '30 2 * * *' not in text or off == enabled or modes != (0o600, 0o700):
        report.product.append('%s: schedule file modes %s, ENABLED=no %s, default entry %s; expected modes (0o600, 0o700), ENABLED=no %s and the entry 30 2 * * *' % (label, tuple(oct(item) for item in modes), off, '30 2 * * *' in text, not enabled))


def _pk(report: Report) -> None:
    '''PK1-PK3: an upgrade over an active timer retires it, an upgrade over a paused timer keeps the pause, a fresh install makes a paused schedule.

    Args:
        report: the findings collector.

    Returns:
        None.
    '''
    shipped = [name for name in UNITS if (ROOT / 'packaging' / name).is_file()]
    if shipped:
        report.product.append('PK1 the package still ships %s in packaging/ (10.20.8: the new package ships no timer and no oneshot service)' % shipped)
    for label, state in (('PK1 upgrade over an enabled and active timer', (True, True)), ('PK2 upgrade over a disabled timer', (False, False))):
        with Host() as host:
            if host.survivors:
                report.env.append('%s: the script copies still name host paths %s; not run' % (label, host.survivors))
                continue
            host.upgrade(state)
            failed = [run.err.strip()[:120] for run in host.runs if run.rc != 0]
            now = host.unit_state(timerfix.TIMER)
            if failed or now != (False, False):
                report.product.append('%s: script errors %s, the timer is enabled %s active %s afterwards, expected disabled and stopped (systemctl disable --now called: %s)' % (label, failed, now[0], now[1], host.called('--now')))
            if state == (True, True) and not host.called('daemon-reload'):
                report.product.append('PK1 systemctl daemon-reload was not called after the unit files were retired')
            _file(report, label, host, state == (True, True))
            if state == (False, False) and 'schedule' not in host.runs[-1].out.lower():
                report.product.append('PK2 the postinst printed no notice about the paused schedule: %r' % host.runs[-1].out[:80])
    with Host() as host:
        host.upgrade(None)
        if [call for call in host.calls_naming(timerfix.TIMER)]:
            report.product.append('PK3 a fresh install called systemctl for the timer: %s' % host.calls_naming(timerfix.TIMER))
        _file(report, 'PK3 fresh install', host, False)


def _pk456(report: Report) -> None:
    '''PK4 remove, PK5 the file is created only when absent, PK6 the migration record and the NOT MIGRATED notice.

    Args:
        report: the findings collector.

    Returns:
        None.
    '''
    with Host() as host:
        host.set_units(timer=(True, True), api=(True, True))
        done = host.package_step('prerm', 'remove')
        if done.rc != 0 or host.unit_state(timerfix.TIMER) != (False, False):
            report.product.append('PK4 prerm remove: exit %d, the old timer is %s, expected exit 0 and disabled and stopped' % (done.rc, host.unit_state(timerfix.TIMER)))
    with Host() as host:
        host.schedule().parent.mkdir(mode=0o700)
        host.schedule().write_text('# the operator text\n', encoding='utf-8')
        host.upgrade((True, True))
        if host.schedule().read_text(encoding='utf-8') != '# the operator text\n':
            report.product.append('PK5 an existing schedule file was overwritten by the postinst; it must be created only when absent')
    for label, props, notice in (('PK6 default timer', OLD, False), ('PK6 changed timer', dict(OLD, OnCalendar='*-*-* 03:10:00'), True)):
        with Host() as host:
            host.upgrade((True, True), props)
            record = host.varlib / 'timer-migration.txt'
            text = record.read_text(encoding='utf-8') if record.is_file() else ''
            said = 'NOT MIGRATED: re-enter the schedule' in ''.join(run.out for run in host.runs)
            if not record.is_file() or record.stat().st_mode & 0o777 != 0o600 or any(key not in text for key in OLD) or said != notice:
                report.product.append('%s: timer-migration.txt exists %s (mode 0600, holds OnCalendar, RandomizedDelaySec, Persistent), NOT MIGRATED notice printed %s, expected the record and the notice %s' % (label, record.is_file(), said, notice))


def timer_retired() -> None:
    '''Raise CheckFailure when the package keeps the timer or does not create the schedule file as 10.20.8 requires.

    Returns:
        None.
    '''
    report = Report()
    for body in (_pk, _pk456):
        try:
            body(report)
        except Exception as exc:  # noqa: BLE001 - a script or fixture failure is a finding, never a skip
            report.product.append('%s: raised %s: %s' % (body.__name__, type(exc).__name__, str(exc)[:200]))
    report.finish('timer_retired')


def _lines(base: Path) -> list[dict]:
    '''Return the parsed lines of runs.jsonl under the data directory, empty when there is none.

    Args:
        base: the temporary data directory.

    Returns:
        The records.
    '''
    path = base / 'schedule' / 'runs.jsonl'
    return [json.loads(line) for line in path.read_text(encoding='utf-8').splitlines() if line] if path.is_file() else []


def _runs(report: Report, mod: Any, base: Path) -> None:
    '''RR1-RR4: start and end records, the end record in a finally, an unwritable file does not stop the run, a dry run is marked.

    Args:
        report: the findings collector.
        mod: the product module backup_run.
        base: the temporary data directory.

    Returns:
        None.
    '''
    shared = sys.modules[mod.__name__.rsplit('.', 1)[0] + '.sharepoint_backup']
    for code in (0, 1, 2):
        with mock.patch.object(shared, 'main', return_value=code), mock.patch.object(mod, 'index_new_snapshots'):
            got = mod.main([])
        pairs = _lines(base)[-2:]
        start, end = (pairs + [{}, {}])[:2]
        if got != code or start.get('event') != 'start' or start.get('trigger') != 'manual' or start.get('pid') != os.getpid() or end.get('event') != 'end' or end.get('exit_code') != code or end.get('run_id') != start.get('run_id'):
            report.product.append('RR1 exit %d: main returned %s and runs.jsonl ends with %s, expected a start line (trigger manual, this pid) and an end line with the same run_id and exit_code %d' % (code, got, pairs, code))
    with mock.patch.object(shared, 'main', side_effect=RuntimeError('boom')), mock.patch.object(mod, 'index_new_snapshots'):
        try:
            mod.main([])
        except RuntimeError:
            pass
    tail = _lines(base)[-2:]
    if [item.get('event') for item in tail] != ['start', 'end'] or len({item.get('run_id') for item in tail}) != 1:
        report.product.append('RR2 a run that raises leaves %s at the end of runs.jsonl, expected the start line and an end line of the same run' % tail)
    with mock.patch.object(shared, 'main', return_value=0), mock.patch.object(mod, 'index_new_snapshots'):
        mod.main(['--dry-run'])
    if not any(item.get('event') == 'start' and item.get('dry_run') is True for item in _lines(base)[-2:]):
        report.product.append('RR4 a --dry-run start line carries no dry_run true: %s' % _lines(base)[-2:])
    with tempfile.TemporaryDirectory() as other:
        (Path(other) / 'schedule').write_text('not a directory', encoding='utf-8')
        handler, seen = logging.Handler(), []
        handler.emit = lambda record: seen.append(record)  # type: ignore[method-assign]
        logging.getLogger().addHandler(handler)
        os.environ['ONEDRIVE_BACKUP_DATA'] = other
        try:
            with mock.patch.object(shared, 'main', return_value=1), mock.patch.object(mod, 'index_new_snapshots'):
                got = mod.main([])
        finally:
            logging.getLogger().removeHandler(handler)
            os.environ['ONEDRIVE_BACKUP_DATA'] = str(base)
        if got != 1 or not [item for item in seen if item.levelno == logging.WARNING]:
            report.product.append('RR3 with an unwritable runs.jsonl main returned %s and logged %d warnings, expected the exit code 1 unchanged and one WARNING' % (got, len([item for item in seen if item.levelno == logging.WARNING])))


def _concurrent(report: Report, base: Path) -> None:
    '''RR5: 1000 appends from four processes give a valid JSONL file with single-write lines under 4096 bytes.

    Args:
        report: the findings collector.
        base: the temporary data directory.

    Returns:
        None.
    '''
    env = dict(os.environ, ONEDRIVE_BACKUP_DATA=str(base))
    procs = [subprocess.Popen([sys.executable, '-c', CHILD % str(sched12.fixtures.SRC)], env=env, stderr=subprocess.PIPE, text=True) for _ in range(4)]
    errors = [proc.communicate(timeout=300)[1] for proc in procs]
    path = base / 'schedule' / 'runs.jsonl'
    raw = path.read_text(encoding='utf-8').splitlines() if path.is_file() else []
    good = 0
    for line in raw:
        try:
            good += isinstance(json.loads(line), dict) and len(line.encode('utf-8')) < 4096
        except ValueError:
            continue
    if len(raw) < 1000 or good != len(raw):
        report.product.append('RR5 four processes of 125 runs left %d lines of which %d are valid JSON objects under 4096 bytes, expected at least 1000 valid lines (child errors %s)' % (len(raw), good, [item.strip()[-120:] for item in errors if item.strip()]))


def run_records() -> None:
    '''Raise CheckFailure when backup_run does not write the run records of 10.20.5 for every start.

    Returns:
        None.
    '''
    report = Report()
    mod = sched12.load(report, 'run')
    if mod is not None:
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            os.environ['ONEDRIVE_BACKUP_DATA'] = tmp
            os.environ.pop('ONEDRIVE_RUN_TRIGGER', None)
            try:
                for body in (_runs, _concurrent):
                    try:
                        body(report, mod, base) if body is _runs else body(report, base)  # type: ignore[call-arg, arg-type]
                    except Exception as exc:  # noqa: BLE001 - product code that raises is a finding
                        report.product.append('%s: raised %s: %s' % (body.__name__, type(exc).__name__, str(exc)[:200]))
            finally:
                os.environ.pop('ONEDRIVE_BACKUP_DATA', None)
    report.finish('run_records')


def schedule_host_timer() -> None:
    '''Raise CheckFailure when the host still lists or enables onedrive-backup.timer (read-only systemctl queries).

    Returns:
        None.
    '''
    report = Report()
    try:
        listed = subprocess.run(['systemctl', 'list-timers', '--all', '--no-legend', '--no-pager'], capture_output=True, text=True, timeout=30, check=False)
        enabled = subprocess.run(['systemctl', 'is-enabled', 'onedrive-backup.timer'], capture_output=True, text=True, timeout=30, check=False)
    except (OSError, subprocess.SubprocessError) as exc:
        report.env.append('systemctl cannot be run here (%s: %s): this check needs the service host' % (type(exc).__name__, exc))
    else:
        lines = [line.strip() for line in listed.stdout.splitlines() if 'onedrive-backup.timer' in line]
        if lines or enabled.returncode == 0:
            report.product.append('10.20.8 U6: onedrive-backup.timer is still on the host: list-timers %s, is-enabled exit %d (%s); expected no such timer after the deploy' % (lines[:1], enabled.returncode, enabled.stdout.strip() or enabled.stderr.strip()))
    report.finish('schedule_host_timer')
