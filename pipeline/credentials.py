'''Run credentials of the pipeline: matrix row PX11, relation R17 (revision 4, section 10.3).

The live checks that send the interim token T = base64(login ':' password) (decision D3) need exactly two inputs, the login
and the password. A ready-made token variable is NOT an input. They are read from ONE source:
  1. the git-ignored env file named by ONEDRIVE_BACKUP_CREDENTIALS_FILE, loaded BY PATH (mode 0600, not tracked by git,
     git-ignored); or, when that variable is not set,
  2. the variables ONEDRIVE_BACKUP_LOGIN and ONEDRIVE_BACKUP_PASSWORD already present in the environment of the run (a run
     that sourced the env file itself with set -a).
T is derived in memory only. No value is ever printed or put into an exception text: a problem names the variable or the
file problem, never a value (R17).
'''

from __future__ import annotations

import base64
import os
import stat
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FILE_VAR = 'ONEDRIVE_BACKUP_CREDENTIALS_FILE'
LOGIN_VAR = 'ONEDRIVE_BACKUP_LOGIN'
PASSWORD_VAR = 'ONEDRIVE_BACKUP_PASSWORD'


class CredentialsError(RuntimeError):
    '''The run credentials are missing, incomplete or unusable; the message never holds a value.'''


def parse_env_file(text: str) -> dict[str, str]:
    '''Parse NAME=VALUE lines (optional export prefix and quotes) into a mapping.'''
    values: dict[str, str] = {}
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith('#'):
            continue
        if line.startswith('export '):
            line = line[len('export '):].strip()
        name, sep, value = line.partition('=')
        if not sep:
            continue
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in (chr(34), chr(39)):
            value = value[1:-1]
        values[name.strip()] = value
    return values


def _git(args: list[str], root: Path) -> subprocess.CompletedProcess:
    try:
        return subprocess.run(['git'] + args, cwd=root, capture_output=True, text=True)
    except OSError:
        raise CredentialsError('git cannot be run to check that the credentials file is ignored (file problem N4)')


def check_file(path: Path, root: Path = ROOT) -> None:
    '''Raise CredentialsError for an absent or unreadable file (N1), a mode wider than 0600 (N2), a tracked or not git-ignored file (N4).'''
    try:
        info = path.stat()
    except OSError:
        raise CredentialsError('the credentials file named by %s does not exist or cannot be read (file problem N1)' % FILE_VAR)
    if not stat.S_ISREG(info.st_mode) or not os.access(path, os.R_OK):
        raise CredentialsError('the credentials file named by %s is not a readable regular file (file problem N1)' % FILE_VAR)
    if stat.S_IMODE(info.st_mode) & ~0o600:
        raise CredentialsError('the credentials file named by %s has mode %s, wider than 0600; it is not loaded (file problem N2)'
                               % (FILE_VAR, oct(stat.S_IMODE(info.st_mode))))
    try:
        rel = path.resolve().relative_to(root.resolve())
    except ValueError:
        return
    if _git(['ls-files', '--error-unmatch', '--', str(rel)], root).returncode == 0:
        raise CredentialsError('the credentials file named by %s is tracked by git (file problem N4)' % FILE_VAR)
    if _git(['check-ignore', '-q', '--', str(rel)], root).returncode != 0:
        raise CredentialsError('the credentials file named by %s is inside the repository but not git-ignored (file problem N4)' % FILE_VAR)


def load(environ: dict | None = None, root: Path = ROOT) -> tuple[str, str]:
    '''Return (login, password) of the run or raise CredentialsError (R17: all-or-none login and password).'''
    env = os.environ if environ is None else environ
    given = env.get(FILE_VAR)
    if given:
        path = Path(given)
        check_file(path, root)
        try:
            values = parse_env_file(path.read_text(encoding='utf-8'))
        except (OSError, UnicodeDecodeError):
            raise CredentialsError('the credentials file named by %s cannot be read (file problem N1)' % FILE_VAR)
    else:
        values = {LOGIN_VAR: env.get(LOGIN_VAR, ''), PASSWORD_VAR: env.get(PASSWORD_VAR, '')}
    login, password = values.get(LOGIN_VAR, ''), values.get(PASSWORD_VAR, '')
    if not login and not password:
        raise CredentialsError('%s and %s are both missing: export them, or name the git-ignored 0600 env file in %s'
                               % (LOGIN_VAR, PASSWORD_VAR, FILE_VAR))
    if not login or not password:
        raise CredentialsError('only one of %s and %s is set; both are required (all-or-none, N3)' % (LOGIN_VAR, PASSWORD_VAR))
    if ':' in login:
        raise CredentialsError('%s must not contain a colon' % LOGIN_VAR)
    return login, password


def derive(login: str, password: str) -> str:
    '''Return T = base64(login ':' password).'''
    return base64.b64encode((login + ':' + password).encode('utf-8')).decode('ascii')


def problem(environ: dict | None = None, root: Path = ROOT) -> str | None:
    '''Return the problem text of the run credentials (no value in it) or None when they are usable.'''
    try:
        load(environ, root)
    except CredentialsError as exc:
        return str(exc)
    return None


def token(environ: dict | None = None, root: Path = ROOT) -> str | None:
    '''Return the token T of the run credentials, or None when they are missing or unusable.'''
    try:
        return derive(*load(environ, root))
    except CredentialsError:
        return None


def secret_values(environ: dict | None = None, root: Path = ROOT) -> list[str]:
    '''Return every secret form (login, password, T, login:password) for the output scans; empty when unusable.'''
    try:
        login, password = load(environ, root)
    except CredentialsError:
        return []
    return [login, password, derive(login, password), login + ':' + password]
