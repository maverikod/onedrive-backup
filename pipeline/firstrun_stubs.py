'''Stub commands of the deploy_first_run check: dpkg, docker, systemctl, restic, id, chown, chgrp, install and findmnt.

Every call is appended as one JSON line to the file named by FR_LOG. The restic stub keeps a repository as a
directory whose config file holds the SHA-256 of the password; it records where the password came from and never
the password itself. dpkg records whether the password file named by FR_PASSWORD_FILE existed at call time and its
mode, which proves that the password was stored before the package replaced the running installation. Nothing
here touches the real host: dpkg, docker and systemctl only log, chown and chgrp only log, install drops its
owner and group options and installs as the calling user.
'''

from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys

from pipeline import archivefs

VERBS = ('init', 'cat', 'snapshots', 'check', 'list', 'stats', 'ls', 'key', 'unlock', 'version')


def _log(entry: dict) -> None:
    with open(os.environ['FR_LOG'], 'a', encoding='utf-8') as fp:
        fp.write(json.dumps(entry) + chr(10))


def _read_password(path: str) -> str | None:
    try:
        if path == '-':
            return sys.stdin.readline().rstrip(chr(10))
        with open(path, encoding='utf-8') as fp:
            return fp.readline().rstrip(chr(10))
    except OSError:
        return None


def _password(args: list[str]) -> tuple[str | None, str]:
    '''Return the restic password and the label of its source: file, env-file, env or none.'''
    for index, item in enumerate(args):
        if item == '--password-file' and index + 1 < len(args):
            return _read_password(args[index + 1]), 'file'
        if item.startswith('--password-file='):
            return _read_password(item.split('=', 1)[1]), 'file'
    if os.environ.get('RESTIC_PASSWORD_FILE'):
        return _read_password(os.environ['RESTIC_PASSWORD_FILE']), 'env-file'
    if os.environ.get('RESTIC_PASSWORD') is not None:
        return os.environ['RESTIC_PASSWORD'], 'env'
    return None, 'none'


def _repo(args: list[str]) -> str | None:
    for index, item in enumerate(args):
        if item in ('-r', '--repo') and index + 1 < len(args):
            return args[index + 1]
        if item.startswith('--repo='):
            return item.split('=', 1)[1]
    return os.environ.get('RESTIC_REPOSITORY')


def digest(password: str) -> str:
    '''The value the stub repository stores for a password.'''
    return hashlib.sha256(password.encode('utf-8')).hexdigest()


def create_repo(repo: str, password: str) -> None:
    '''Create a stub repository the way restic init does.'''
    os.makedirs(os.path.join(repo, 'keys'), exist_ok=True)
    with open(os.path.join(repo, 'config'), 'w', encoding='utf-8') as fp:
        fp.write(digest(password))


def _restic(args: list[str]) -> int:
    password, source = _password(args)
    repo = _repo(args)
    verb = next((item for item in args if item in VERBS), '')
    _log({'cmd': 'restic', 'args': args, 'verb': verb, 'repo': repo, 'password_source': source})
    if verb == 'version':
        print('restic 0.0.0 (stub)')
        return 0
    if not repo or password is None:
        sys.stderr.write('Fatal: no repository or no password given (stub)' + chr(10))
        return 1
    config = os.path.join(repo, 'config')
    if verb == 'init':
        if os.path.exists(config):
            sys.stderr.write('Fatal: create repository failed: config file already exists' + chr(10))
            return 1
        create_repo(repo, password)
        print('created restic repository (stub)')
        return 0
    if not os.path.exists(config):
        sys.stderr.write('Fatal: unable to open config file: repository does not exist' + chr(10))
        return 10
    with open(config, encoding='utf-8') as fp:
        stored = fp.read().strip()
    if stored != digest(password):
        sys.stderr.write('Fatal: wrong password or no key found' + chr(10))
        return 12
    print('{}' if verb == 'cat' else '[]')
    return 0


def _install(args: list[str]) -> int:
    kept: list[str] = []
    skip = False
    for item in args:
        if skip:
            skip = False
        elif item in ('-o', '-g', '--owner', '--group'):
            skip = True
        elif not item.startswith(('--owner=', '--group=')):
            kept.append(item)
    return subprocess.run(['/usr/bin/install'] + kept, check=False).returncode


def main(name: str) -> int:
    '''Behave as the stubbed command called name.'''
    args = sys.argv[1:]
    if name == 'restic':
        return _restic(args)
    if name == 'findmnt':
        _log({'cmd': 'findmnt', 'args': args})
        code, text = archivefs.findmnt(args, dict(os.environ))
        sys.stdout.write(text)
        return code
    if name == 'id' and args == ['-u']:
        print(0)
        return 0
    if name == 'id':
        os.execv('/usr/bin/id', ['id'] + args)
    if name == 'install':
        _log({'cmd': 'install', 'args': args})
        return _install(args)
    entry: dict = {'cmd': name, 'args': args}
    if name == 'dpkg':
        path = os.environ['FR_PASSWORD_FILE']
        entry['secret_exists'] = os.path.isfile(path)
        entry['secret_mode'] = (os.stat(path).st_mode & 0o777) if os.path.isfile(path) else None
    _log(entry)
    return 0
