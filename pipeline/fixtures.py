'''Disposable fixtures of the B3 checks.

CatalogFixture runs the real Catalog class of src/onedrive_api over a fake restic binary in a
temporary data directory. Host runs a copy of packaging/docker-run.sh (or another packaging script) with stub docker, mountpoint, findmnt, id,
install and mv commands on PATH, over a temporary configuration, secrets, rclone state and archive tree. run_wrapper runs a
copy of packaging/onedrive-backup-docker whose absolute paths are redirected to a recording stub.
All trees live under .test-run of the checkout and are removed afterwards.
'''

from __future__ import annotations

import contextlib
import importlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

from pipeline import archivefs

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / 'src'
WORK = ROOT / '.test-run'
SNAPSHOT_ID = 'a1b2c3d4' * 8
SECOND_ID = 'b2c3d4e5' * 8
STUBS = ('docker', 'mountpoint', 'findmnt', 'id', 'install', 'mv', 'chown', 'chgrp', 'adduser', 'systemctl')
WRAPPER_DOCKER_RUN = '/usr/lib/onedrive-backup/docker-run.sh'
WRAPPER_DEFAULTS = '/etc/default/onedrive-backup'


def _work_dir(prefix: str) -> Path:
    WORK.mkdir(exist_ok=True)
    return Path(tempfile.mkdtemp(prefix=prefix, dir=str(WORK)))


def _remove(tree: Path) -> None:
    for base, dirs, _files in os.walk(tree):
        for name in dirs:
            with contextlib.suppress(OSError):
                os.chmod(os.path.join(base, name), 0o755)
    shutil.rmtree(tree, ignore_errors=True)


def catalog_module():
    '''Import onedrive_api.catalog from the checkout source tree.'''
    for item in (str(SRC), str(ROOT)):
        if item not in sys.path:
            sys.path.insert(0, item)
    return importlib.import_module('onedrive_api.catalog')


class CatalogFixture:
    '''A Catalog over a fake restic; call() returns (status, value) where status is ok or an HTTP code.'''

    def __init__(self, *, scaffold: bool = False, snapshots: list | None = None, mount_plain_dir: bool = False,
                 max_export_bytes: int = 10 * 1024 ** 3, password_mode: int = 0o600, repository: bool = True):
        self.module = catalog_module()
        self.tmp = _work_dir('b3-catalog-')
        self.scaffold = scaffold
        self.data = self.tmp / 'data'
        self.mirror = self.data / 'mirror'
        self.state = self.tmp / 'state'
        for folder in (self.data / 'restic-repo', self.mirror, self.state, self.tmp / 'secrets', self.tmp / 'bin'):
            folder.mkdir(parents=True, exist_ok=True)
        if repository:
            (self.data / 'restic-repo' / 'config').write_text('fixture', encoding='utf-8')
        password = self.tmp / 'secrets' / 'restic-password'
        password.write_text('fixture', encoding='utf-8')
        password.chmod(password_mode)
        wrapper = self.tmp / 'bin' / 'restic'
        wrapper.write_text('#!' + sys.executable + chr(10) + 'import sys' + chr(10) + 'sys.path.insert(0, '
                           + repr(str(ROOT)) + ')' + chr(10) + 'from pipeline.fake_restic import main'
                           + chr(10) + 'sys.exit(main())' + chr(10), encoding='utf-8')
        wrapper.chmod(0o755)
        stamp = '2026-11-01T00:00:00Z'
        found = snapshots if snapshots is not None else [
            {'id': SNAPSHOT_ID, 'short_id': SNAPSHOT_ID[:8], 'time': stamp, 'tags': ['onedrive']}]
        nodes = [{'path': str(self.mirror) + '/dir', 'type': 'dir', 'size': 0, 'mtime': stamp},
                 {'path': str(self.mirror) + '/dir/file.txt', 'type': 'file', 'size': 5, 'mtime': stamp}]
        (self.state / 'snapshots.json').write_text(json.dumps(found), encoding='utf-8')
        (self.state / 'nodes.json').write_text(json.dumps(nodes), encoding='utf-8')
        (self.state / 'blob.bin').write_bytes(b'hello')
        plain = self.tmp / 'plain-mount'
        plain.mkdir(exist_ok=True)
        config = {'onedrive_remote': 'onedrive:', 'rclone_config': str(self.tmp / 'secrets' / 'rclone.conf'),
                  'mirror_dir': str(self.mirror), 'repository_dir': str(self.data / 'restic-repo'),
                  'password_file': str(password), 'lock_file': str(self.data / 'backup.lock'),
                  'restic_bin': str(wrapper), 'required_mountpoint': str(plain) if mount_plain_dir else None}
        self.config = self.tmp / 'backup.json'
        self.config.write_text(json.dumps(config), encoding='utf-8')
        self.catalog = self.module.Catalog(self.config, self.data, max_export_bytes=max_export_bytes)

    def call(self, function, *args, **kwargs):
        '''Run one catalog method with the scaffold flag and the fake restic state in the environment.'''
        saved = {key: os.environ.get(key) for key in ('ONEDRIVE_SCAFFOLD_MODE', 'FAKE_RESTIC_STATE')}
        os.environ['ONEDRIVE_SCAFFOLD_MODE'] = '1' if self.scaffold else '0'
        os.environ['FAKE_RESTIC_STATE'] = str(self.state)
        try:
            return 'ok', function(*args, **kwargs)
        except self.module.CatalogError as exc:
            return exc.status, str(exc)
        finally:
            for key, value in saved.items():
                if value is None:
                    os.environ.pop(key, None)
                else:
                    os.environ[key] = value

    def restic_calls(self) -> list:
        '''Return the recorded fake restic invocations.'''
        log = self.state / 'calls.log'
        return [json.loads(line) for line in log.read_text(encoding='utf-8').splitlines()] if log.exists() else []

    def write_export(self, export_id: str, *, expired: bool) -> None:
        '''Write one export (metadata and data file) as the catalog stores it; expired or valid for an hour.'''
        self.catalog.exports.mkdir(mode=0o700, parents=True, exist_ok=True)
        now = datetime.now(timezone.utc)
        stop = now - timedelta(hours=1) if expired else now + timedelta(hours=1)
        meta = {'export_id': export_id, 'snapshot_id': SNAPSHOT_ID, 'path': 'dir/file.txt', 'filename': 'file.txt',
                'size_bytes': 5, 'sha256': '0' * 64, 'created_at': (now - timedelta(hours=25)).isoformat(),
                'expires_at': stop.isoformat()}
        (self.catalog.exports / (export_id + '.json')).write_text(json.dumps(meta), encoding='utf-8')
        (self.catalog.exports / (export_id + '.bin')).write_bytes(b'hello')

    def export_files(self, export_id: str) -> list[str]:
        '''Names of the files of one export that still exist.'''
        folder = self.catalog.exports
        return sorted(p.name for p in folder.glob(export_id + '.*')) if folder.exists() else []

    def close(self) -> None:
        _remove(self.tmp)


@contextlib.contextmanager
def catalog_fixture(**kwargs):
    '''Context manager around CatalogFixture.'''
    fixture = CatalogFixture(**kwargs)
    try:
        yield fixture
    finally:
        fixture.close()


class Result:
    '''Outcome of one script run: exit code, output and the recorded stub calls.'''

    def __init__(self, rc: int, out: str, err: str, calls: list) -> None:
        self.rc, self.out, self.err, self.calls = rc, out, err, calls

    def docker(self, verb: str) -> list[list[str]]:
        '''docker calls whose first argument is verb.'''
        return [c for c in self.calls if c[0] == 'docker' and len(c) > 1 and c[1] == verb]

    def container_work(self) -> bool:
        '''True when a container was started or a command was executed in it.'''
        return bool(self.docker('run') or self.docker('exec'))

    def python_work(self) -> bool:
        '''True when python was executed inside the container.'''
        return any('python' in c for c in self.docker('exec'))


class Host:
    '''A temporary host: configuration with certificates, secrets, the rclone state directory and the archive tree.

    The data directory is archive/onedrive-backup, where archive stands for the mounted /srv/archive: run() executes a copy
    of the script with /srv/archive replaced by it and answers findmnt as the fs mode says (pipeline.archivefs).
    '''

    def __init__(self, *, secrets: bool = True) -> None:
        self.tmp = _work_dir('b3-host-')
        self.bin = self.tmp / 'bin'
        self.config = self.tmp / 'config'
        self.secrets = self.tmp / 'secrets'
        self.archive = self.tmp / 'archive'
        self.data = self.archive / 'onedrive-backup'
        self.elsewhere = self.tmp / 'elsewhere'
        self.other_mount = self.tmp / 'other-mount'
        self.state = self.tmp / 'rclone-state'
        self.scaffold = self.tmp / 'scaffold'
        self.log = self.tmp / 'calls.log'
        self.bin.mkdir()
        for name in STUBS:
            stub = self.bin / name
            stub.write_text('#!' + sys.executable + chr(10) + 'import sys' + chr(10) + 'sys.path.insert(0, '
                            + repr(str(ROOT)) + ')' + chr(10) + 'from pipeline.host_stubs import main'
                            + chr(10) + 'sys.exit(main(' + repr(name) + '))' + chr(10), encoding='utf-8')
            stub.chmod(0o755)
        (self.config / 'certs').mkdir(parents=True)
        for name in ('server.crt', 'server.key', 'ca.crt', 'proxy-ca.crt', 'trust-bundle.pem'):
            (self.config / 'certs' / name).write_text('fixture', encoding='utf-8')
        (self.config / 'server.json').write_text('{}', encoding='utf-8')
        (self.config / 'backup.json').write_text('{}', encoding='utf-8')
        self.secrets.mkdir(mode=0o700)
        self.secrets.chmod(0o700)
        past = time.time() - 1000
        if secrets:
            for name in ('rclone.conf', 'restic-password'):
                (self.secrets / name).write_text('fixture', encoding='utf-8')
                os.utime(self.secrets / name, (past, past))
        self.state.mkdir(mode=0o700)
        self.state.chmod(0o700)
        (self.state / 'rclone.conf').write_text('fixture-state-copy', encoding='utf-8')
        (self.state / 'rclone.conf').chmod(0o600)
        for folder in (self.archive, self.elsewhere, self.other_mount):
            folder.mkdir(mode=0o750)
            folder.chmod(0o750)
        self.data.mkdir(mode=0o750)
        self.data.chmod(0o750)
        self.log.write_text('', encoding='utf-8')

    def copy(self, script: Path) -> Path:
        '''A copy of script in which /srv/archive and /srv/backup name the fixture tree; the same file when nothing changes.'''
        text = script.read_text(encoding='utf-8')
        out = self.tmp / 'scripts' / script.name
        out.parent.mkdir(exist_ok=True)
        out.write_text(archivefs.rewrite(text, {archivefs.MOUNT: str(self.archive),
                                                archivefs.OLD_MOUNT: str(self.tmp / 'old-backup')}), encoding='utf-8')
        out.chmod(0o755)
        return out

    def run(self, script: Path, *args: str, uid: int | None = None, data: Path | None = None, fs: str = 'ok',
            unset: tuple[str, ...] = (), env: dict[str, str] | None = None) -> Result:
        '''Run a copy of bash script with args under the stubs; uid is what id -u onedrive-backup answers, data replaces
        the data directory of ONEDRIVE_DATA_DIR, fs is the findmnt mode of pipeline.archivefs, unset names variables to drop.'''
        target = self.data if data is None else data
        variables = {'PATH': str(self.bin) + ':/usr/bin:/bin', 'HOME': str(self.tmp), 'STUB_LOG': str(self.log),
                     'STUB_ROOT': str(self.tmp),
                     'STUB_UID': str(os.getuid() if uid is None else uid), 'STUB_GID': str(os.getgid()),
                     'ONEDRIVE_IMAGE': 'fixture-image:1', 'ONEDRIVE_CONTAINER': 'odb-fixture',
                     'ONEDRIVE_NETWORK': 'odb-net', 'ONEDRIVE_CONFIG_DIR': str(self.config),
                     'ONEDRIVE_DATA_DIR': str(target), 'ONEDRIVE_SECRET_DIR': str(self.secrets),
                     'ONEDRIVE_RCLONE_STATE_DIR': str(self.state),
                     'ONEDRIVE_SCAFFOLD_DATA_DIR': str(self.scaffold)}
        variables.update(archivefs.fs_env(fs, self.archive, target, self.other_mount))
        variables.update(env or {})
        for name in unset:
            variables.pop(name, None)
        self.log.write_text('', encoding='utf-8')
        done = subprocess.run(['bash', str(self.copy(script))] + list(args), env=variables, capture_output=True, text=True,
                              timeout=60, cwd=str(self.tmp))
        calls = [json.loads(line) for line in self.log.read_text(encoding='utf-8').splitlines() if line]
        return Result(done.returncode, done.stdout, done.stderr, calls)

    def close(self) -> None:
        _remove(self.tmp)


@contextlib.contextmanager
def host(**kwargs):
    '''Context manager around Host.'''
    fixture = Host(**kwargs)
    try:
        yield fixture
    finally:
        fixture.close()


def run_wrapper(args: list[str]) -> tuple[int, list | None, str, bool]:
    '''Run a copy of the wrapper script with its absolute paths redirected to a recording stub.

    Returns (exit code, argv received by the stub or None, stderr, whether both paths were redirected).
    '''
    tmp = _work_dir('b3-wrapper-')
    try:
        text = (ROOT / 'packaging' / 'onedrive-backup-docker').read_text(encoding='utf-8')
        redirected = WRAPPER_DOCKER_RUN in text
        seen = tmp / 'argv.json'
        stub = tmp / 'docker-run.sh'
        stub.write_text('#!' + sys.executable + chr(10) + 'import json, sys' + chr(10) + 'json.dump(sys.argv[1:], open('
                        + repr(str(seen)) + ', ' + repr('w') + '))' + chr(10), encoding='utf-8')
        stub.chmod(0o755)
        copy = tmp / 'wrapper'
        copy.write_text(text.replace(WRAPPER_DOCKER_RUN, str(stub)).replace(WRAPPER_DEFAULTS, str(tmp / 'defaults')),
                        encoding='utf-8')
        done = subprocess.run(['sh', str(copy)] + list(args), capture_output=True, text=True, timeout=30,
                              cwd=str(tmp))
        got = json.loads(seen.read_text(encoding='utf-8')) if seen.exists() else None
        return done.returncode, got, done.stderr.strip(), redirected
    finally:
        _remove(tmp)
