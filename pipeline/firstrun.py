'''Disposable host of the deploy_first_run check: runs the real docker/deploy.sh over stub commands.

A Scenario is a temporary tree under .test-run of the checkout: a secrets directory, a data directory with an
optional stub restic repository, an optional restic password file, and a bin directory of stub commands that
stand in front of dpkg, docker, systemctl, restic, id, chown, chgrp and install. The environment overrides
ONEDRIVE_SECRET_DIR, ONEDRIVE_DATA_DIR and ONEDRIVE_DEFAULTS_FILE point docker/deploy.sh at that tree. The
script is a COPY in which /srv/archive names the temporary archive tree (pipeline.archivefs) and the stub findmnt answers as the
fs mode says, so the data directory guard of decision D9 passes unless a case chooses another mode. The copy runs either behind a pseudo-terminal that answers every wait for input with the next supplied line (the
terminal echo flag is read at each wait), or with no terminal at all. Real host state is never read or written.
'''

from __future__ import annotations

import hashlib
import json
import os
import pty
import secrets
import select
import shutil
import signal
import subprocess
import sys
import tempfile
import termios
import time
from pathlib import Path

from pipeline import archivefs, firstrun_stubs

ROOT = Path(__file__).resolve().parents[1]
WORK = ROOT / '.test-run'
SCRIPT = ROOT / 'docker' / 'deploy.sh'
STUBS = ('dpkg', 'docker', 'systemctl', 'restic', 'id', 'chown', 'chgrp', 'install', 'findmnt')
IDLE_SECONDS = 1.5


def new_password() -> str:
    '''A random password; it is only ever compared, never printed.'''
    return 'Pw-' + secrets.token_hex(12)


class Run:
    '''Outcome of one deploy.sh run: exit code, text, the waits for input and what the driver did.'''

    def __init__(self, rc: int, out: str, err: str, prompts: list[dict], sent: int, stuck: bool, timed_out: bool) -> None:
        self.rc, self.out, self.err = rc, out, err
        self.prompts, self.sent, self.stuck, self.timed_out = prompts, sent, stuck, timed_out

    def lines(self) -> list[str]:
        '''Every output line, stripped.'''
        return [line.strip() for line in (self.out + chr(10) + self.err).splitlines()]

    def text(self) -> str:
        '''All the output of the run.'''
        return self.out + chr(10) + self.err


class Scenario:
    '''A temporary host: secrets, data, stub commands and the recorded calls.'''

    def __init__(self, *, repo_password: str | None = None, file_password: str | None = None, fs: str = 'ok') -> None:
        WORK.mkdir(exist_ok=True)
        self.tmp = Path(tempfile.mkdtemp(prefix='fr-', dir=str(WORK)))
        self.bin = self.tmp / 'bin'
        self.secrets = self.tmp / 'secrets'
        self.archive = self.tmp / 'archive'
        self.data = self.archive / 'onedrive-backup'
        self.other_mount = self.tmp / 'other-mount'
        self.fs = fs
        self.env_set: dict[str, str] = {}
        self.env_drop: set[str] = set()
        self.log = self.tmp / 'calls.log'
        self.defaults = self.tmp / 'defaults'
        self.bin.mkdir()
        for name in STUBS:
            stub = self.bin / name
            stub.write_text('#!' + sys.executable + chr(10) + 'import sys' + chr(10) + 'sys.path.insert(0, '
                            + repr(str(ROOT)) + ')' + chr(10) + 'from pipeline.firstrun_stubs import main'
                            + chr(10) + 'sys.exit(main(' + repr(name) + '))' + chr(10), encoding='utf-8')
            stub.chmod(0o755)
        self.secrets.mkdir(mode=0o700)
        self.secrets.chmod(0o700)
        self.archive.mkdir(mode=0o750)
        self.other_mount.mkdir(mode=0o750)
        self.data.mkdir(mode=0o750)
        self.data.chmod(0o750)
        self.script = self.tmp / 'docker' / 'deploy.sh'
        self.script.parent.mkdir()
        self.script.write_text(archivefs.rewrite(SCRIPT.read_text(encoding='utf-8') if SCRIPT.is_file() else '',
                                                 {archivefs.MOUNT: str(self.archive),
                                                  archivefs.OLD_MOUNT: str(self.tmp / 'old-backup')}), encoding='utf-8')
        (self.tmp / 'VERSION').write_text('0.0.0' + chr(10), encoding='utf-8')
        self.log.write_text('', encoding='utf-8')
        self.defaults.write_text('ONEDRIVE_SECRET_DIR=%s%sONEDRIVE_DATA_DIR=%s%s' % (self.secrets, chr(10), self.data, chr(10)),
                                 encoding='utf-8')
        if repo_password is not None:
            firstrun_stubs.create_repo(str(self.repo), repo_password)
        if file_password is not None:
            self.password_file.write_text(file_password + chr(10), encoding='utf-8')
            self.password_file.chmod(0o600)

    @property
    def repo(self) -> Path:
        '''Where the restic repository lives: the data directory holds restic-repo, as config/backup.json says.'''
        return self.data / 'restic-repo'

    @property
    def password_file(self) -> Path:
        '''Where the restic password file lives.'''
        return self.secrets / 'restic-password'

    def env(self) -> dict[str, str]:
        '''The environment of a run: stubs first on PATH, every host path redirected into the temporary tree.'''
        env = {'PATH': str(self.bin) + ':/usr/bin:/bin', 'HOME': str(self.tmp), 'LANG': 'C', 'TERM': 'xterm',
               'FR_LOG': str(self.log), 'FR_PASSWORD_FILE': str(self.password_file),
               'ONEDRIVE_SECRET_DIR': str(self.secrets), 'ONEDRIVE_DATA_DIR': str(self.data),
               'ONEDRIVE_DEFAULTS_FILE': str(self.defaults)}
        env.update(archivefs.fs_env(self.fs, self.archive, self.data, self.other_mount))
        env.update(self.env_set)
        for name in self.env_drop:
            env.pop(name, None)
        return env

    def calls(self, command: str | None = None) -> list[dict]:
        '''Recorded stub calls, optionally only those of one command.'''
        rows = [json.loads(line) for line in self.log.read_text(encoding='utf-8').splitlines() if line]
        return [row for row in rows if command is None or row['cmd'] == command]

    def restic(self, verb: str | None = None) -> list[dict]:
        '''Recorded restic calls with the given verb; verb None keeps every call, verb ! keeps the non-init ones.'''
        found = self.calls('restic')
        if verb == '!':
            return [row for row in found if row['verb'] != 'init']
        return [row for row in found if verb is None or row['verb'] == verb]

    def replaced(self) -> list[str]:
        '''Calls that would replace the running package or container: any dpkg, docker or systemctl call.'''
        return [row['cmd'] for row in self.calls() if row['cmd'] in ('dpkg', 'docker', 'systemctl')]

    def secrets_digest(self) -> str:
        '''Digest of the secrets directory: names, modes and content hashes.'''
        return tree_digest(self.secrets)

    def repo_digest(self) -> str:
        '''Digest of the restic repository directory, or the word absent.'''
        return tree_digest(self.repo) if self.repo.exists() else 'absent'

    def password_text(self) -> str | None:
        '''Content of the password file without the final newline, or None when the file is absent.'''
        return self.password_file.read_text(encoding='utf-8').rstrip(chr(10)) if self.password_file.is_file() else None

    def repo_opens_with(self, password: str) -> bool:
        '''True when the stub repository exists and was created with this password.'''
        config = self.repo / 'config'
        return config.is_file() and config.read_text(encoding='utf-8').strip() == firstrun_stubs.digest(password)

    def owned_by_root(self) -> bool:
        '''The password file is owned by root: really (run as root) or by a recorded chown or install owner option.'''
        if os.geteuid() == 0:
            return self.password_file.stat().st_uid == 0
        for row in self.calls():
            if row['cmd'] in ('chown', 'install') and any(
                    item in ('root', 'root:root', '--owner=root') or item.startswith('root:') for item in row['args']):
                return True
        return False

    def leaks(self, run: Run, *passwords: str) -> bool:
        '''True when any password shows in the output of the run or in the arguments of a recorded call.'''
        words = [item for item in passwords if item]
        argv = [part for row in self.calls() for part in row['args']]
        return any(word in run.text() or any(word in part for part in argv) for word in words)

    def tty(self, passwords: list[str], *, limit: float = 40.0) -> Run:
        '''Run docker/deploy.sh behind a pseudo-terminal; every wait for input gets the next password line.'''
        return _run_tty(self.env(), str(self.tmp), passwords, limit, self.script)

    def plain(self, stdin: bytes | None, *, limit: float = 30.0) -> Run:
        '''Run docker/deploy.sh in a new session with no controlling terminal; stdin is a pipe or the null device.'''
        kwargs: dict = {'input': stdin} if stdin is not None else {'stdin': subprocess.DEVNULL}
        try:
            done = subprocess.run(['/bin/bash', str(self.script)], env=self.env(), cwd=str(self.tmp), capture_output=True,
                                  timeout=limit, start_new_session=True, check=False, **kwargs)
        except subprocess.TimeoutExpired:
            return Run(-1, '', '', [], 0, False, True)
        return Run(done.returncode, done.stdout.decode('utf-8', 'replace'), done.stderr.decode('utf-8', 'replace'),
                   [], 0, False, False)

    def close(self) -> None:
        shutil.rmtree(self.tmp, ignore_errors=True)

    def __enter__(self) -> 'Scenario':
        return self

    def __exit__(self, *_exc: object) -> None:
        self.close()


def tree_digest(path: Path) -> str:
    '''Digest of the names, modes and content of every entry under path.'''
    sha = hashlib.sha256()
    for base, dirs, files in os.walk(path):
        dirs.sort()
        for name in sorted(dirs + files):
            item = Path(base) / name
            sha.update(('%s %o ' % (item.relative_to(path), item.lstat().st_mode & 0o7777)).encode('utf-8'))
            if item.is_file() and not item.is_symlink():
                sha.update(item.read_bytes())
    return sha.hexdigest()


def _drain(fd: int) -> bytes:
    data = b''
    while select.select([fd], [], [], 0.2)[0]:
        try:
            part = os.read(fd, 4096)
        except OSError:
            break
        if not part:
            break
        data += part
    return data


def _run_tty(env: dict[str, str], cwd: str, passwords: list[str], limit: float, script: Path = SCRIPT) -> Run:
    pid, fd = pty.fork()
    if pid == 0:
        try:
            os.chdir(cwd)
            os.execve('/bin/bash', ['bash', str(script)], env)
        finally:
            os._exit(127)
    out = b''
    prompts: list[dict] = []
    sent = 0
    stuck = timed_out = False
    status = None
    started = last = time.monotonic()
    while True:
        now = time.monotonic()
        if now - started > limit:
            timed_out = True
            break
        if select.select([fd], [], [], 0.2)[0]:
            try:
                data = os.read(fd, 4096)
            except OSError:
                data = b''
            if not data:
                break
            out += data
            last = time.monotonic()
            continue
        done, state = os.waitpid(pid, os.WNOHANG)
        if done:
            status = state
            out += _drain(fd)
            break
        if time.monotonic() - last >= IDLE_SECONDS:
            prompts.append({'echo': bool(termios.tcgetattr(fd)[3] & termios.ECHO)})
            if sent >= len(passwords):
                stuck = True
                break
            os.write(fd, (passwords[sent] + chr(10)).encode('utf-8'))
            sent += 1
            last = time.monotonic()
    if status is None:
        if stuck or timed_out:
            os.kill(pid, signal.SIGKILL)
        _done, status = os.waitpid(pid, 0)
    os.close(fd)
    text = out.decode('utf-8', 'replace').replace(chr(13) + chr(10), chr(10)).replace(chr(13), chr(10))
    return Run(os.waitstatus_to_exitcode(status), text, '', prompts, sent, stuck, timed_out)
