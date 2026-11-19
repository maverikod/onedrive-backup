'''rclone_writable_state: the service uses a writable copy of rclone.conf in a service-owned state directory (row PL11, decision D10).

Mode: script fixture over a COPY of packaging/docker-run.sh plus source-static checks of the configuration files; nothing of the host
(rclone.conf, /var/lib/onedrive-backup/secrets, the restic repository, /srv/archive, /srv/backup) is read or written and no real
container is touched. Fixture values are sentinels, never real credentials, and no output may contain them (W7).

Contract (10.16.4): /secrets stays mounted readonly (original rclone.conf S, restic-password, api-credentials); the new directory mount
type=bind,src=<rclone state directory>,dst=/rclone-state is read-write. The state directory is ONEDRIVE_RCLONE_STATE_DIR, default
/var/lib/onedrive-backup/rclone-state, created by postinst 0700 onedrive-backup and verified by docker-run.sh start (exists, not a
symlink, mode 0700, owner onedrive-backup) or start refuses with its own message. The copy C is <state>/rclone.conf, mode 0600, owner
onedrive-backup. Seeding in start before docker run: S missing or empty -> no seeding, restricted scaffold, C untouched; S present and C
absent or empty -> C is written by a temporary file in the state directory renamed onto C; S newer than C -> C is replaced the same way;
otherwise C is kept untouched, so a token refreshed by rclone survives a restart. discover, init, check and backup refuse with
'rclone state copy unavailable' (exit 1, no docker exec) when C is missing or empty. A copy wider than 0600 or foreign-owned is refused.
In-container: config/backup.json and packaging/api-backup.json have rclone_config /rclone-state/rclone.conf, password_file stays
/secrets/restic-password; sharepoint_discover_cli admits rclone_config under /rclone-state and refuses /secrets/rclone.conf and
/tmp/untrusted.conf with RCLONE_CONFIG_PATH_UNSAFE.
'''

from __future__ import annotations

import importlib
import json
import os
import secrets as token_source
import sys
import tempfile
import time
from pathlib import Path
from unittest import mock

from pipeline import fixtures, postinstfix
from pipeline.report import Report

ROOT = Path(__file__).resolve().parents[2]
RUN = ROOT / 'packaging' / 'docker-run.sh'
PREEXISTING_STATE = ('Missing private secrets directory', 'Secrets directory must be mode 0700', 'Secrets directory owner invalid')
BLOCKED = (['init'], ['check'], ['backup'], ['backup', '--dry-run'], ['discover'], ['discover', '--dry-run'])
SENTINELS: list[str] = []


def _sentinel(kind: str) -> str:
    value = 'SENTINEL-%s-%s' % (kind, token_source.token_hex(8))
    SENTINELS.append(value)
    return value


def _quiet(report: Report, label: str, result: fixtures.Result) -> None:
    '''W7: no output of a run contains a sentinel value.'''
    for value in SENTINELS:
        if value in result.out or value in result.err or any(value in part for call in result.calls for part in call):
            report.product.append('W7 %s: the content of a rclone configuration shows in the output or in a command argument' % label)
            return


def _state_mode(path: Path) -> int:
    return path.stat().st_mode & 0o777


def _seed_host(host: fixtures.Host, *, s: str | None, c: str | None, s_age: int = 1000, c_age: int = 0) -> None:
    '''Write S and C with the given sentinels (None removes the file); ages are seconds in the past of their modification time.'''
    now = time.time()
    for path, text, age in ((host.secrets / 'rclone.conf', s, s_age), (host.state / 'rclone.conf', c, c_age)):
        if text is None:
            path.unlink(missing_ok=True)
            continue
        path.write_text(text, encoding='utf-8')
        path.chmod(0o600)
        os.utime(path, (now - age, now - age))


def _start(host: fixtures.Host) -> fixtures.Result:
    return host.run(RUN, 'start')


def _mounts(report: Report) -> None:
    with fixtures.host() as host:
        _seed_host(host, s=_sentinel('S'), c=_sentinel('C'))
        result = _start(host)
        runs = result.docker('run')
        _quiet(report, 'start baseline', result)
        if result.rc != 0 or not runs:
            report.product.append('W1 start with a correct state directory: exit %d, container started %s, stderr: %s'
                                  % (result.rc, bool(runs), result.err.strip()[:200]))
            return
        mounts = [item for index, item in enumerate(runs[0]) if index and runs[0][index - 1] == '--mount']
        by_dst = {next((part[4:] for part in item.split(',') if part.startswith('dst=')), ''): item for item in mounts}
        secrets_mount, state_mount = by_dst.get('/secrets', ''), by_dst.get('/rclone-state', '')
        if not secrets_mount or 'readonly' not in secrets_mount.split(','):
            report.product.append('W1 /secrets is not mounted readonly: %r' % secrets_mount)
        if not state_mount:
            report.product.append('W1 no /rclone-state mount; mounts: %s' % sorted(by_dst))
        elif 'readonly' in state_mount.split(',') or ('src=%s' % host.state) not in state_mount.split(',') \
                or 'type=bind' not in state_mount.split(','):
            report.product.append('W1 /rclone-state must be a read-write bind mount of the state directory %s: %r' % (host.state, state_mount))
        for item in mounts:
            if 'src=%s' % host.secrets in item.split(',') and 'readonly' not in item.split(','):
                report.product.append('W1 a mount maps the secrets directory read-write: %r' % item)
        if 'readonly' not in by_dst.get('/config', '').split(','):
            report.product.append('W1 /config is not mounted readonly: %r' % by_dst.get('/config'))
        if 'type=bind,src=%s,dst=/data' % host.data not in mounts:
            report.product.append('W1 /data is not bound from the data directory: %s' % sorted(mounts))
    with postinstfix.Postinst() as host:
        if host.survivors:
            report.env.append('the postinst copy still names the host paths %s after the rewrite; not run' % host.survivors)
            return
        host.data.mkdir(mode=0o750)
        host.set_default(None)
        result = host.run()
        if not host.state.is_dir() or _state_mode(host.state) != 0o700:
            report.product.append('W1 postinst did not create the state directory %s with mode 0700: exit %d, exists %s'
                                  % (host.state, result.rc, host.state.is_dir()))
        elif not any(call[:6] == ['-d', '-m', '0700', '-o', 'onedrive-backup', '-g'] and str(host.state) in call
                     for call in result.installs()):
            report.product.append('W1 postinst did not create the state directory with install -d -m 0700 -o onedrive-backup -g onedrive-backup')


def _seeding(report: Report) -> None:
    # (label, C content: None absent, '' empty, 'copy' a sentinel, age of S, age of C in seconds, expected outcome)
    cases = (('S present, C absent', None, 1000, 0, 'seed'), ('S present, C empty', '', 1000, 0, 'seed'),
             ('S present, C newer', 'copy', 1000, 0, 'keep'), ('S present, C as new as S', 'copy', 1000, 1000, 'keep'),
             ('S newer than C', 'copy', 1000, 5000, 'reseed'))
    for label, kind, s_age, c_age, outcome in cases:
        with fixtures.host() as host:
            secret_text = _sentinel('S')
            copy_text = _sentinel('C') if kind == 'copy' else kind
            _seed_host(host, s=secret_text, c=copy_text, s_age=s_age, c_age=c_age)
            copy = host.state / 'rclone.conf'
            before = copy.stat().st_mtime_ns if copy.exists() else None
            result = _start(host)
            _quiet(report, 'seeding ' + label, result)
            name = 'W2 start, %s' % label
            if result.rc != 0 or not result.docker('run'):
                report.product.append('%s: exit %d, container started %s, stderr: %s'
                                      % (name, result.rc, bool(result.docker('run')), result.err.strip()[:200]))
                continue
            text = copy.read_text(encoding='utf-8') if copy.is_file() else None
            moves = [call for call in result.calls if call[0] == 'mv' and call[-1] == str(copy)]
            if outcome == 'keep':
                if text != copy_text or copy.stat().st_mtime_ns != before or moves:
                    report.product.append('%s: the state copy was touched; a token refreshed by rclone must survive a restart' % name)
                continue
            if text != secret_text:
                report.product.append('%s: the state copy does not hold the original (%s expected): %s'
                                      % (name, outcome, 'absent' if text is None else 'other content'))
                continue
            if _state_mode(copy) != 0o600:
                report.product.append('%s: the state copy has mode %o, expected 600' % (name, _state_mode(copy)))
            if copy.stat().st_uid != os.getuid():
                report.product.append('%s: the state copy is not owned by the service user' % name)
            if not moves or os.path.dirname(moves[-1][-2]) != str(host.state) or moves[-1][-2] == str(copy):
                report.product.append('%s: the copy did not appear by renaming a temporary file of the state directory (mv calls: %d)'
                                      % (name, len(moves)))
            if (host.secrets / 'rclone.conf').read_text(encoding='utf-8') != secret_text:
                report.product.append('%s: the original rclone.conf was changed' % name)
    for label, secret_text in (('S absent', None), ('S empty', '')):
        with fixtures.host() as host:
            copy_text = _sentinel('C')
            _seed_host(host, s=secret_text, c=copy_text, c_age=0)
            copy = host.state / 'rclone.conf'
            before = copy.stat().st_mtime_ns
            result = _start(host)
            _quiet(report, 'seeding ' + label, result)
            runs = result.docker('run')
            if result.rc != 0 or not runs or 'ONEDRIVE_SCAFFOLD_MODE=1' not in runs[0]:
                report.product.append('W2 start, %s: expected the restricted scaffold start (ONEDRIVE_SCAFFOLD_MODE=1): exit %d, container started %s'
                                      % (label, result.rc, bool(runs)))
            if copy.read_text(encoding='utf-8') != copy_text or copy.stat().st_mtime_ns != before:
                report.product.append('W2 start, %s: the state copy was deleted or changed' % label)


def _unsafe_state(report: Report) -> None:
    def symlink(host: fixtures.Host) -> None:
        real = host.tmp / 'real-state'
        host.state.rename(real)
        host.state.symlink_to(real)

    def missing(host: fixtures.Host) -> None:
        for item in host.state.iterdir():
            item.unlink()
        host.state.rmdir()

    def wide(host: fixtures.Host) -> None:
        host.state.chmod(0o755)

    def foreign(host: fixtures.Host) -> None:
        os.chown(host.state, 65534, 65534)

    def wide_copy(host: fixtures.Host) -> None:
        (host.state / 'rclone.conf').chmod(0o644)

    def foreign_copy(host: fixtures.Host) -> None:
        os.chown(host.state / 'rclone.conf', 65534, 65534)

    cases = [('symlink', symlink, False), ('missing', missing, False), ('mode 0755', wide, False), ('copy mode 0644', wide_copy, False),
             ('foreign owner', foreign, True), ('copy of a foreign owner', foreign_copy, True)]
    for label, damage, needs_root in cases:
        if needs_root and os.geteuid() != 0:
            report.info.append('W4 state %s needs root to be set up; probed only when the pipeline runs as root' % label)
            continue
        with fixtures.host() as host:
            _seed_host(host, s=_sentinel('S'), c=_sentinel('C'))
            damage(host)
            result = _start(host)
            _quiet(report, 'unsafe state ' + label, result)
            line = result.err.strip()
            if result.rc == 0 or result.docker('run') or not line:
                report.product.append('W4 start with the state %s: exit %d, container started %s, stderr %r; expected a refusal with its own message'
                                      % (label, result.rc, bool(result.docker('run')), line[:200]))
            elif line in PREEXISTING_STATE or not ('rclone' in line.lower() or str(host.state) in line):
                report.product.append('W4 start with the state %s: the refusal %r is not a message of its own (it must name the rclone state)' % (label, line))


def _missing_copy(report: Report) -> None:
    for args in BLOCKED:
        with fixtures.host() as host:
            _seed_host(host, s=_sentinel('S'), c=None)
            result = host.run(RUN, *args)
            _quiet(report, 'missing copy ' + ' '.join(args), result)
            exec_calls = result.docker('exec')
            if result.rc != 1 or exec_calls or 'rclone state copy unavailable' not in result.err.lower():
                report.product.append('W6 docker-run.sh %s with the state copy missing: exit %d, docker exec calls %d, stderr %r; expected exit 1, '
                                      'no docker exec and "rclone state copy unavailable"'
                                      % (' '.join(args), result.rc, len(exec_calls), result.err.strip()[:160]))


def _configuration(report: Report) -> None:
    for rel in ('config/backup.json', 'packaging/api-backup.json'):
        try:
            config = json.loads((ROOT / rel).read_text(encoding='utf-8'))
        except (OSError, ValueError) as exc:
            report.product.append('W5 %s cannot be read: %s' % (rel, exc))
            continue
        if not str(config.get('rclone_config', '')).startswith('/rclone-state/'):
            report.product.append('W5 %s rclone_config is %r, expected /rclone-state/rclone.conf' % (rel, config.get('rclone_config')))
        if config.get('password_file') != '/secrets/restic-password':
            report.product.append('W5 %s password_file is %r, expected /secrets/restic-password' % (rel, config.get('password_file')))
    for item in (str(fixtures.SRC), str(ROOT)):
        if item not in sys.path:
            sys.path.insert(0, item)
    cli = importlib.import_module('onedrive_api.sharepoint_discover_cli')
    base = importlib.import_module('onedrive_api.sharepoint_base')
    verdicts = {'/rclone-state/rclone.conf': 'accepted', '/secrets/rclone.conf': 'RCLONE_CONFIG_PATH_UNSAFE',
                '/tmp/untrusted.conf': 'RCLONE_CONFIG_PATH_UNSAFE'}
    fixtures.WORK.mkdir(exist_ok=True)
    saved = os.environ.get('ONEDRIVE_SCAFFOLD_MODE')
    os.environ['ONEDRIVE_SCAFFOLD_MODE'] = '0'
    try:
        with tempfile.TemporaryDirectory(prefix='w5-', dir=str(fixtures.WORK)) as raw:
            for path, wanted in verdicts.items():
                config = Path(raw) / 'backup.json'
                config.write_text(json.dumps({'rclone_config': path}), encoding='utf-8')
                stop = base.DiscoveryError('FIXTURE_STOP')
                with mock.patch.object(Path, 'is_mount', return_value=True), \
                        mock.patch.object(cli.EntraCredentials, 'from_rclone', side_effect=stop):
                    try:
                        cli.discover(config, raw, dry_run=True)
                        got = 'returned'
                    except base.DiscoveryError as exc:
                        got = 'accepted' if exc.code == 'FIXTURE_STOP' else exc.code
                if got != wanted:
                    report.product.append('W5 sharepoint_discover_cli with rclone_config %s answered %s, expected %s' % (path, got, wanted))
    finally:
        if saved is None:
            os.environ.pop('ONEDRIVE_SCAFFOLD_MODE', None)
        else:
            os.environ['ONEDRIVE_SCAFFOLD_MODE'] = saved


def run() -> None:
    '''Raise CheckFailure when the service does not use a writable copy of rclone.conf kept in its own state directory.'''
    SENTINELS.clear()
    report = Report()
    _mounts(report)
    _seeding(report)
    _unsafe_state(report)
    _missing_copy(report)
    _configuration(report)
    report.info.append('host proof, read-only, with terminal_host_exec: docker inspect Mounts shows /secrets RW=false and /rclone-state RW=true; '
                       'the state directory is 0700 onedrive-backup; after a run longer than one token lifetime the log has no "Failed to save config" line')
    report.finish('rclone_writable_state')
