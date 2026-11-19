'''host_data_fs_guard: the data directory must lie on the mounted /srv/archive filesystem (row PL9, decision D9, rules R19, R16).

Mode: script fixture over COPIES of packaging/docker-run.sh, docker/deploy.sh and packaging/postinst in which /srv/archive names a
temporary archive tree and a stub findmnt answers as the case says (pipeline.archivefs); nothing under the real /srv/archive or
/srv/backup is touched and no real docker, dpkg, restic or install runs. The live host state is proved separately, read-only,
with terminal_host_exec.

Guard condition (one definition for the three scripts): D is the realpath of the resolved data directory; the guard passes only
when /srv/archive is a mount point, D is /srv/archive or lies below it after symlink resolution, and findmnt -T D answers
/srv/archive or a path below it, never /. Cases (10.16.7): G1 passes; G2 /srv/archive not mounted; G3 mounted but D on the root
filesystem; G4 D on another mounted filesystem; G5 D a symlink; G6 D its own sub-mount; G7 deploy.sh refuses before dpkg and
before any prompt; G8 postinst refuses; G9 postinst never creates a missing data directory; G10 stop, status and ports do not
evaluate the guard.
Refusal contract: docker-run.sh and deploy.sh exit 1, postinst exits 2; one stderr line prefixed by the script name
('onedrive-backup-docker: ', 'deploy.sh: ', 'onedrive-backup: ') names the resolved data path and its filesystem and states that
/srv/archive is not mounted or the directory is not on it; it differs from every pre-existing refusal text; no container is
started, stopped, removed or entered, no dpkg runs, no repository or password is created and nothing is written in the data directory.
'''

from __future__ import annotations

import os
import shutil
from pathlib import Path

from pipeline import archivefs, firstrun, fixtures, postinstfix
from pipeline.report import Report

ROOT = Path(__file__).resolve().parents[2]
RUN = ROOT / 'packaging' / 'docker-run.sh'
ACTIONS = (['start'], ['init'], ['check'], ['backup'], ['backup', '--dry-run'], ['discover'], ['discover', '--dry-run'])
CONTAINER_VERBS = ('run', 'rm', 'exec')
RUN_PREFIX = 'onedrive-backup-docker: '
DEPLOY_PREFIX = 'deploy.sh: '
POSTINST_PREFIX = 'onedrive-backup: '
REFUSALS = (('G2 /srv/archive is not mounted', 'unmounted'), ('G3 mounted, data directory on the root filesystem', 'root'))
PRE_EXISTING_DEPLOY = {'deploy: restic password file is missing and no terminal is available; '
                       'run docker/deploy.sh interactively once to set the password'}


def _container_calls(result: fixtures.Result) -> list[str]:
    return [call[1] for call in result.calls if call[0] == 'docker' and len(call) > 1 and call[1] in CONTAINER_VERBS]


def _known_refusals() -> set[str]:
    '''The refusal texts of docker-run.sh that exist before the guard: one line per damaged data directory.'''
    known: set[str] = set()
    for cause in ('missing', 'wrong_owner', 'not_writable', 'world_writable'):
        with fixtures.host() as host:
            uid = None
            if cause == 'missing':
                shutil.rmtree(host.data)
            elif cause == 'not_writable':
                host.data.chmod(0o555)
            elif cause == 'world_writable':
                host.data.chmod(0o777)
            else:
                uid = os.getuid() + 1
            known.add(host.run(RUN, 'init', uid=uid).err.strip())
    return known


def _docker_run(report: Report, others: set[str]) -> None:
    cases = (REFUSALS[0] + ('inside',), REFUSALS[1] + ('inside',),
             ('G3 data directory outside the archive on the root filesystem', 'root', 'outside'),
             ('G4 data directory on another mounted filesystem', 'other', 'outside'))
    for label, mode, where in cases:
        for args in ACTIONS:
            with fixtures.host() as host:
                data = host.data if where == 'inside' else host.elsewhere
                result = host.run(RUN, *args, data=data, fs=mode)
                name = '%s: docker-run.sh %s' % (label, ' '.join(args))
                found = []
                if result.rc != 1:
                    found.append('exit %d, expected the filesystem guard to refuse with exit 1' % result.rc)
                if _container_calls(result):
                    found.append('docker %s was called' % _container_calls(result))
                words = archivefs.fs_words(mode, host.archive, host.other_mount)
                found.extend(archivefs.message_problems('message', result.err, result.out, data.resolve(), RUN_PREFIX, words, others))
                if found:
                    report.product.append('%s: %s' % (name, '; '.join(found)))


def _passes(report: Report) -> None:
    for label, mode in (('G1 guard passes', 'ok'), ('G6 data directory is its own sub-mount', 'submount')):
        for args in ACTIONS[1:]:
            with fixtures.host() as host:
                result = host.run(RUN, *args, fs=mode)
                if result.rc != 0 or not result.python_work():
                    report.product.append('%s: docker-run.sh %s: exit %d, python run in the container: %s, stderr: %s'
                                          % (label, ' '.join(args), result.rc, result.python_work(), result.err.strip()[:200]))
        with fixtures.host() as host:
            result = host.run(RUN, 'start', fs=mode)
            runs = result.docker('run')
            if result.rc != 0 or not runs or 'type=bind,src=%s,dst=/data' % host.data not in runs[0]:
                report.product.append('%s: docker-run.sh start: exit %d, container started %s, /data bound from the data directory %s'
                                      % (label, result.rc, bool(runs), bool(runs) and 'type=bind,src=%s,dst=/data' % host.data in runs[0]))


def _symlink(report: Report, others: set[str]) -> None:
    for action in (['init'], ['start']):
        with fixtures.host() as host:
            link = host.archive / 'link'
            link.symlink_to(host.elsewhere)
            result = host.run(RUN, *action, data=link, fs='root')
            name = 'G5 data directory is a symlink to the root filesystem: docker-run.sh %s' % action[0]
            if result.rc == 0 or _container_calls(result):
                report.product.append('%s: exit %d, container calls %s; expected a refusal without a container'
                                      % (name, result.rc, _container_calls(result)))
            if str(link) not in result.err and str(host.elsewhere) not in result.err:
                report.product.append('%s: the message names neither the link nor its target: %r' % (name, result.err.strip()[:200]))


def _unaffected(report: Report) -> None:
    for action in (['stop'], ['status'], ['ports']):
        with fixtures.host() as host:
            result = host.run(RUN, *action, fs='unmounted')
            if result.rc != 0 or any(call[0] == 'findmnt' for call in result.calls):
                report.product.append('G10 docker-run.sh %s with /srv/archive not mounted: exit %d, findmnt calls %d; it must not evaluate the guard'
                                      % (action[0], result.rc, sum(1 for call in result.calls if call[0] == 'findmnt')))


def _deploy(report: Report) -> None:
    for label, mode in REFUSALS:
        scenarios = (('both password file and repository present', {'repo_password': 'p-fixture', 'file_password': 'p-fixture'}, False),
                     ('first run on a terminal', {}, True))
        for case, kwargs, terminal in scenarios:
            with firstrun.Scenario(fs=mode, **kwargs) as scenario:
                before = (scenario.secrets_digest(), scenario.repo_digest(), firstrun.tree_digest(scenario.data))
                run = scenario.tty(['Pw-fixture-1', 'Pw-fixture-1']) if terminal else scenario.plain(None)
                name = 'G7 deploy.sh, %s, %s' % (label, case)
                if run.rc != 1:
                    report.product.append('%s: exit %d, expected 1' % (name, run.rc))
                if scenario.replaced() or scenario.restic():
                    report.product.append('%s: reached %s and %d restic call(s) before the refusal'
                                          % (name, scenario.replaced() or 'no package step', len(scenario.restic())))
                if run.prompts or run.sent:
                    report.product.append('%s: the password was asked (%d prompt(s)) before the refusal' % (name, len(run.prompts)))
                after = (scenario.secrets_digest(), scenario.repo_digest(), firstrun.tree_digest(scenario.data))
                if after != before:
                    report.product.append('%s: the secrets directory, the repository or the data directory changed' % name)
                words = archivefs.fs_words(mode, scenario.archive, scenario.other_mount)
                report.product.extend(archivefs.message_problems(name, run.text() if terminal else run.err,
                                                                 '' if terminal else run.out, scenario.data.resolve(),
                                                                 DEPLOY_PREFIX, words, PRE_EXISTING_DEPLOY))


def _postinst(report: Report) -> None:
    for label, mode in REFUSALS:
        with postinstfix.Postinst() as host:
            if host.survivors:
                report.env.append('the postinst copy still names the host paths %s after the rewrite; not run' % host.survivors)
                return
            host.data.mkdir(mode=0o750)
            host.set_default(None)
            before = firstrun.tree_digest(host.data)
            result = host.run(fs=mode)
            name = 'G8 postinst, %s' % label
            if result.rc != 2:
                report.product.append('%s: exit %d, expected 2' % (name, result.rc))
            if firstrun.tree_digest(host.data) != before or any(str(host.data) in ' '.join(call) for call in result.calls
                                                                 if call[0] in ('install', 'chown', 'chgrp')):
                report.product.append('%s: the data directory %s was created, changed or handed to another owner' % (name, host.data))
            report.product.extend(archivefs.message_problems(name, result.err, result.out, host.data.resolve(), POSTINST_PREFIX,
                                                             archivefs.fs_words(mode, host.archive, host.other_mount),
                                                             {'onedrive-backup: ONEDRIVE_DATA_DIR must be absolute'}))
    with postinstfix.Postinst() as host:
        if host.survivors:
            return
        host.set_default(None)
        result = host.run(fs='ok')
        name = 'G9 postinst, /srv/archive mounted and the data directory missing'
        if host.data.exists():
            report.product.append('%s: the data directory %s was created; postinst must never create it' % (name, host.data))
        if result.rc != 2 or 'does not exist' not in result.err or str(host.data) not in result.err:
            report.product.append('%s: exit %d, stderr %r; expected exit 2 and a line "Host data directory does not exist" naming %s'
                                  % (name, result.rc, result.err.strip()[:200], host.data))
    with postinstfix.Postinst() as host:
        if host.survivors:
            return
        host.data.mkdir(mode=0o750)
        host.set_default(None)
        result = host.run(fs='ok')
        if result.rc != 0 or result.escapes():
            report.product.append('G1 postinst with the guard passing: exit %d, stderr %r' % (result.rc, result.err.strip()[:200]))


def run() -> None:
    '''Raise CheckFailure when a script accepts a data directory that is not on the mounted /srv/archive.'''
    report = Report()
    others = _known_refusals()
    _passes(report)
    _docker_run(report, others)
    _symlink(report, others)
    _unaffected(report)
    _deploy(report)
    _postinst(report)
    report.info.append('host state of production is outside the pipeline; prove it with terminal_host_exec (findmnt, stat), read-only')
    report.finish('host_data_fs_guard')
