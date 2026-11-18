'''B4 named check run_credentials_env: the environment contract of every live pipeline run (row PX11, relation R17).

The run credentials are ONEDRIVE_BACKUP_LOGIN and ONEDRIVE_BACKUP_PASSWORD, both required, loaded BY PATH from a git-ignored
env file of mode 0600 (variable ONEDRIVE_BACKUP_CREDENTIALS_FILE) or taken from the environment of the run; the token T is
derived in memory only (pipeline.credentials). The cases P1 and N1..N4 run on synthetic files of this check and need no real
secret; N5 and the real P1 need the real run credentials and are RED [ENVIRONMENT] when the run holds none.
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
    login, password = 'pipeline-synthetic', secrets.token_hex(12)
    both = 'ONEDRIVE_BACKUP_LOGIN=%s\nONEDRIVE_BACKUP_PASSWORD=%s\n' % (login, password)
    values = (login, password)
    var = credentials.FILE_VAR
    captured = io.StringIO()
    with contextlib.redirect_stdout(captured), contextlib.redirect_stderr(captured):
        got = _load({var: str(_write(work / 'good.env', both, 0o600))})
        token = credentials.token({var: str(work / 'good.env')})
    if got != ('ok', (login, password)) or token != credentials.derive(login, password):
        report.product.append('P1 a 0600 git-ignored file with both variables: expected the pair and T = base64(login:password), got %s' % got[0])
    if captured.getvalue():
        report.product.append('P1 loading the credentials printed to stdout or stderr')
    _expect_error(report, 'N1 file path absent', _load({var: str(work / 'absent.env')}), 'N1', values)
    _expect_error(report, 'N2 file mode 0644', _load({var: str(_write(work / 'wide.env', both, 0o644))}), 'N2', values)
    _expect_error(report, 'N3 only the login', _load({var: str(_write(work / 'login.env', 'ONEDRIVE_BACKUP_LOGIN=%s\n' % login, 0o600))}), 'N3', values)
    _expect_error(report, 'N3 only the password', _load({var: str(_write(work / 'pass.env', 'ONEDRIVE_BACKUP_PASSWORD=%s\n' % password, 0o600))}), 'N3', values)
    inside = ROOT / 'pipeline' / ('.credenv-%s.tmp' % secrets.token_hex(4))
    try:
        _write(inside, both, 0o600)
        _expect_error(report, 'N4 file inside the repository and not git-ignored', _load({var: str(inside)}), 'N4', values)
    finally:
        inside.unlink(missing_ok=True)
    if _load({credentials.LOGIN_VAR: login, credentials.PASSWORD_VAR: password}) != ('ok', (login, password)):
        report.product.append('P1 both variables in the environment of the run were not accepted')
    _expect_error(report, 'N3 only the login in the environment', _load({credentials.LOGIN_VAR: login}), 'N3', values)
    if credentials.token({RETIRED_VARIABLE: 'ready-made'}) is not None:
        report.product.append('a ready-made token variable is still an input of the run credentials (U1(c): login and password only)')


def _static_cases(report: Report) -> None:
    hits = [str(path.relative_to(ROOT)) for path in sorted((ROOT / 'pipeline').rglob('*'))
            if path.is_file() and path.suffix in ('.py', '.yaml', '.env') and RETIRED_VARIABLE in path.read_text(encoding='utf-8', errors='replace')]
    if hits:
        report.product.append('the retired token variable is still named in %s (U1(c): it is no input of the matrix)' % hits)


def _real_cases(report: Report) -> None:
    problem = credentials.problem()
    if problem:
        report.env.append('P1 the real run credentials: ' + problem)
        report.env.append('N5 the output scan of an auth_token run needs the real run credentials')
        return
    captured, failure = io.StringIO(), ''
    with contextlib.redirect_stdout(captured), contextlib.redirect_stderr(captured):
        try:
            b4server.auth_token()
        except CheckFailure as exc:
            failure = str(exc)
    text = captured.getvalue() + failure
    if any(item and item in text for item in credentials.secret_values()):
        report.product.append('N5 the captured stdout and stderr of an auth_token run contain the password, the token T or the login-password pair')


def run_credentials_env() -> None:
    '''PX11 cases P1 and N1..N5 of the run-credentials environment; a missing real environment is RED [ENVIRONMENT], never PRODUCT.'''
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
