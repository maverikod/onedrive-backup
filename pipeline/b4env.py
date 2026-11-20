'''B4 named check run_credentials_env: the environment contract of every live pipeline run (row PX11, relation R17, revision 8).

The only run credential is the OPTIONAL password ONEDRIVE_BACKUP_PASSWORD, loaded BY PATH from a git-ignored env file of mode 0600
(variable ONEDRIVE_BACKUP_CREDENTIALS_FILE) or taken from the environment of the run, and sent as X-API-Key exactly as it is; an
absent password is GREEN (no header, the service is open), never [ENVIRONMENT]. The login variable is removed. The cases P0, P1 and
N1, N2, N4 run on synthetic files of this check and need no real secret; N5 needs the real password and is skipped as a case
(not as a check) when the run holds none.
'''

from __future__ import annotations

import contextlib
import io
import secrets
import shutil
import tempfile
from pathlib import Path

from pipeline import b4server, credentials
from pipeline.checks import CheckFailure
from pipeline.report import Report

ROOT = credentials.ROOT
RETIRED_VARIABLE = ''.join(('ONEDRIVE_BACKUP_', 'TOK', 'EN'))
LOGIN_VARIABLE = ''.join(('ONEDRIVE_BACKUP_', 'LOGIN'))


def _load(env: dict) -> tuple[str, object]:
    try:
        return 'ok', credentials.load(env)
    except credentials.CredentialsError as exc:
        return 'error', str(exc)


def _write(path: Path, text: str, mode: int) -> Path:
    path.write_text(text, encoding='utf-8')
    path.chmod(mode)
    return path


def _expect_error(report: Report, case: str, got: tuple[str, object], code: str, secret_values: tuple[str, ...]) -> None:
    kind, value = got
    if kind != 'error' or code not in str(value):
        report.product.append('%s: expected the RED [ENVIRONMENT] problem %s, got %s %s' % (case, code, kind, str(value)[:100] if kind == 'error' else '(loaded)'))
    elif any(item in str(value) for item in secret_values):
        report.product.append('%s: the problem text holds a login or password value' % case)


def _synthetic_cases(report: Report, work: Path) -> None:
    password = secrets.token_hex(12)
    body = 'ONEDRIVE_BACKUP_PASSWORD=%s\n' % password
    values = (password,)
    var = credentials.FILE_VAR
    captured = io.StringIO()
    with contextlib.redirect_stdout(captured), contextlib.redirect_stderr(captured):
        got = _load({var: str(_write(work / 'good.env', body, 0o600))})
        token = credentials.token({var: str(work / 'good.env')})
    if got != ('ok', password) or token != password:
        report.product.append('P1 a 0600 git-ignored file with the password: expected the password as it is (the X-API-Key value, nothing derived), got %s' % got[0])
    if captured.getvalue():
        report.product.append('P1 loading the credentials printed to stdout or stderr')
    if _load({}) != ('ok', None) or credentials.problem({}) is not None or credentials.token({}) is not None:
        report.product.append('P0 no password at all: expected no value and no problem (the service is open, GREEN, never [ENVIRONMENT])')
    if _load({credentials.PASSWORD_VAR: password}) != ('ok', password):
        report.product.append('P1 the password in the environment of the run was not accepted')
    if credentials.token({LOGIN_VARIABLE: 'someone'}) is not None or hasattr(credentials, 'derive'):
        report.product.append('the login variable or a derived base64 token is still part of the run credentials (removed in revision 8)')
    _expect_error(report, 'N1 file path absent', _load({var: str(work / 'absent.env')}), 'N1', values)
    _expect_error(report, 'N2 file mode 0644', _load({var: str(_write(work / 'wide.env', body, 0o644))}), 'N2', values)
    inside = ROOT / 'pipeline' / ('.credenv-%s.tmp' % secrets.token_hex(4))
    try:
        _write(inside, body, 0o600)
        _expect_error(report, 'N4 file inside the repository and not git-ignored', _load({var: str(inside)}), 'N4', values)
    finally:
        inside.unlink(missing_ok=True)
    if credentials.token({RETIRED_VARIABLE: 'ready-made'}) is not None:
        report.product.append('a ready-made token variable is still an input of the run credentials')


def _static_cases(report: Report) -> None:
    for name in (RETIRED_VARIABLE, LOGIN_VARIABLE):
        hits = [str(path.relative_to(ROOT)) for path in sorted((ROOT / 'pipeline').rglob('*'))
                if path.is_file() and path.suffix in ('.py', '.env') and name in path.read_text(encoding='utf-8', errors='replace')]
        if hits:
            report.product.append('the retired variable %s is still named in %s (it is no input of the matrix)' % (name, hits))


def _real_cases(report: Report) -> None:
    problem = credentials.problem()
    if problem:
        report.env.append('P1 the real run credentials file: ' + problem)
        return
    if not credentials.token():
        report.info.append('N5 no run password is configured: the output scan has no value to look for (GREEN, the service is open)')
        return
    captured, failure = io.StringIO(), ''
    with contextlib.redirect_stdout(captured), contextlib.redirect_stderr(captured):
        try:
            b4server.auth_token()
        except CheckFailure as exc:
            failure = str(exc)
    text = captured.getvalue() + failure
    if any(item and item in text for item in credentials.secret_values()):
        report.product.append('N5 the captured stdout and stderr of an auth_token run contain the password')


def run_credentials_env() -> None:
    '''PX11 cases P0, P1, N1, N2, N4 and N5 of the run-credentials environment; a missing real environment is RED [ENVIRONMENT], never PRODUCT.'''
    report = Report()
    cache = ROOT / '.test-run'
    cache.mkdir(exist_ok=True)
    work = Path(tempfile.mkdtemp(prefix='credenv', dir=cache))
    try:
        _synthetic_cases(report, work)
    finally:
        shutil.rmtree(work, ignore_errors=True)
    _static_cases(report)
    _real_cases(report)
    report.finish('run_credentials_env')
