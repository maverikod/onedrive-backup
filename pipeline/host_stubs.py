'''Stub commands of the packaging-script fixtures: docker, mountpoint, id and install.

Every call is appended to the JSON-lines file named by STUB_LOG. mountpoint always fails (the host
backup directory is a plain directory, decision D8); id answers the uid and gid in STUB_UID and
STUB_GID for the user onedrive-backup; docker succeeds and reports a running container.
'''

from __future__ import annotations

import json
import os
import sys


def _log(entry: list[str]) -> None:
    with open(os.environ['STUB_LOG'], 'a', encoding='utf-8') as fp:
        fp.write(json.dumps(entry) + chr(10))


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
    if name == 'id':
        if args == ['-u', 'onedrive-backup']:
            print(os.environ['STUB_UID'])
            return 0
        if args == ['-g', 'onedrive-backup']:
            print(os.environ['STUB_GID'])
            return 0
        os.execv('/usr/bin/id', ['id'] + args)
    if name == 'install':
        _log(['install'] + args)
        os.makedirs(args[-1], exist_ok=True)
        return 0
    return 127
