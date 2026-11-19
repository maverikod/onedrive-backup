'''Shared pieces of the DATA-ARCHIVE-REV9 checks (matrix block DATA-ARCHIVE-REV9, rows PL1, PL3, PL8-PL12).

The data directory of the service lives on the mounted /srv/archive filesystem (decision D9). The scripts under
test (packaging/docker-run.sh, docker/deploy.sh, packaging/postinst) name that mount point as a built-in constant, so a
fixture cannot create anything under the real /srv/archive. It runs a COPY of the script in which the literal
/srv/archive (and the old /srv/backup, and for the postinst every other absolute host path) is replaced by a path under
a temporary tree, and answers the filesystem questions of the script with a stub findmnt. The stub is driven by the
environment variables FS_MOUNT_ROOT, FS_MOUNTED, FS_TARGET and FS_SOURCE; fs_env() builds them for the five modes below.
Nothing here reads or writes the real host: the stubs that change files refuse every path outside STUB_ROOT.
'''

from __future__ import annotations

import os
import re
from pathlib import Path

MOUNT = '/srv/archive'
OLD_MOUNT = '/srv/backup'
DEFAULT_DATA = MOUNT + '/onedrive-backup'
ROOT_SOURCE = '/dev/root-stub'
ARCHIVE_SOURCE = '/dev/archive-stub'
OTHER_SOURCE = '/dev/other-stub'
MODES = ('ok', 'unmounted', 'root', 'other', 'submount')
DESCRIPTION = {'ok': 'the archive filesystem is mounted and holds the data directory',
               'unmounted': 'the archive mount point is not mounted (the data directory is on the root filesystem)',
               'root': 'the archive is mounted but the data directory is on the root filesystem',
               'other': 'the data directory is on another mounted filesystem',
               'submount': 'the data directory is its own mount below the archive'}
HOST_PREFIXES = ('/var/lib/onedrive-backup', '/etc/onedrive-backup', '/etc/default/onedrive-backup',
                 '/usr/share/onedrive-backup', '/usr/lib/onedrive-backup', '/run/systemd', '/srv/backup',
                 '/srv/archive')


def fs_env(mode: str, mount: Path, data: Path, other: Path) -> dict[str, str]:
    '''Environment that makes the stub findmnt answer as mode says.'''
    if mode not in MODES:
        raise ValueError(mode)
    real = os.path.realpath(data)
    table = {'ok': ('1', str(mount), ARCHIVE_SOURCE), 'unmounted': ('0', '/', ROOT_SOURCE),
             'root': ('1', '/', ROOT_SOURCE), 'other': ('1', str(other), OTHER_SOURCE),
             'submount': ('1', real, ARCHIVE_SOURCE)}
    mounted, target, source = table[mode]
    return {'FS_MOUNT_ROOT': str(mount), 'FS_MOUNTED': mounted, 'FS_TARGET': target, 'FS_SOURCE': source}


def fs_words(mode: str, mount: Path, other: Path) -> list[str]:
    '''Words of the filesystem description a refusal message may carry for mode (target, source device, root filesystem).'''
    if mode == 'other':
        return [str(other), OTHER_SOURCE]
    if mode in ('unmounted', 'root'):
        return ['root filesystem', ROOT_SOURCE]
    return [str(mount), ARCHIVE_SOURCE]


def rewrite(text: str, mapping: dict[str, str]) -> str:
    '''Replace every literal of mapping, longest first.'''
    for old in sorted(mapping, key=len, reverse=True):
        text = text.replace(old, mapping[old])
    return text


def leftovers(text: str) -> list[str]:
    '''Host path prefixes that are still named in text after rewriting.'''
    return [item for item in HOST_PREFIXES if item in text]


def _option_values(args: list[str]) -> tuple[str | None, str | None, list[str]]:
    '''Return (query kind M or T, its path, output columns) of a findmnt command line.'''
    query = path = None
    columns = ['TARGET']
    index = 0
    while index < len(args):
        item = args[index]
        if item.startswith('--'):
            name, eq, value = item.partition('=')
            if name in ('--mountpoint', '--target', '--output'):
                if not eq:
                    index += 1
                    value = args[index] if index < len(args) else ''
                if name == '--output':
                    columns = value.split(',')
                else:
                    query, path = ('M' if name == '--mountpoint' else 'T'), value
        elif item.startswith('-') and len(item) > 1:
            for pos, flag in enumerate(item[1:], 1):
                if flag in 'MTo':
                    value = item[pos + 1:]
                    if not value:
                        index += 1
                        value = args[index] if index < len(args) else ''
                    if flag == 'o':
                        columns = value.split(',')
                    else:
                        query, path = flag, value
                    break
        index += 1
    return query, path, columns


def findmnt(args: list[str], env: dict[str, str]) -> tuple[int, str]:
    '''Answer findmnt -M PATH / findmnt -T PATH with the columns of -o from the environment; returns (exit code, text).'''
    query, path, columns = _option_values(args)
    if query is None or not path:
        return 1, ''
    mounted = env.get('FS_MOUNTED', '1') == '1'
    mount = env.get('FS_MOUNT_ROOT', '')
    if query == 'M':
        if not mounted or os.path.realpath(path) != os.path.realpath(mount):
            return 1, ''
        values = {'TARGET': mount, 'SOURCE': env.get('FS_SOURCE', ARCHIVE_SOURCE)}
    else:
        if not os.path.exists(path):
            return 1, ''
        values = {'TARGET': env.get('FS_TARGET', '/'), 'SOURCE': env.get('FS_SOURCE', ROOT_SOURCE)}
    values['FSTYPE'] = 'ext4'
    return 0, ' '.join(values.get(name.upper(), '') for name in columns) + chr(10)


def refusal_line(err: str, data: str) -> str:
    '''The stderr line that names the resolved data path, or the empty string.'''
    return next((line for line in err.splitlines() if data in line), '')


def message_problems(label: str, err: str, out: str, data: Path, prefix: str, words: list[str],
                     others: set[str]) -> list[str]:
    '''Check the refusal contract of 10.16.2 for one refused run: a stderr line with the script prefix that names the
    resolved data path, the filesystem it is on and states that /srv/archive is not mounted or the directory is not on it;
    different from every pre-existing refusal text; nothing of it on stdout.'''
    problems: list[str] = []
    data_text = str(data)
    if not err.strip():
        return ['%s: nothing on stderr; a refusal must print one line' % label]
    line = refusal_line(err, data_text)
    if not line:
        return ['%s: no stderr line names the resolved data path %s: %r' % (label, data_text, err.strip()[:200])]
    if not line.startswith(prefix):
        problems.append('%s: the refusal line does not start with %r: %r' % (label, prefix, line))
    low = line.lower()
    if 'archive' not in low or not ('not mounted' in low or 'not on' in low):
        problems.append('%s: the refusal line does not state that /srv/archive is not mounted or the directory is not on it: %r'
                        % (label, line))
    if not any(word.lower() in low for word in words):
        problems.append('%s: the refusal line does not name the filesystem of the data directory (one of %s): %r'
                        % (label, words, line))
    if line.strip() in others:
        problems.append('%s: the refusal line is identical to a pre-existing refusal text: %r' % (label, line))
    if data_text in out or re.search('not (mounted|on)', out.lower()):
        problems.append('%s: refusal text on stdout; it belongs on stderr: %r' % (label, out.strip()[:200]))
    return problems
