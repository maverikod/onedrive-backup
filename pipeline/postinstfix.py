'''Disposable host of the postinst checks: runs a COPY of packaging/postinst with every absolute host path redirected.

The Debian maintainer script names /var/lib/onedrive-backup, /etc/onedrive-backup, /etc/default/onedrive-backup,
/usr/share/onedrive-backup, /usr/lib/onedrive-backup, /run/systemd/system and the data directory (/srv/archive, formerly
/srv/backup) as literals. The copy replaces each by a path under a temporary tree; the checks refuse to run it when
any host path survives the rewrite (an environment finding, never a pass). The stub commands of pipeline.host_stubs
stand in front of install, chown, chgrp, adduser, systemctl, id and findmnt; install only writes inside the temporary tree.
The real host is never read or written.
'''

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

from pipeline import archivefs, fixtures

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / 'packaging' / 'postinst'
TEMPLATE = ROOT / 'packaging' / 'defaults'
STUBS = ('install', 'chown', 'chgrp', 'adduser', 'systemctl', 'id', 'findmnt')


class Run:
    '''Outcome of one postinst run: exit code, text and the recorded stub calls.'''

    def __init__(self, rc: int, out: str, err: str, calls: list) -> None:
        self.rc, self.out, self.err, self.calls = rc, out, err, calls

    def installs(self) -> list[list[str]]:
        '''Recorded install calls without the command name.'''
        return [call[1:] for call in self.calls if call[0] == 'install']

    def escapes(self) -> list:
        '''Paths a stub refused because they lay outside the fixture.'''
        return [call for call in self.calls if call[0] == 'ESCAPE']


class Postinst:
    '''A temporary host for one or several runs of the postinst copy.'''

    def __init__(self) -> None:
        self.tmp = fixtures._work_dir('pi-')
        self.bin = self.tmp / 'bin'
        self.varlib = self.tmp / 'varlib'
        self.etc = self.tmp / 'etc-onedrive-backup'
        self.default = self.tmp / 'etc-default'
        self.share = self.tmp / 'share'
        self.lib = self.tmp / 'lib'
        self.archive = self.tmp / 'archive'
        self.other_mount = self.tmp / 'other-mount'
        self.old = self.tmp / 'old-backup'
        self.log = self.tmp / 'calls.log'
        self.extra_env: dict[str, str] = {}
        self.mapping = {'/var/lib/onedrive-backup': str(self.varlib), '/etc/onedrive-backup': str(self.etc),
                        '/etc/default/onedrive-backup': str(self.default), '/usr/share/onedrive-backup': str(self.share),
                        '/usr/lib/onedrive-backup': str(self.lib), '/run/systemd/system': str(self.tmp / 'no-systemd'),
                        archivefs.OLD_MOUNT: str(self.old), archivefs.MOUNT: str(self.archive)}
        for folder in (self.bin, self.share, self.lib, self.archive, self.other_mount):
            folder.mkdir()
        for name in STUBS:
            stub = self.bin / name
            stub.write_text('#!' + sys.executable + chr(10) + 'import sys' + chr(10) + 'sys.path.insert(0, '
                            + repr(str(ROOT)) + ')' + chr(10) + 'from pipeline.host_stubs import main'
                            + chr(10) + 'sys.exit(main(' + repr(name) + '))' + chr(10), encoding='utf-8')
            stub.chmod(0o755)
        runtime = self.lib / 'install-runtime.sh'
        runtime.write_text('#!/bin/sh' + chr(10) + 'exit 0' + chr(10), encoding='utf-8')
        runtime.chmod(0o755)
        template = TEMPLATE.read_text(encoding='utf-8') if TEMPLATE.is_file() else ''
        (self.share / 'defaults').write_text(archivefs.rewrite(template, self.mapping), encoding='utf-8')
        self.script = self.tmp / 'postinst'
        text = archivefs.rewrite(SCRIPT.read_text(encoding='utf-8'), self.mapping)
        self.script.write_text(text, encoding='utf-8')
        self.survivors = archivefs.leftovers(text)
        self.log.write_text('', encoding='utf-8')

    @property
    def data(self) -> Path:
        '''The built-in data directory of the fixture.'''
        return self.archive / 'onedrive-backup'

    @property
    def state(self) -> Path:
        '''The rclone state directory the postinst creates.'''
        return self.varlib / 'rclone-state'

    def set_default(self, data: Path | None) -> None:
        '''Write /etc/default/onedrive-backup with ONEDRIVE_DATA_DIR=data, or without that key when data is None.'''
        self.default.write_text(('ONEDRIVE_DATA_DIR=%s' % data + chr(10)) if data else '# no data directory key' + chr(10),
                                encoding='utf-8')
        self.default.chmod(0o644)

    def run(self, fs: str = 'ok', script: Path | None = None, args: tuple[str, ...] = ('configure',)) -> Run:
        '''Run the copy as postinst configure (or another script copy with args) under the stubs; fs is the findmnt mode of pipeline.archivefs.'''
        env = {'PATH': str(self.bin) + ':/usr/bin:/bin', 'HOME': str(self.tmp), 'STUB_LOG': str(self.log),
               'STUB_ROOT': str(self.tmp), 'STUB_UID': str(os.getuid()), 'STUB_GID': str(os.getgid())}
        env.update(archivefs.fs_env(fs, self.archive, self.data, self.other_mount))
        env.update(self.extra_env)
        self.log.write_text('', encoding='utf-8')
        done = subprocess.run(['sh', str(script or self.script)] + list(args), env=env, capture_output=True, text=True,
                              timeout=60, cwd=str(self.tmp))
        calls = [json.loads(line) for line in self.log.read_text(encoding='utf-8').splitlines() if line]
        return Run(done.returncode, done.stdout, done.stderr, calls)

    def close(self) -> None:
        fixtures._remove(self.tmp)

    def __enter__(self) -> 'Postinst':
        return self

    def __exit__(self, *_exc: object) -> None:
        self.close()

