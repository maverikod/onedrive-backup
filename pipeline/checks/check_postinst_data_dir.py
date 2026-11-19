'''postinst_data_dir: the postinst never creates the data directory and creates the rclone state directory (row PL12, decisions D9 and D10).

Mode: source-static plus script fixture over a COPY of packaging/postinst in which every absolute host path names a temporary tree
(pipeline.postinstfix); the copy runs under stub install, chown, chgrp, adduser, systemctl, id and findmnt, so nothing of the real
host is read or written. P1 static: postinst contains no install -d and no mkdir that names the data directory (data_dir), and the step
'create it when absent' of 0.3.12 is gone. P2: the state directory /var/lib/onedrive-backup/rclone-state is created with
install -d -m 0700 -o onedrive-backup -g onedrive-backup; a second run changes nothing and does not fail. P3: the refusals of host_data_fs_guard
G8 and G9 as postinst contract: with /srv/archive not mounted or the directory on the root filesystem exit 2 and no change of the
data directory; with the directory missing exit 2 with 'Host data directory does not exist' and the directory is NOT created, neither on
the root filesystem nor on /srv/archive; with a correct directory exit 0 and the directory is left as it was.
'''

from __future__ import annotations

import re
from pathlib import Path

from pipeline import firstrun, postinstfix
from pipeline.report import Report

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / 'packaging' / 'postinst'
CREATES = re.compile(r'\b(install\s+-d|mkdir)\b')


def _static(report: Report) -> None:
    for number, raw in enumerate(SCRIPT.read_text(encoding='utf-8').splitlines(), 1):
        line = raw.strip()
        if line.startswith('#'):
            continue
        if CREATES.search(line) and '$data_dir' in line:
            report.product.append('P1 packaging/postinst:%d creates the data directory: %s' % (number, line))
    text = SCRIPT.read_text(encoding='utf-8')
    if re.search(r'if \[ ! -e "\$data_dir" \]', text):
        report.product.append('P1 packaging/postinst still has the step that creates the data directory when it is absent (test of "$data_dir")')


def _state_directory(report: Report) -> None:
    with postinstfix.Postinst() as host:
        if host.survivors:
            report.env.append('the postinst copy still names the host paths %s after the rewrite; not run' % host.survivors)
            return
        host.data.mkdir(mode=0o750)
        host.set_default(None)
        first = host.run()
        wanted = ['-d', '-m', '0700', '-o', 'onedrive-backup', '-g', 'onedrive-backup']
        made = [call for call in first.installs() if call[:7] == wanted and str(host.state) in call]
        if first.rc != 0 or not host.state.is_dir():
            report.product.append('P2 postinst run 1: exit %d, state directory %s exists %s, stderr %r'
                                   % (first.rc, host.state, host.state.is_dir(), first.err.strip()[:200]))
            return
        if not made:
            report.product.append('P2 postinst did not create %s with install -d -m 0700 -o onedrive-backup -g onedrive-backup; install calls: %s'
                                  % (host.state, [call for call in first.installs() if str(host.state) in ' '.join(call)]))
        if (host.state.stat().st_mode & 0o777) != 0o700:
            report.product.append('P2 the state directory has mode %o, expected 700' % (host.state.stat().st_mode & 0o777))
        marker = host.state / 'rclone.conf'
        marker.write_text('SENTINEL-state-copy', encoding='utf-8')
        before = firstrun.tree_digest(host.state)
        second = host.run()
        if second.rc != 0 or firstrun.tree_digest(host.state) != before:
            report.product.append('P2 postinst run 2 is not idempotent: exit %d, the state directory content or mode changed' % second.rc)


def _refusals(report: Report) -> None:
    for label, mode in (('/srv/archive not mounted', 'unmounted'), ('data directory on the root filesystem', 'root')):
        with postinstfix.Postinst() as host:
            if host.survivors:
                return
            host.data.mkdir(mode=0o750)
            host.set_default(None)
            before = firstrun.tree_digest(host.data)
            result = host.run(fs=mode)
            if result.rc != 2 or firstrun.tree_digest(host.data) != before or 'archive' not in result.err.lower():
                report.product.append('P3 postinst, %s: exit %d (expected 2), data directory changed %s, stderr %r'
                                      % (label, result.rc, firstrun.tree_digest(host.data) != before, result.err.strip()[:200]))
    with postinstfix.Postinst() as host:
        if host.survivors:
            return
        host.set_default(None)
        result = host.run(fs='ok')
        created = [str(path) for path in (host.data, host.old / 'onedrive') if path.exists()]
        if result.rc != 2 or 'does not exist' not in result.err or created:
            report.product.append('P3 postinst with the data directory missing: exit %d (expected 2), stderr %r, created %s; the directory must '
                                  'never be created by postinst' % (result.rc, result.err.strip()[:200], created))
    with postinstfix.Postinst() as host:
        if host.survivors:
            return
        host.data.mkdir(mode=0o750)
        (host.data / 'mirror').mkdir()
        host.set_default(None)
        before = firstrun.tree_digest(host.data)
        result = host.run(fs='ok')
        if result.rc != 0 or firstrun.tree_digest(host.data) != before or Path(host.data).stat().st_mode & 0o777 != 0o750:
            report.product.append('P3 postinst with a correct data directory: exit %d, the directory was changed %s'
                                  % (result.rc, firstrun.tree_digest(host.data) != before))


def run() -> None:
    '''Raise CheckFailure when postinst creates the data directory or does not create the rclone state directory.'''
    report = Report()
    _static(report)
    _state_directory(report)
    _refusals(report)
    report.finish('postinst_data_dir')
