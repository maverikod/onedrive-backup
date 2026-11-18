'''container_data_mount: inside the container /data must be a real mount point (row PL2, decision D8).

Mode: process fixture. The four operator entry points of the image run as the container runs them
(ONEDRIVE_SCAFFOLD_MODE=0): init, check and backup of onedrive_backup, discover of sharepoint_discover_cli and
the sharepoint_backup run. Pointed at a plain directory that is not a mount point, each refuses with a
non-zero exit, names the cause with the code STORAGE_NOT_MOUNTED (the code discover and the SharePoint
backup already use) and creates nothing in that directory. Pointed at a real mount point the same entry
points never answer with that code (positive control).
'''

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

from pipeline import fixtures
from pipeline.report import Report

ROOT = Path(__file__).resolve().parents[2]
CODE = 'STORAGE_NOT_MOUNTED'
MOUNT_CANDIDATES = ('/tmp', '/dev/shm', '/proc', '/sys')


def _config(tmp: Path, mount: Path, base: Path) -> Path:
    secrets = tmp / 'secrets'
    secrets.mkdir(exist_ok=True)
    config = {'onedrive_remote': 'onedrive:', 'rclone_config': str(secrets / 'rclone.conf'),
              'mirror_dir': str(base / 'mirror'), 'repository_dir': str(base / 'restic-repo'),
              'password_file': str(secrets / 'restic-password'), 'lock_file': str(base / 'backup.lock'),
              'required_mountpoint': str(mount)}
    path = tmp / ('backup-%s.json' % abs(hash(str(base))))
    path.write_text(json.dumps(config), encoding='utf-8')
    return path


def _entries(config: Path, data: Path) -> list[tuple[str, list[str]]]:
    python = sys.executable
    return [('init', [python, '-m', 'onedrive_backup', '--config', str(config), 'init']),
            ('check', [python, '-m', 'onedrive_backup', '--config', str(config), 'check']),
            ('backup', [python, '-m', 'onedrive_backup', '--config', str(config), 'backup', '--dry-run']),
            ('discover', [python, '-m', 'onedrive_api.sharepoint_discover_cli', '--backup-config', str(config),
                          '--data', str(data), '--dry-run']),
            ('sharepoint backup', [python, '-m', 'onedrive_api.sharepoint_backup', '--config', str(config),
                                   '--data', str(data), '--dry-run'])]


def _run(command: list[str], tmp: Path) -> tuple[int, str]:
    env = {'PATH': os.environ.get('PATH', '/usr/bin:/bin'), 'PYTHONPATH': str(ROOT / 'src'), 'HOME': str(tmp),
           'ONEDRIVE_SCAFFOLD_MODE': '0', 'PYTHONDONTWRITEBYTECODE': '1'}
    done = subprocess.run(command, env=env, capture_output=True, text=True, timeout=60, cwd=str(tmp))
    return done.returncode, done.stdout + done.stderr


def run() -> None:
    '''Raise CheckFailure when an entry point accepts or mislabels a /data that is not a mount point.'''
    report = Report()
    fixtures.WORK.mkdir(exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='b3-mount-', dir=str(fixtures.WORK)) as raw:
        tmp = Path(raw)
        plain = tmp / 'plain-data'
        plain.mkdir()
        for name, command in _entries(_config(tmp, plain, plain), plain):
            rc, text = _run(command, tmp)
            if rc == 0 or CODE not in text:
                report.product.append('%s on /data that is not a mount point: exit %d, code %s present: %s; output: %s'
                                      % (name, rc, CODE, CODE in text, ' '.join(text.split())[:240]))
            if any(plain.iterdir()):
                report.product.append('%s created %s in the unmounted /data before refusing'
                                      % (name, sorted(p.name for p in plain.iterdir())))
                for leftover in plain.iterdir():
                    shutil.rmtree(leftover) if leftover.is_dir() else leftover.unlink()
        mounted = next((Path(item) for item in MOUNT_CANDIDATES if os.path.ismount(item)), None)
        if mounted is None:
            report.env.append('no real mount point found among %s for the positive control' % (MOUNT_CANDIDATES,))
        else:
            base = tmp / 'on-mount'
            for name, command in _entries(_config(tmp, mounted, base), mounted):
                rc, text = _run(command, tmp)
                if CODE in text:
                    report.product.append('%s refuses a real mount point (%s) with %s: %s'
                                          % (name, mounted, CODE, ' '.join(text.split())[:240]))
    report.finish('container_data_mount')
