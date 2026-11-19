'''deploy_first_run: docker/deploy.sh asks the restic repository password on the first run (row PL8; TODO 8b81de72).

User decision 2026-11-19, cases 1-4. Mode: script fixture over a COPY of the REAL docker/deploy.sh. The copy runs under a
sandbox of stub commands (dpkg, docker, systemctl, restic, id, chown, chgrp, install, findmnt) in front of PATH and over
environment overrides that point it at a temporary secrets directory and a temporary data directory; in the copy /srv/archive
names a temporary archive tree and the stub findmnt reports it mounted with the data directory on it, so the data directory guard
of decision D9 (revision 9, host_data_fs_guard) passes and the cases reach their password prompt. The real
host state (/var/lib/onedrive-backup, /srv/archive, /srv/backup, /etc) is never read or written, nothing is installed,
stopped or started, and the script is refused before it runs when it names a production path without an
overridable default or calls dpkg, docker, systemctl, restic or findmnt by an absolute path.

Contract the script must meet (the check is the specification):
  environment: ONEDRIVE_SECRET_DIR (default /var/lib/onedrive-backup/secrets) and ONEDRIVE_DATA_DIR (default
    /srv/archive/onedrive-backup) are honoured, the restic password file is $ONEDRIVE_SECRET_DIR/restic-password and
    the repository is $ONEDRIVE_DATA_DIR/restic-repo; root is tested with id -u; restic is the host command
    restic; ONEDRIVE_DEFAULTS_FILE (default /etc/default/onedrive-backup) is honoured when the script reads it.
  case 1 first run, terminal, no repository and no password file: the password is asked twice without echo, a
    mismatch asks again, the file is written mode 0600 owned by root, the repository is initialised with that
    password, a warning says the user must keep a copy outside the host, the package is installed afterwards.
  case 2 repository exists, password file missing, terminal: the password is asked, verified against the
    repository with a read-only restic call (never init), written only on success; a wrong password exits
    non-zero with the line MSG_WRONG, creates and overwrites nothing and never reaches dpkg or docker.
  case 3 repository and password file present: no prompt, with or without a terminal, nothing rewritten.
  case 4 no terminal and password file missing: non-zero exit with the line MSG_NO_TTY, no password generated
    or read from a pipe, nothing created, restic init never called, never reaches dpkg or docker.
  always: the password never shows in stdout, stderr or the arguments of any command.
'''

from __future__ import annotations

import re

from pipeline import archivefs, firstrun, firstrun_stubs
from pipeline.firstrun import Run, Scenario, new_password
from pipeline.report import Report

MSG_WRONG = 'deploy: the password does not open the existing restic repository; nothing was written'
MSG_NO_TTY = ('deploy: restic password file is missing and no terminal is available; '
              'run docker/deploy.sh interactively once to set the password')
PROD_PATH = re.compile('/(var/lib/onedrive-backup|srv/(backup|archive)|etc/onedrive-backup|etc/default/onedrive-backup)')
OVERRIDABLE = re.compile('[$][{]ONEDRIVE_[A-Z_]+:-[^}]*[}]')
ABSOLUTE_TOOL = re.compile('(/usr/local/bin|/usr/sbin|/usr/bin|/sbin|/bin)/(dpkg|docker|systemctl|restic|findmnt|apt|apt-get)( |$)')


def _guard(report: Report) -> bool:
    '''Static isolation guard; False when the script could reach the real host and must not be run.'''
    if not firstrun.SCRIPT.is_file():
        report.product.append('docker/deploy.sh does not exist')
        return False
    safe = True
    text = archivefs.rewrite(firstrun.SCRIPT.read_text(encoding='utf-8'),
                             {archivefs.MOUNT: '/fixture/archive', archivefs.OLD_MOUNT: '/fixture/old-backup'})
    for number, raw in enumerate(text.splitlines(), 1):
        line = raw.strip()
        if line.startswith('#'):
            continue
        if ABSOLUTE_TOOL.search(line):
            report.env.append('docker/deploy.sh:%d calls a host tool by an absolute path; the stubs cannot isolate it: %s'
                              % (number, line))
            safe = False
        if PROD_PATH.search(line) and not OVERRIDABLE.search(line):
            report.env.append('docker/deploy.sh:%d names a production path without an overridable ONEDRIVE_* default; '
                              'the check refuses to run it: %s' % (number, line))
            safe = False
    for name in ('ONEDRIVE_SECRET_DIR', 'ONEDRIVE_DATA_DIR'):
        if name not in text:
            report.product.append('docker/deploy.sh honours no %s override: the secrets and repository paths are fixed, so '
                                  'the first-run behaviour cannot be isolated from the host' % name)
    return safe


def _common(report: Report, label: str, run: Run, scenario: Scenario, *passwords: str) -> None:
    if run.timed_out:
        report.product.append('%s: deploy.sh did not finish within the time limit' % label)
    if scenario.leaks(run, *passwords):
        report.product.append('%s: a password shows in the output or in the arguments of a command' % label)


def _stored(report: Report, label: str, scenario: Scenario, password: str) -> None:
    '''The password file holds password, mode 0600, owner root; dpkg ran only after it was stored.'''
    stored = scenario.password_text()
    if stored is None:
        report.product.append('%s: no restic password file was written' % label)
        return
    if stored != password:
        report.product.append('%s: the password file does not hold the entered password' % label)
    mode = scenario.password_file.stat().st_mode & 0o777
    if mode != 0o600:
        report.product.append('%s: the password file has mode %o, expected 600' % (label, mode))
    if not scenario.owned_by_root():
        report.product.append('%s: the password file is not owned by root (no root owner on the file, no chown or install -o root)' % label)
    dpkg = scenario.calls('dpkg')
    if len(dpkg) != 1 or not dpkg[0]['secret_exists'] or dpkg[0]['secret_mode'] != 0o600:
        report.product.append('%s: the package was not installed exactly once after the password file existed with mode 600: %s'
                              % (label, [(c['secret_exists'], c['secret_mode']) for c in dpkg]))


def _fails_closed(report: Report, label: str, run: Run, scenario: Scenario, message: str, before: tuple) -> None:
    if run.rc == 0:
        report.product.append('%s: exit 0, expected non-zero' % label)
    if message not in run.lines():
        report.product.append('%s: the exact line %r was not printed' % (label, message))
    if scenario.password_file.exists() or scenario.secrets_digest() != before[0]:
        report.product.append('%s: the secrets directory changed (a password file was created or overwritten)' % label)
    if scenario.repo_digest() != before[1]:
        report.product.append('%s: the restic repository changed' % label)
    if scenario.restic('init'):
        report.product.append('%s: restic init was called' % label)
    if scenario.replaced():
        report.product.append('%s: the running package or container was reached before the failure: %s' % (label, scenario.replaced()))


def _case1(report: Report) -> None:
    with Scenario() as scenario:
        pw = new_password()
        run = scenario.tty([pw, pw])
        label = 'case 1 first run'
        _common(report, label, run, scenario, pw)
        if run.rc != 0:
            report.product.append('%s: exit %d, expected 0 (prompts seen %d)' % (label, run.rc, len(run.prompts)))
        if len(run.prompts) != 2:
            report.product.append('%s: the password was asked %d time(s), expected twice' % (label, len(run.prompts)))
        if any(item['echo'] for item in run.prompts):
            report.product.append('%s: the terminal echoed while the password was typed' % label)
        _stored(report, label, scenario, pw)
        inits = scenario.restic('init')
        if len(inits) != 1 or not scenario.repo_opens_with(pw):
            report.product.append('%s: the repository was not initialised exactly once with the entered password (init calls %d)'
                                  % (label, len(inits)))
        elif inits[0]['repo'] != str(scenario.repo):
            report.product.append('%s: restic init targeted %s, expected the data directory restic-repo' % (label, inits[0]['repo']))
        low = run.text().lower()
        if not ('password' in low and re.search('warning|important|note', low) and re.search('copy|outside', low)):
            report.product.append('%s: no warning that the user must keep a copy of the password outside the host' % label)
    with Scenario() as scenario:
        first, second, third = new_password(), new_password(), new_password()
        run = scenario.tty([first, second, third, third])
        label = 'case 1 mismatch'
        _common(report, label, run, scenario, first, second, third)
        if run.rc != 0 or len(run.prompts) != 4:
            report.product.append('%s: a mismatch must ask again: exit %d, prompts %d, expected 0 and 4' % (label, run.rc, len(run.prompts)))
        _stored(report, label, scenario, third)
        if not scenario.repo_opens_with(third):
            report.product.append('%s: the repository was not initialised with the password confirmed last' % label)


def _case2(report: Report) -> None:
    with Scenario() as scenario:
        pw = new_password()
        firstrun_stubs.create_repo(str(scenario.repo), pw)
        before = scenario.repo_digest()
        run = scenario.tty([pw, pw])
        label = 'case 2 right password'
        _common(report, label, run, scenario, pw)
        if run.rc != 0 or not 1 <= len(run.prompts) <= 2:
            report.product.append('%s: exit %d with %d prompt(s), expected 0 with one or two' % (label, run.rc, len(run.prompts)))
        if any(item['echo'] for item in run.prompts):
            report.product.append('%s: the terminal echoed while the password was typed' % label)
        if scenario.restic('init') or not scenario.restic('!'):
            report.product.append('%s: the password was not verified by a read-only restic call, or restic init was called' % label)
        if scenario.repo_digest() != before:
            report.product.append('%s: the existing repository was modified' % label)
        _stored(report, label, scenario, pw)
    with Scenario() as scenario:
        pw, wrong = new_password(), new_password()
        firstrun_stubs.create_repo(str(scenario.repo), pw)
        before = (scenario.secrets_digest(), scenario.repo_digest())
        run = scenario.tty([wrong, wrong])
        label = 'case 2 wrong password'
        _common(report, label, run, scenario, pw, wrong)
        if run.stuck:
            report.product.append('%s: the script asked again instead of stopping' % label)
        if not scenario.restic('!'):
            report.product.append('%s: the password was not verified against the repository' % label)
        _fails_closed(report, label, run, scenario, MSG_WRONG, before)


def _case3(report: Report) -> None:
    for terminal in (True, False):
        with Scenario() as scenario:
            pw = new_password()
            firstrun_stubs.create_repo(str(scenario.repo), pw)
            scenario.password_file.write_text(pw + chr(10), encoding='utf-8')
            scenario.password_file.chmod(0o600)
            before = (scenario.secrets_digest(), scenario.repo_digest())
            run = scenario.tty([]) if terminal else scenario.plain(None)
            label = 'case 3 both present, %s' % ('terminal' if terminal else 'no terminal')
            _common(report, label, run, scenario, pw)
            if run.prompts or run.stuck:
                report.product.append('%s: the script asked for input although the repository and the password file exist' % label)
            if run.rc != 0 or len(scenario.calls('dpkg')) != 1:
                report.product.append('%s: exit %d, dpkg calls %d, expected 0 and 1' % (label, run.rc, len(scenario.calls('dpkg'))))
            if (scenario.secrets_digest(), scenario.repo_digest()) != before or scenario.restic('init'):
                report.product.append('%s: the password file or the repository was rewritten' % label)


def _case4(report: Report) -> None:
    for repo_exists in (False, True):
        for piped in (None, b'a-password-on-a-pipe' + chr(10).encode()):
            with Scenario(repo_password=new_password() if repo_exists else None) as scenario:
                before = (scenario.secrets_digest(), scenario.repo_digest())
                run = scenario.plain(piped)
                label = 'case 4 no terminal, repository %s, stdin %s' % ('present' if repo_exists else 'absent',
                                                                         'pipe' if piped else 'null device')
                _common(report, label, run, scenario, 'a-password-on-a-pipe')
                _fails_closed(report, label, run, scenario, MSG_NO_TTY, before)


def run() -> None:
    '''Raise CheckFailure when docker/deploy.sh does not meet the first-run password contract.'''
    report = Report()
    if _guard(report):
        _case1(report)
        _case2(report)
        _case3(report)
        _case4(report)
    report.info.append('real host state is outside the pipeline: nothing under /var/lib/onedrive-backup, /srv/archive, /srv/backup or /etc was touched; '
                       'the first-run initialisation of the host itself is done by the user (F5)')
    report.finish('deploy_first_run')
