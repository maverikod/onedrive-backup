'''run_log: every backup run leaves a persistent run log and, on a non-zero exit, a reason (matrix row PL20, block SCHEDULE-REV12).

User goal (2026-11-25, task 121 after the 2026-11-24 `refused` run of task 118): the cause of a failed scheduled run must be findable
after the container is recreated. Cases RL1-RL4: the deployed image runs `python -m onedrive_api.backup_run` in a throw-away container
(no network, no host mount except a temporary data directory, no credentials, no backup guard passed), the run is refused by a guard and
the files it leaves in that temporary data directory are asserted. RL5 reads the production data volume read-only. Nothing under
/srv/archive/onedrive-backup is written, the production container is only inspected, no backup and no schedule is touched.
'''

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import tempfile
import uuid
from pathlib import Path
from typing import Any

from pipeline import archivefs
from pipeline.report import Report

CONTAINER = 'onedrive-backup'
MAX_REASON = 500
MAX_LOGS = 500
MAX_LOG_BYTES = 10 * 1024 * 1024 + 65536
SECRET = 'SeCrEt12345'
NAME = re.compile(r'^([0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12})\.log(\.[0-9]+)?$')
MODES = (0o600, 0o640)
SECRET_CONFIG = '/nonexistent/access_token=%s.json' % SECRET


def _docker(args: list[str], timeout: int = 120) -> subprocess.CompletedProcess[str]:
    '''Run one docker client command.

    Args:
        args: The arguments after docker.
        timeout: The limit in seconds.

    Returns:
        The completed process.
    '''
    return subprocess.run(['docker'] + args, capture_output=True, text=True, timeout=timeout, check=False)


def _image() -> tuple[str, int, int]:
    '''Return the image of the deployed container and the numeric user and group the image runs as.

    Returns:
        The image name with its tag, the uid and the gid.
    '''
    shown = _docker(['inspect', '--type', 'container', '--format', '{{.Config.Image}} {{.Config.User}}', CONTAINER])
    if shown.returncode != 0:
        raise OSError('docker inspect %s failed: %s' % (CONTAINER, shown.stderr.strip()[:200]))
    image, _, user = shown.stdout.strip().partition(' ')
    uid, _, gid = user.partition(':')
    return image, int(uid), int(gid or uid)


def _seed(logs: Path, uid: int, gid: int, count: int) -> None:
    '''Create old run log files, owned by the service user, to prove the retention bound.

    Args:
        logs: The run log directory to create.
        uid: The owner.
        gid: The group.
        count: The number of old files.

    Returns:
        None.
    '''
    logs.mkdir(mode=0o700)
    for index in range(count):
        path = logs / ('%08x-0000-4000-8000-000000000000.log' % index)
        path.write_text('old run %d\n' % index, encoding='utf-8')
        path.chmod(0o600)
        shutil.chown(path, uid, gid)
        stamp = 1577836800 + index
        os.utime(path, (stamp, stamp))
    shutil.chown(logs, uid, gid)


def _lines(path: Path) -> list[dict[str, Any]]:
    '''Return the JSON objects of a runs.jsonl file, [] when it is missing.

    Args:
        path: The file.

    Returns:
        The records in file order.
    '''
    if not path.is_file():
        return []
    return [json.loads(line) for line in path.read_text(encoding='utf-8').splitlines() if line.strip()]


def _one_run(image: str, uid: int, gid: int, scaffold: bool, config: str | None, seed: int) -> dict[str, Any]:
    '''Run the deployed image once in a throw-away container and return the facts about the files it left.

    Args:
        image: The deployed image.
        uid: The user of the container.
        gid: The group of the container.
        scaffold: True to refuse the run with the SCAFFOLD_ONLY guard.
        config: A --config argument, or None.
        seed: How many old run logs to create before the run.

    Returns:
        exit, tail, records, logs ({name: {mode, uid, size, text}}) and logs_dir_mode.
    '''
    box = Path(tempfile.mkdtemp(prefix='runlog-'))
    name = 'onedrive-backup-runlog-' + uuid.uuid4().hex[:8]
    try:
        shutil.chown(box, uid, gid)
        box.chmod(0o700)
        if seed:
            (box / 'schedule').mkdir(mode=0o700)
            shutil.chown(box / 'schedule', uid, gid)
            _seed(box / 'schedule' / 'logs', uid, gid, seed)
        env = ['-e', 'ONEDRIVE_BACKUP_DATA=/data', '-e', 'ONEDRIVE_RUN_TRIGGER=manual']
        env += ['-e', 'ONEDRIVE_SCAFFOLD_MODE=1'] if scaffold else []
        argv = ['run', '--rm', '--pull', 'never', '--name', name, '--network', 'none', '--user', '%d:%d' % (uid, gid), '--cap-drop', 'ALL',
                '--security-opt', 'no-new-privileges', '--entrypoint', 'python', '-v', '%s:/data' % box] + env
        argv += [image, '-m', 'onedrive_api.backup_run', '--data', '/data'] + (['--config', config] if config else [])
        done = _docker(argv, timeout=180)
        logs: dict[str, dict[str, Any]] = {}
        folder = box / 'schedule' / 'logs'
        for path in sorted(folder.iterdir()) if folder.is_dir() else []:
            info = path.stat()
            text = path.read_text(encoding='utf-8', errors='replace')[:20000] if info.st_size < MAX_LOG_BYTES else ''
            logs[path.name] = {'mode': info.st_mode & 0o777, 'uid': info.st_uid, 'size': info.st_size, 'text': text}
        return {'exit': done.returncode, 'tail': (done.stdout + done.stderr)[-300:], 'records': _lines(box / 'schedule' / 'runs.jsonl'), 'logs': logs,
                'logs_dir_mode': (folder.stat().st_mode & 0o777) if folder.is_dir() else None}
    finally:
        _docker(['rm', '-f', name], timeout=60)
        shutil.rmtree(box, ignore_errors=True)


def _refusal(report: Report, label: str, facts: dict[str, Any], expect: str, secret: bool) -> str | None:
    '''Assert the end record reason of one refused run.

    Args:
        report: The findings.
        label: The case id.
        facts: The result of _one_run.
        expect: Text that the reason must contain with the class BackupError, or '' when any text is accepted.
        secret: True when the secret marker must be absent from the reason.

    Returns:
        The run id, or None when the run left no start and end record.
    '''
    ends = [item for item in facts['records'] if item.get('event') == 'end']
    starts = [item for item in facts['records'] if item.get('event') == 'start']
    if facts['exit'] == 0 or len(starts) != 1 or len(ends) != 1:
        report.env.append('%s: the throw-away run did not end as a refused run: exit %s, %d start and %d end records, container output %r'
                          % (label, facts['exit'], len(starts), len(ends), facts['tail']))
        return None
    run_id = str(starts[0]['run_id'])
    end = ends[0]
    reason = end.get('reason')
    if not isinstance(reason, str) or not reason.strip():
        report.product.append('%s: the end record of a run with exit code %s has no non-empty string "reason": %s' % (label, end.get('exit_code'), json.dumps(end)[:300]))
    else:
        if len(reason) > MAX_REASON:
            report.product.append('%s: reason is %d characters, expected at most %d' % (label, len(reason), MAX_REASON))
        if expect and (expect not in reason or 'BackupError' not in reason):
            report.product.append('%s: reason %r must name the exception class BackupError and the message %s' % (label, reason[:200], expect))
        if secret and SECRET in reason:
            report.product.append('%s: reason carries the secret marker of the config path, expected it scrubbed' % label)
    return run_id


def _log_file(report: Report, label: str, facts: dict[str, Any], run_id: str | None, uid: int, expect: str, secret: bool) -> None:
    '''Assert the persistent run log of one refused run.

    Args:
        report: The findings.
        label: The case id.
        facts: The result of _one_run.
        run_id: The run id of the start record, or None.
        uid: The uid of the service user.
        expect: Text the log must contain, or ''.
        secret: True when the secret marker must be absent.

    Returns:
        None.
    '''
    entry = facts['logs'].get('%s.log' % run_id) if run_id else None
    if entry is None:
        report.product.append('%s: no <data>/schedule/logs/<run_id>.log after the run (run id %s, files %s)' % (label, run_id, sorted(facts['logs'])[:3]))
        return
    if entry['mode'] not in MODES or entry['uid'] != uid:
        report.product.append('%s: run log mode %o owner uid %d, expected mode 0600 or 0640 owned by uid %d' % (label, entry['mode'], entry['uid'], uid))
    if entry['size'] == 0 or (expect and expect not in entry['text']):
        report.product.append('%s: run log is %d bytes and lacks %r' % (label, entry['size'], expect))
    if secret and SECRET in entry['text']:
        report.product.append('%s: run log carries the secret marker of the config path, expected it scrubbed' % label)
    if entry['size'] > MAX_LOG_BYTES:
        report.product.append('%s: run log is %d bytes, expected at most %d' % (label, entry['size'], MAX_LOG_BYTES))


def _retention(report: Report, facts: dict[str, Any], run_id: str | None) -> None:
    '''Assert that 520 old run logs plus one new run leave at most MAX_LOGS runs and keep the new one.

    Args:
        report: The findings.
        facts: The result of _one_run with 520 seeded logs.
        run_id: The run id of the new run, or None.

    Returns:
        None.
    '''
    runs = {match.group(1) for match in map(NAME.match, facts['logs']) if match}
    oldest = '00000000-0000-4000-8000-000000000000.log'
    if len(runs) > MAX_LOGS or oldest in facts['logs'] or (run_id and run_id not in runs):
        report.product.append('RL4 retention: %d run logs after 520 old ones and one new run (new run kept: %s, oldest kept: %s), expected at most %d, '
                              'the oldest removed and the new one kept' % (len(runs), bool(run_id and run_id in runs), oldest in facts['logs'], MAX_LOGS))


def _live(report: Report) -> None:
    '''Assert read-only that the production data volume holds the run log directory (RL5).

    Args:
        report: The findings.

    Returns:
        None.
    '''
    folder = Path(archivefs.DEFAULT_DATA) / 'schedule' / 'logs'
    try:
        info = folder.stat()
    except FileNotFoundError:
        report.product.append('RL5 %s does not exist on the production data volume: no run log can survive a container recreation' % folder)
    except OSError as exc:
        report.env.append('RL5 %s cannot be read here (%s): this check needs the service host' % (folder, exc))
    else:
        if not folder.is_dir() or info.st_mode & 0o007:
            report.product.append('RL5 %s is not a directory closed to others (mode %o)' % (folder, info.st_mode & 0o777))


def run_log() -> None:
    '''Raise CheckFailure when a backup run leaves no persistent run log or no reason for its non-zero exit.

    Returns:
        None.
    '''
    report = Report()
    try:
        image, uid, gid = _image()
        guard = _one_run(image, uid, gid, True, None, 0)
        run_id = _refusal(report, 'RL1', guard, 'SCAFFOLD_ONLY', False)
        _log_file(report, 'RL2', guard, run_id, uid, 'SCAFFOLD_ONLY', False)
        hidden = _one_run(image, uid, gid, False, SECRET_CONFIG, 0)
        hid = _refusal(report, 'RL3', hidden, '', True)
        _log_file(report, 'RL3', hidden, hid, uid, '', True)
        seeded = _one_run(image, uid, gid, True, None, MAX_LOGS + 20)
        _retention(report, seeded, _refusal(report, 'RL4', seeded, 'SCAFFOLD_ONLY', False))
    except (OSError, ValueError, subprocess.SubprocessError) as exc:
        report.env.append('the throw-away run could not be made: %s: %s' % (type(exc).__name__, str(exc)[:300]))
    _live(report)
    report.finish('run_log')
