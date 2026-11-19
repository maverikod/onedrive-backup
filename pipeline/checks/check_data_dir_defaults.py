'''data_dir_defaults: every built-in default of the data directory names /srv/archive/onedrive-backup (row PL10, decision D9, rule R20).

Mode: source-static plus script fixture. D1: none of docker/deploy.sh, packaging/docker-run.sh, packaging/defaults, packaging/postinst,
packaging/config.json, docker/compose.yml, docker/container.env.example, README.md, AGENTS.md, CLAUDE.md and
src/onedrive_api/ONEDRIVE_INFO.md contains /srv/backup (past CHANGELOG.md entries are history and are not scanned). D2: deploy.sh,
docker-run.sh, defaults, postinst, compose.yml and container.env.example all name /srv/archive/onedrive-backup. D3: packaging/config.json
has required_mountpoint /srv/archive and mirror_dir and repository_dir below /srv/archive/onedrive-backup. D4: the standards line of
CLAUDE.md and AGENTS.md is the replacement text of 10.16.3. D5: precedence R20 with stubs: ONEDRIVE_DATA_DIR from the environment wins over
/etc/default/onedrive-backup, which wins over the built-in default (docker-run.sh reads the environment and the built-in default only;
postinst reads /etc/default and the built-in default only); the filesystem guard is applied to the resolved value (host_data_fs_guard).
'''

from __future__ import annotations

import json
from pathlib import Path

from pipeline import firstrun, fixtures, postinstfix
from pipeline.report import Report

ROOT = Path(__file__).resolve().parents[2]
SCANNED = ('docker/deploy.sh', 'packaging/docker-run.sh', 'packaging/defaults', 'packaging/postinst', 'packaging/config.json',
           'docker/compose.yml', 'docker/container.env.example', 'README.md', 'AGENTS.md', 'CLAUDE.md',
           'src/onedrive_api/ONEDRIVE_INFO.md')
DEFAULTS = ('docker/deploy.sh', 'packaging/docker-run.sh', 'packaging/defaults', 'packaging/postinst', 'docker/compose.yml',
            'docker/container.env.example')
OLD = '/srv/backup'
NEW = '/srv/archive/onedrive-backup'
STANDARD = ('Data volume /srv/archive/onedrive-backup must be backed by the mounted /srv/archive filesystem; '
            'deploy, postinst and every docker-run.sh action refuse otherwise.')


def _read(rel: str) -> str | None:
    path = ROOT / rel
    return path.read_text(encoding='utf-8') if path.is_file() else None


def _static(report: Report) -> None:
    for rel in SCANNED:
        text = _read(rel)
        if text is None:
            report.product.append('D1 %s does not exist' % rel)
            continue
        for number, line in enumerate(text.splitlines(), 1):
            if OLD in line:
                report.product.append('D1 %s:%d still names %s: %s' % (rel, number, OLD, line.strip()[:120]))
    for rel in DEFAULTS:
        text = _read(rel)
        if text is not None and NEW not in text:
            report.product.append('D2 %s does not name the default data directory %s' % (rel, NEW))
    text = _read('packaging/config.json')
    try:
        config = json.loads(text or '')
    except ValueError:
        report.product.append('D3 packaging/config.json is not valid JSON')
        return
    if config.get('required_mountpoint') != '/srv/archive':
        report.product.append('D3 packaging/config.json required_mountpoint is %r, expected /srv/archive' % config.get('required_mountpoint'))
    for key in ('mirror_dir', 'repository_dir'):
        if not str(config.get(key, '')).startswith(NEW + '/'):
            report.product.append('D3 packaging/config.json %s is %r, expected a path below %s' % (key, config.get(key), NEW))
    for rel in ('CLAUDE.md', 'AGENTS.md'):
        if STANDARD not in (_read(rel) or ''):
            report.product.append('D4 %s does not carry the standards line %r' % (rel, STANDARD))


def _precedence_docker_run(report: Report) -> None:
    script = ROOT / 'packaging' / 'docker-run.sh'
    with fixtures.host() as host:
        result = host.run(script, 'start', unset=('ONEDRIVE_DATA_DIR',))
        runs = result.docker('run')
        if result.rc != 0 or not runs or 'type=bind,src=%s,dst=/data' % host.data not in runs[0]:
            report.product.append('D5 docker-run.sh start with ONEDRIVE_DATA_DIR unset did not bind the built-in default %s (the fixture '
                                  'archive/onedrive-backup): exit %d, container started %s, stderr: %s'
                                  % (NEW, result.rc, bool(runs), result.err.strip()[:200]))
    with fixtures.host() as host:
        chosen = host.archive / 'chosen'
        chosen.mkdir(mode=0o750)
        result = host.run(script, 'start', data=chosen)
        runs = result.docker('run')
        if result.rc != 0 or not runs or 'type=bind,src=%s,dst=/data' % chosen not in runs[0]:
            report.product.append('D5 docker-run.sh start: ONEDRIVE_DATA_DIR from the environment did not win over the built-in default: '
                                  'exit %d, container started %s' % (result.rc, bool(runs)))


def _precedence_deploy(report: Report) -> None:
    for label, in_env, in_file in (('environment wins over the defaults file', True, True),
                                   ('defaults file wins over the built-in default', False, True),
                                   ('built-in default when neither names a directory', False, False)):
        with firstrun.Scenario() as scenario:
            env_data, file_data = scenario.archive / 'env-data', scenario.archive / 'file-data'
            env_data.mkdir(mode=0o750)
            file_data.mkdir(mode=0o750)
            if in_env:
                scenario.env_set['ONEDRIVE_DATA_DIR'] = str(env_data)
            else:
                scenario.env_drop.add('ONEDRIVE_DATA_DIR')
            lines = ['ONEDRIVE_SECRET_DIR=%s' % scenario.secrets] + (['ONEDRIVE_DATA_DIR=%s' % file_data] if in_file else [])
            scenario.defaults.write_text(chr(10).join(lines) + chr(10), encoding='utf-8')
            expected_dir = env_data if in_env else file_data if in_file else scenario.data
            run = scenario.tty(['Pw-fixture-1', 'Pw-fixture-1'])
            inits = scenario.restic('init')
            expected = str(expected_dir / 'restic-repo')
            if run.rc != 0 or len(inits) != 1 or inits[0]['repo'] != expected:
                report.product.append('D5 deploy.sh, %s: exit %d, restic init repository %s, expected %s'
                                      % (label, run.rc, [item['repo'] for item in inits], expected))


def _precedence_postinst(report: Report) -> None:
    with postinstfix.Postinst() as host:
        if host.survivors:
            report.env.append('the postinst copy still names the host paths %s after the rewrite; not run' % host.survivors)
            return
        custom = host.archive / 'custom'
        custom.mkdir(mode=0o750)
        host.set_default(custom)
        result = host.run()
        if result.rc != 0 or host.data.exists():
            report.product.append('D5 postinst: ONEDRIVE_DATA_DIR of /etc/default did not win over the built-in default: exit %d, stderr %r, '
                                  'built-in directory created %s' % (result.rc, result.err.strip()[:200], host.data.exists()))
    with postinstfix.Postinst() as host:
        host.set_default(None)
        result = host.run()
        created = [str(path) for path in (host.data, host.old / 'onedrive') if path.exists()]
        if result.rc != 2 or str(host.data) not in result.err or created:
            report.product.append('D5 postinst without ONEDRIVE_DATA_DIR in /etc/default: exit %d, stderr %r, created %s; expected the built-in '
                                  'default %s to be resolved and refused because the directory does not exist (exit 2, nothing created)'
                                  % (result.rc, result.err.strip()[:200], created, NEW))


def run() -> None:
    '''Raise CheckFailure when a default data directory is not /srv/archive/onedrive-backup or the precedence is wrong.'''
    report = Report()
    _static(report)
    _precedence_docker_run(report)
    _precedence_deploy(report)
    _precedence_postinst(report)
    report.info.append('the live host already has ONEDRIVE_DATA_DIR=%s in /etc/default/onedrive-backup; prove it with terminal_host_exec' % NEW)
    report.finish('data_dir_defaults')
