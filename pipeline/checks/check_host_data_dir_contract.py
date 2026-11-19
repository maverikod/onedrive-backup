'''host_data_dir_contract: the host data directory is a plain directory on the archive filesystem (row PL1; decisions D8 and D9, rule R20).

Mode: script fixture over a COPY of packaging/docker-run.sh (/srv/archive names a temporary archive tree and a stub findmnt answers
the filesystem questions, pipeline.archivefs); the pipeline has no host access, so the live host state is proved separately with
terminal_host_exec. Rules: with a correct data directory (exists, owned by onedrive-backup, writable, not world-writable, a plain
directory, on the mounted /srv/archive filesystem: the baseline G1 of host_data_fs_guard) init, check, backup and discover run their
container work and start starts the container with the host directory bound at /data. The built-in default of ONEDRIVE_DATA_DIR is
/srv/archive/onedrive-backup. A missing, foreign-owned, read-only or world-writable directory fails closed for init and start:
non-zero exit, no container started or used, a message that is not empty and differs per cause. The same correct directory on a
filesystem that is not the mounted /srv/archive is refused (contrast G2; the cases of the guard are in host_data_fs_guard). Mount and
filesystem wording in the messages is allowed.
'''

from __future__ import annotations

import os
import shutil
from pathlib import Path

from pipeline import fixtures
from pipeline.report import Report

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / 'packaging' / 'docker-run.sh'
ACTIONS = (['init'], ['check'], ['backup'], ['backup', '--dry-run'], ['discover'], ['discover', '--dry-run'])
INIT_CAUSES = ('missing', 'wrong_owner', 'not_writable', 'world_writable')
START_CAUSES = ('missing', 'not_writable', 'world_writable')


def _damage(host: fixtures.Host, cause: str) -> int | None:
    '''Break the data directory in one way; return the uid the stub id must answer, or None for the default.'''
    if cause == 'missing':
        shutil.rmtree(host.data)
    elif cause == 'not_writable':
        host.data.chmod(0o555)
    elif cause == 'world_writable':
        host.data.chmod(0o777)
    elif cause == 'wrong_owner':
        return os.getuid() + 1
    return None


def _valid(report: Report) -> None:
    for args in ACTIONS:
        with fixtures.host() as host:
            result = host.run(SCRIPT, *args)
            if result.rc != 0 or not result.python_work():
                report.product.append('docker-run.sh %s with a correct plain host data directory: exit %d, python run in the container: %s, stderr: %s'
                                      % (' '.join(args), result.rc, result.python_work(), result.err.strip()))
    with fixtures.host() as host:
        result = host.run(SCRIPT, 'start', unset=('ONEDRIVE_DATA_DIR',))
        if result.rc != 0 or not result.docker('run'):
            report.product.append('docker-run.sh start without ONEDRIVE_DATA_DIR: the built-in default must be /srv/archive/onedrive-backup '
                                  '(the fixture data directory): exit %d, container started %s, stderr: %s'
                                  % (result.rc, bool(result.docker('run')), result.err.strip()[:200]))
        contrast = host.run(SCRIPT, 'init', fs='unmounted')
        if contrast.rc == 0 or contrast.container_work():
            report.product.append('docker-run.sh init with the same correct directory but /srv/archive not mounted: exit %d, container work %s; '
                                  'the data directory must be on the mounted /srv/archive filesystem (G2 contrast)'
                                  % (contrast.rc, contrast.container_work()))
    with fixtures.host() as host:
        result = host.run(SCRIPT, 'start')
        runs = result.docker('run')
        wanted = 'type=bind,src=%s,dst=/data' % host.data
        if result.rc != 0 or not runs:
            report.product.append('docker-run.sh start with a correct plain host data directory: exit %d, container started: %s, stderr: %s'
                                  % (result.rc, bool(runs), result.err.strip()))
        elif wanted not in runs[0]:
            report.product.append('docker-run.sh start did not bind the host data directory at /data; mounts: %s'
                                  % [item for item in runs[0] if item.startswith('type=bind')])


def _refusals(report: Report) -> None:
    messages: dict[str, str] = {}
    for cause in INIT_CAUSES:
        with fixtures.host() as host:
            uid = _damage(host, cause)
            result = host.run(SCRIPT, 'init', uid=uid)
            messages[cause] = result.err.strip()
            if result.rc == 0 or result.container_work() or not messages[cause]:
                report.product.append('init with data directory cause %s must fail closed with a message: exit %d, container work %s, stderr %r'
                                      % (cause, result.rc, result.container_work(), messages[cause]))
    if len(set(messages.values())) < len(messages):
        report.product.append('refusals for different data directory causes are indistinguishable: %s' % messages)
    for cause in START_CAUSES:
        with fixtures.host() as host:
            _damage(host, cause)
            result = host.run(SCRIPT, 'start')
            if result.rc == 0 or result.docker('run'):
                report.product.append('start with data directory cause %s must fail closed: exit %d, container started %s (scaffold fallback of the start branch of docker-run.sh)'
                                      % (cause, result.rc, bool(result.docker('run'))))


def run() -> None:
    '''Raise CheckFailure when the host contract of the data directory is not met.'''
    report = Report()
    _valid(report)
    _refusals(report)
    report.info.append('host state of production is outside the pipeline; prove it with terminal_host_exec (stat, findmnt), read-only')
    report.finish('host_data_dir_contract')
