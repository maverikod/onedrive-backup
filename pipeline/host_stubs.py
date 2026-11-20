'''Stub commands of the packaging-script fixtures: docker, mountpoint, findmnt, id, install, mv, chown, chgrp, adduser, systemctl.

Every call is appended to the JSON-lines file named by STUB_LOG. mountpoint always fails (the host
backup directory is a plain directory, decision D8; the filesystem questions of decision D9 go to findmnt, which
answers from FS_MOUNT_ROOT, FS_MOUNTED, FS_TARGET and FS_SOURCE, see pipeline.archivefs); id answers the uid and gid in
STUB_UID and STUB_GID for the user onedrive-backup; docker succeeds and reports a running container. install (its destinations) and mv
really change files, but only under STUB_ROOT: any other path is logged as an escape and refused with exit 99, so a script
that names a real host path can never touch it. chown, chgrp and adduser only log. systemctl only logs, except when
STUB_UNITS names a JSON file: then it keeps the enabled and active state of every unit in that file (enable, disable, start,
stop, restart, is-enabled, is-active; --now; daemon-reload changes nothing) and answers the state queries like systemd does.
'''

from __future__ import annotations

import json
import os
import shutil
import sys

from pipeline import archivefs


def _log(entry: list[str]) -> None:
    with open(os.environ['STUB_LOG'], 'a', encoding='utf-8') as fp:
        fp.write(json.dumps(entry) + chr(10))


def _inside(path: str) -> bool:
    root = os.path.realpath(os.environ.get('STUB_ROOT', '/nonexistent'))
    real = os.path.realpath(path)
    return real == root or real.startswith(root + os.sep)


def _escape(paths: list[str]) -> bool:
    bad = [item for item in paths if not _inside(item)]
    if bad:
        _log(['ESCAPE'] + bad)
        sys.stderr.write('stub: refused a path outside the fixture: %s' % bad + chr(10))
    return bool(bad)


def _install(args: list[str]) -> int:
    directory, mode, operands, index = False, None, [], 0
    while index < len(args):
        item = args[index]
        if item in ('-d', '--directory'):
            directory = True
        elif item in ('-m', '--mode'):
            index += 1
            mode = args[index]
        elif item.startswith('--mode='):
            mode = item.split('=', 1)[1]
        elif item in ('-o', '-g', '--owner', '--group'):
            index += 1
        elif not item.startswith('-') or item == '-':
            operands.append(item)
        index += 1
    if _escape(operands if directory else operands[-1:]):
        return 99
    if directory:
        for item in operands:
            os.makedirs(item, exist_ok=True)
            os.chmod(item, int(mode, 8) if mode else 0o755)
        return 0
    source, target = operands[-2], operands[-1]
    if os.path.isdir(target):
        target = os.path.join(target, os.path.basename(source))
    shutil.copyfile(source, target)
    os.chmod(target, int(mode, 8) if mode else 0o755)
    return 0


def _systemctl(args: list[str]) -> int:
    '''Stateful systemctl of the timer fixtures: the unit state lives in the JSON file STUB_UNITS.'''
    path = os.environ['STUB_UNITS']
    state = json.load(open(path, encoding='utf-8')) if os.path.exists(path) else {}
    words = [item for item in args if not item.startswith('-')]
    verb, units, now = (words[0] if words else ''), words[1:], '--now' in args
    code = 0
    for unit in units:
        entry = state.setdefault(unit, {'enabled': False, 'active': False})
        if verb in ('enable', 'disable'):
            entry['enabled'] = verb == 'enable'
            if now:
                entry['active'] = verb == 'enable'
        elif verb in ('start', 'restart'):
            entry['active'] = True
        elif verb == 'stop':
            entry['active'] = False
        elif verb in ('is-enabled', 'is-active'):
            key = 'enabled' if verb == 'is-enabled' else 'active'
            if not ('--quiet' in args or '-q' in args):
                print(('enabled' if key == 'enabled' else 'active') if entry[key] else ('disabled' if key == 'enabled' else 'inactive'))
            code = code or (0 if entry[key] else (1 if key == 'enabled' else 3))
    with open(path, 'w', encoding='utf-8') as fp:
        json.dump(state, fp)
    return code


def main(name: str) -> int:
    '''Behave as the stubbed command called name.'''
    args = sys.argv[1:]
    if name == 'docker':
        _log(['docker'] + args)
        if args[:1] == ['inspect'] and '--format' in args:
            print('true')
        return 0
    if name == 'mountpoint':
        _log(['mountpoint'] + args)
        return 1
    if name == 'findmnt':
        _log(['findmnt'] + args)
        code, text = archivefs.findmnt(args, dict(os.environ))
        sys.stdout.write(text)
        return code
    if name == 'id':
        if args == ['-u', 'onedrive-backup']:
            print(os.environ['STUB_UID'])
            return 0
        if args == ['-g', 'onedrive-backup']:
            print(os.environ['STUB_GID'])
            return 0
        if args == ['onedrive-backup']:
            print('uid=%s(onedrive-backup) gid=%s(onedrive-backup)' % (os.environ['STUB_UID'], os.environ['STUB_GID']))
            return 0
        os.execv('/usr/bin/id', ['id'] + args)
    if name == 'install':
        _log(['install'] + args)
        return _install(args)
    if name == 'mv':
        _log(['mv'] + args)
        operands = [item for item in args if not item.startswith('-')]
        if _escape(operands):
            return 99
        os.execv('/usr/bin/mv', ['mv'] + args)
    if name == 'systemctl' and os.environ.get('STUB_UNITS'):
        _log([name] + args)
        return _systemctl(args)
    if name in ('chown', 'chgrp', 'adduser', 'systemctl'):
        _log([name] + args)
        return 0
    return 127
