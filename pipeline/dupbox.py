'''Sandbox of the DUP-KEEP-REV10 stub checks (matrix block DUP-KEEP-REV10, rows BE1-BE3, matrix TODO 10.17).

The REAL backup code path runs (onedrive_api.sharepoint_backup.backup_libraries over a configuration loaded by the real
load_config), exactly as in pipeline.be1, which this module extends. Only the process and network boundaries are replaced, in
this process and for the duration of one call:
  - run_command of onedrive_backup and of every onedrive_api module that holds it: the stub rclone answers lsjson (listing
    with Path, Name, Size, ID, Hashes.quickxor in the form of rclone 1.76.0 observed by probe P1: ID is <drive_id>#<item id>,
    the hash is 40 lowercase hex digits), sync (the stub keeps the first of every name group, as rclone does, and honours the
    exclude patterns that protect files from deletion) and hashsum quickxor; every other rclone verb is refused and recorded
    as a write to the source; the stub restic records its arguments;
  - urllib.request.urlopen (and every onedrive_api module that imported it): the stub Graph answers the token request and
    GET /v1.0/drives/<drive_id>/items/<item id>/content; every other request is refused and recorded;
  - time.sleep (no waiting), subprocess.run and subprocess.Popen (refused).
Nothing of the host, the network or the real SharePoint is reached. The quickXorHash is the real algorithm (160 bit register,
11 bit shift per byte, the length xored into the last 8 bytes).
'''

from __future__ import annotations

import base64
import fnmatch
import hashlib
import io
import json
import logging
import re
import sys
import time
import unicodedata
import urllib.error
import urllib.request
from dataclasses import dataclass
from email.message import Message
from pathlib import Path
from typing import Any
from unittest import mock
from urllib.parse import unquote, urlsplit

from pipeline import be1

CONF = ('[onedrive]\ntype = onedrive\nclient_credentials = true\ntenant = 11111111-1111-1111-1111-111111111111\n'
        'client_id = 22222222-2222-2222-2222-222222222222\nclient_secret = stub-secret\n')
CONTENT_URL = re.compile(r'https://graph[.]microsoft[.]com/v1[.]0/drives/([^/]+)/items/([^/]+)/content')
VERBS = ('lsjson', 'sync', 'hashsum', 'dedupe', 'delete', 'deletefile', 'purge', 'move', 'moveto', 'copy', 'copyto', 'mkdir',
         'rmdir', 'rmdirs', 'cleanup', 'touch', 'rcat', 'check', 'cat', 'ls', 'lsd', 'lsl', 'size', 'tree', 'link', 'version')
READ_VERBS = ('lsjson', 'sync', 'hashsum')
MODTIME = '2026-01-01T00:00:00Z'


def quickxor(data: bytes) -> bytes:
    '''Return the 20 byte QuickXorHash of data, the file hash of OneDrive and SharePoint.'''
    mask = (1 << 160) - 1
    register = 0
    for index, value in enumerate(data):
        shifted = value << ((index * 11) % 160)
        register ^= (shifted | (shifted >> 160)) & mask
    register ^= (len(data) << 96) & mask
    return register.to_bytes(20, 'little')


def key(name: str) -> str:
    '''The name key of 10.17.2: NFC normalisation, then case folding.'''
    return unicodedata.normalize('NFC', name).casefold()


def suffix(item_id: str, digits: int = 8) -> str:
    '''The first digits lowercase hex digits of sha256(item id as UTF-8).'''
    return hashlib.sha256(item_id.encode('utf-8')).hexdigest()[:digits]


def stored_name(path: str, item_id: str, digits: int = 8) -> str:
    '''The mirror-relative stored_as of an extra: <stem>.dup-<h><ext> in the folder of its plain path (10.17.3).'''
    folder, _, name = path.rpartition('/')
    stem, dot, ext = name.rpartition('.')
    if not dot:
        stem, ext = name, ''
    return (folder + '/' if folder else '') + '%s.dup-%s%s' % (stem, suffix(item_id, digits), dot + ext if dot else '')


@dataclass
class Item:
    '''One SharePoint file: its mirror-relative path, Graph item id and bytes; fetch picks the answer of the Graph content endpoint.'''

    path: str
    item: str
    content: bytes
    hashed: bool = True
    fetch: str = 'ok'


class Reply:
    '''The minimal HTTP response object a urlopen stand-in returns.'''

    def __init__(self, body: bytes, length: int | None = None) -> None:
        self._io = io.BytesIO(body)
        self.status = 200
        self.headers = {'Content-Length': str(len(body) if length is None else length), 'Content-Type': 'application/octet-stream'}

    def read(self, size: int = -1) -> bytes:
        return self._io.read(size)

    def __enter__(self) -> 'Reply':
        return self

    def __exit__(self, *args: Any) -> None:
        return None


def patterns_of(cmd: list[str]) -> list[str]:
    '''The exclude globs of an rclone command line: --exclude, --filter '- x', --exclude-from and --filter-from files.'''
    found: list[str] = []
    for number, word in enumerate(cmd):
        value = word.split('=', 1)[1] if '=' in word else (cmd[number + 1] if number + 1 < len(cmd) else '')
        flag = word.split('=', 1)[0]
        if flag == '--exclude':
            found.append(value)
        elif flag == '--filter' and value.startswith('- '):
            found.append(value[2:])
        elif flag in ('--exclude-from', '--filter-from') and Path(value).is_file():
            for line in Path(value).read_text(encoding='utf-8').splitlines():
                line = line.strip()
                if flag == '--exclude-from' and line and not line.startswith('#'):
                    found.append(line)
                elif flag == '--filter-from' and line.startswith('- '):
                    found.append(line[2:])
    return found


def excluded(path: str, patterns: list[str]) -> bool:
    '''True when an rclone exclude glob matches the path (a pattern without a slash matches the base name).'''
    name = path.rpartition('/')[2]
    return any(fnmatch.fnmatchcase(path if '/' in pattern else name, pattern.lstrip('/')) for pattern in patterns)


class DupBox(be1.Sandbox):
    '''A be1 sandbox whose fake SharePoint holds Items with ids and hashes and whose Graph content endpoint is stubbed.'''

    def __init__(self) -> None:
        super().__init__()
        (self.tmp / 'rclone.conf').write_text(CONF, encoding='utf-8')
        (self.tmp / 'rclone.conf').chmod(0o600)
        self.items: dict[str, list[Item]] = {}
        self.dirs: dict[str, list[str]] = {}
        self.events: list[tuple[str, ...]] = []
        self.graph: list[dict[str, Any]] = []
        self.attempts: dict[str, int] = {}
        self.writes: list[str] = []
        self.scan_fails = False

    def drive(self, drive: str, *items: Item) -> None:
        '''Declare a library and its files in the order the remote lists them.'''
        self.items[drive] = list(items)

    def listing(self, drive: str, files_only: bool, dirs_only: bool = False) -> list[dict[str, Any]]:
        '''The lsjson answer: files with their hash and the directories, narrowed by --files-only and --dirs-only.'''
        rows: list[dict[str, Any]] = []
        for item in ([] if dirs_only else self.items[drive]):
            row: dict[str, Any] = {'Path': item.path, 'Name': item.path.rpartition('/')[2], 'Size': len(item.content), 'IsDir': False,
                                   'ID': drive + '#' + item.item, 'ModTime': MODTIME}
            if item.hashed:
                row['Hashes'] = {'quickxor': quickxor(item.content).hex()}
            rows.append(row)
        if not files_only:
            rows += [{'Path': path, 'Name': path.rpartition('/')[2], 'Size': -1, 'IsDir': True, 'ID': '%s#DIR%d' % (drive, number),
                      'ModTime': MODTIME} for number, path in enumerate(self.dirs.get(drive, []))]
        return rows

    def _sync(self, drive: str, cmd: list[str]) -> str:
        position = cmd.index('sync')
        if cmd[position + 1] != 'onedrive:':
            raise be1.Refused('rclone sync source is not the remote: %r' % cmd[position + 1])
        target = Path(cmd[position + 2])
        limit = int(cmd[cmd.index('--max-delete') + 1])
        patterns = patterns_of(cmd)
        wanted: dict[str, bytes] = {}
        seen: set[tuple[str, str]] = set()
        for item in self.items[drive]:
            folder, _, name = item.path.rpartition('/')
            if (folder, key(name)) in seen:
                continue
            seen.add((folder, key(name)))
            if not excluded(item.path, patterns):
                wanted[item.path] = item.content
        stale = [name for name in self.tree(target) if name not in wanted and not excluded(name, patterns)]
        if len(stale) > limit:
            raise self.ob.BackupError('rclone: --max-delete %d exceeded by %d deletions' % (limit, len(stale)))
        if '--dry-run' in cmd:
            return ''
        for name in stale:
            (target / name).unlink()
        for name, content in wanted.items():
            (target / name).parent.mkdir(parents=True, exist_ok=True)
            (target / name).write_bytes(content)
        return ''

    def _hashsum(self, cmd: list[str]) -> str:
        words = cmd[cmd.index('hashsum') + 1:]
        if not words or not words[0].lower().startswith('quickxor'):
            raise be1.Refused('rclone hashsum outside quickxor: %r' % words[:2])
        target = Path(words[-1])
        base64_form = '--base64' in cmd
        files = {target.name: target} if target.is_file() else {str(p.relative_to(target)): p for p in sorted(target.rglob('*')) if p.is_file()}
        lines = []
        for name, path in files.items():
            digest = quickxor(path.read_bytes())
            lines.append('%s  %s' % (base64.b64encode(digest).decode() if base64_form else digest.hex(), name))
        return '\n'.join(lines) + ('\n' if lines else '')

    def _rclone(self, cmd: list[str]) -> str:
        verb = next((word for word in cmd[1:] if word in VERBS), '')
        if verb not in READ_VERBS:
            self.writes.append(verb or '?')
            raise be1.Refused('rclone verb outside lsjson, sync and hashsum: %r' % cmd[:6])
        if verb == 'hashsum':
            return self._hashsum(cmd)
        drive = cmd[cmd.index('--onedrive-drive-id') + 1] if '--onedrive-drive-id' in cmd else ''
        if drive not in self.items:
            raise self.ob.BackupError('rclone: unknown drive %s' % drive)
        if verb == 'sync':
            return self._sync(drive, cmd)
        if '-R' not in cmd and '--recursive' not in cmd:
            return json.dumps([{'Path': name, 'IsDir': False} for name in sorted({item.path.split('/')[0] for item in self.items[drive]})])
        if self.scan_fails:
            raise self.ob.BackupError('rclone lsjson exited 1')
        return json.dumps(self.listing(drive, '--files-only' in cmd, '--dirs-only' in cmd))

    def fake(self, cmd: Any, env: Any = None, *, capture: bool = False) -> str:
        '''The stand-in of run_command: the be1 restic stub plus the DUP rclone stub; the event log orders rclone, restic and Graph.'''
        words = [str(item) for item in cmd]
        verb = next((word for word in words[1:] if word in VERBS + ('backup',)), '')
        self.events.append((Path(words[0]).name, verb))
        return super().fake(words, env, capture=capture)

    def urlopen(self, request: Any, *args: Any, **kwargs: Any) -> Reply:
        '''The stand-in of urlopen: the token POST and GET .../items/<id>/content; anything else is refused and recorded.'''
        url, method = request.full_url, request.get_method()
        self.graph.append({'method': method, 'url': url, 'auth': bool(request.get_header('Authorization')), 'host': urlsplit(url).hostname})
        self.events.append(('graph', method, url))
        if method == 'POST' and urlsplit(url).hostname == 'login.microsoftonline.com':
            return Reply(json.dumps({'access_token': 'stub-token', 'expires_in': 3600}).encode())
        found = CONTENT_URL.fullmatch(url)
        if method != 'GET' or not found:
            raise urllib.error.URLError('refused by the DUP sandbox: %s %s' % (method, url))
        drive, ident = unquote(found.group(1)), unquote(found.group(2))
        item = next((one for one in self.items.get(drive, []) if one.item == ident), None)
        if item is None:
            raise urllib.error.HTTPError(url, 404, 'not found', Message(), None)
        self.attempts[ident] = self.attempts.get(ident, 0) + 1
        if item.fetch == 'fail':
            raise urllib.error.HTTPError(url, 503, 'unavailable', Message(), None)
        if item.fetch == 'mismatch':
            return Reply(bytes((byte + 1) % 256 for byte in item.content))
        if item.fetch == 'short':
            return Reply(item.content[:-1], len(item.content))
        return Reply(item.content)

    def _modules(self, attribute: str, original: Any = None) -> list[Any]:
        found = []
        for name, module in list(sys.modules.items()):
            if module is not None and (name == 'onedrive_backup' or name.startswith('onedrive_api')) and hasattr(module, attribute):
                if original is None or getattr(module, attribute) is original:
                    found.append(module)
        return found

    def run(self, drives: list[str], *, dry_run: bool = False) -> tuple[Any, Exception | None, list[logging.LogRecord]]:
        '''Run backup_libraries; return (value, exception, log records of WARNING and above).'''
        report = {'sites': [{'site_id': be1.SITE, 'display_name': 'stub', 'source_status': 'ok'}],
                  'libraries': [{'site_id': be1.SITE, 'drive_id': drive, 'status': 'ok'} for drive in drives],
                  'complete': True, 'errors': []}
        records: list[logging.LogRecord] = []
        handler = logging.Handler(0)
        handler.emit = records.append  # type: ignore[method-assign,assignment]
        log = logging.getLogger('onedrive_backup')
        log.addHandler(handler)
        original = urllib.request.urlopen
        patches: list[Any] = [mock.patch.object(module, 'run_command', self.fake) for module in self._modules('run_command')]
        patches += [mock.patch.object(module, 'urlopen', self.urlopen) for module in self._modules('urlopen', original)]
        patches += [mock.patch.object(urllib.request, 'urlopen', self.urlopen), mock.patch.object(time, 'sleep', lambda seconds: None),
                    mock.patch.object(self.ob.subprocess, 'run', be1._refuse), mock.patch.object(self.ob.subprocess, 'Popen', be1._refuse)]
        value, error = None, None
        try:
            for item in patches:
                item.start()
            try:
                value = self.sb.backup_libraries(self.cfg, report, dry_run=dry_run)
            finally:
                for item in patches:
                    item.stop()
        except Exception as exc:
            error = exc
        finally:
            log.removeHandler(handler)
        return value, error, [item for item in records if item.levelno >= logging.WARNING]

    def requests_for(self, item_id: str) -> list[dict[str, Any]]:
        '''The recorded Graph content requests of one item.'''
        return [row for row in self.graph if row['method'] == 'GET' and unquote(row['url']).split('/items/')[-1].startswith(item_id + '/')]

    def stored(self, drive: str, relative: str) -> bytes | None:
        '''The bytes of a mirror file of the library, or None when it does not exist.'''
        path = self.mirror(drive) / relative
        return path.read_bytes() if path.is_file() else None

    def restic_backups(self, drive: str) -> list[list[str]]:
        '''The restic backup commands of one library.'''
        return self.commands(drive, 'restic', 'backup')

    def sync_commands(self, drive: str) -> list[list[str]]:
        '''The rclone sync commands of one library.'''
        return self.commands(drive, 'rclone', 'sync')


def entry_of(value: Any, drive: str) -> dict[str, Any] | None:
    '''The run record entry of one library, or None when the run record has none.'''
    rows = value.get('libraries') if isinstance(value, dict) else None
    return next((row for row in rows if isinstance(row, dict) and row.get('drive_id') == drive), None) if isinstance(rows, list) else None


def extras_of(entry: dict[str, Any] | None) -> list[dict[str, Any]] | None:
    '''The duplicates list of a library entry, or None when the entry has no list.'''
    found = entry.get('duplicates') if isinstance(entry, dict) else None
    return found if isinstance(found, list) and all(isinstance(row, dict) for row in found) else None


def b64(content: bytes) -> str:
    '''The base64 quickXorHash of a content, the form of the record field quickxor.'''
    return base64.b64encode(quickxor(content)).decode()
