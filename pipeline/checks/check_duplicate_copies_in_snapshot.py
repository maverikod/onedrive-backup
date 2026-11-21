'''duplicate_copies_in_snapshot: row BE4, both objects of every probed collision group are in the latest sharepoint snapshot of library 1.

Mode: live, against the deployed service, through backup_snapshots, backup_list_files, backup_prepare_download and backup_delete_export
(matrix TODO 10.17.8 BE4 and 10.17.11 (4)). Precondition for GREEN: a backup run on the version that implements revision 10 has finished.
Cases per collision group of probe P1 (pipeline/probe_p1.json): both_objects_listed (the latest snapshot of library 1 lists the plain name
and the stored copy <stem>.dup-<h8><ext> of the group folder, h from the Graph item id of the extra), prepare_download_of_copy
(prepare with the suffixed file_path succeeds; the project client fetch of the export verifies size and SHA256 and the size equals the
listed size; the export is deleted), plain_name_unchanged (the plain name and its size equal the entry the 0.3.20 snapshot held).
Findings: PRODUCT when the snapshot lacks a copy or a case fails, STATE when the inventory, a snapshot or the probe data are not usable.
'''

from __future__ import annotations

import hashlib
import importlib
import re
import tempfile
from pathlib import Path
from typing import Any

from pipeline import b4client, dupprobe, fixtures, live
from pipeline.dupbox import key, suffix
from pipeline.report import Report


def _stable_key(value: str) -> str:
    '''The tag and path component of a site or drive id: the product stable_key (sha256 hex).'''
    fixtures.catalog_module()
    return str(importlib.import_module('onedrive_api.sharepoint_backup').stable_key(value))


def _latest(report: Report, tag: str) -> str | None:
    kind, code, message, data = live.request('backup_snapshots', {'limit': 1000})
    if kind != 'success' or not isinstance(data, dict) or not isinstance(data.get('items'), list):
        report.state.append('backup_snapshots cannot be read: %s %s %s' % (kind, code, message))
        return None
    mine = [item for item in data['items'] if isinstance(item, dict) and tag in item.get('tags', []) and 'sharepoint' in item.get('tags', [])]
    if not mine:
        report.state.append('no sharepoint snapshot of library 1 (tag %s) exists' % tag)
        return None
    return str(max(mine, key=lambda item: str(item.get('time')))['id'])


def _folder_files(report: Report, snapshot: str, prefix: str) -> list[dict[str, Any]] | None:
    found: list[dict[str, Any]] = []
    while True:
        kind, code, message, data = live.request('backup_list_files', {'snapshot_id': snapshot, 'prefix': prefix, 'limit': 5000, 'offset': len(found)})
        if kind != 'success' or not isinstance(data, dict) or not isinstance(data.get('items'), list):
            report.state.append('backup_list_files(%s, %s) failed: %s %s %s' % (snapshot[:12], prefix[-40:], kind, code, message))
            return None
        found += [item for item in data['items'] if isinstance(item, dict) and item.get('type') == 'file']
        if not data['items'] or len(found) >= int(data.get('total') or 0):
            return found


def _prepare_and_fetch(report: Report, snapshot: str, path: str, size: int) -> None:
    label = 'BE4 prepare_download_of_copy'
    kind, code, message, meta = live.request('backup_prepare_download', {'snapshot_id': snapshot, 'file_path': path})
    if kind != 'success' or not isinstance(meta, dict) or 'export_id' not in meta:
        report.product.append('%s: backup_prepare_download(%s) answered %s %s %s' % (label, path.rpartition('/')[2], kind, code, message))
        return
    export = str(meta['export_id'])
    try:
        if meta.get('filename') != path.rpartition('/')[2] or meta.get('size_bytes') != size:
            report.product.append('%s: the export is %r (%r bytes), expected the file %s of %d bytes' % (label, meta.get('filename'), meta.get('size_bytes'), path.rpartition('/')[2], size))
        module = b4client.load_client(report)
        client = b4client.make_client(module, report) if module else None
        if client is None:
            return
        with tempfile.TemporaryDirectory() as work:
            out = Path(work) / 'copy.bin'
            _, failure = b4client.drive(client.fetch, export, str(out))
            data = out.read_bytes() if out.exists() else b''
            if failure is not None or len(data) != size or hashlib.sha256(data).hexdigest() != meta.get('sha256'):
                report.product.append('%s: fetch of the export gave %s, %d bytes (listed %d), sha256 %s (export %s)' % (label, failure or 'ok', len(data), size, hashlib.sha256(data).hexdigest()[:12], str(meta.get('sha256'))[:12]))
    finally:
        kind, code, message, _ = live.request('backup_delete_export', {'export_id': export})
        if kind != 'success':
            report.product.append('%s: the export %s could not be deleted: %s %s %s' % (label, export, kind, code, message))


def _copy_name(member: dict[str, Any]) -> re.Pattern[str]:
    '''The stored copy name of a member as an extra: <stem>.dup-<h8 or longer><ext>, h from the sha256 of its Graph item id (10.17.3).'''
    stem, dot, ext = member['name'].rpartition('.')
    return re.compile(re.escape(stem) + r'[.]dup-' + suffix(member['item_id']) + r'[0-9a-f]*' + re.escape(dot + ext))


def _group_cases(report: Report, listed: list[dict[str, Any]], group: dict[str, Any], plain_record: dict[str, int], snapshot: str) -> None:
    '''both_objects_listed, prepare_download_of_copy and plain_name_unchanged for one probed collision group.'''
    members = group['members']
    names = {str(item['path']).rpartition('/')[2]: item for item in listed}
    plain = [name for name in names if name in [member['name'] for member in members]]
    copies = [name for name in names if any(_copy_name(member).fullmatch(name) for member in members)]
    label = 'BE4 both_objects_listed %s' % ascii(members[0]['name'])
    if len(plain) == 1 and len(copies) == 1 and any(_copy_name(member).fullmatch(copies[0]) for member in members if member['name'] != plain[0]):
        _prepare_and_fetch(report, snapshot, str(names[copies[0]]['path']), int(names[copies[0]]['size']))
    else:
        report.product.append('%s: the snapshot %s lists the plain name(s) %s and the stored copy name(s) %s for the group; expected one plain name and one copy %s of the other member'
                              % (label, snapshot[:12], ascii(plain), ascii(copies), ascii([_copy_name(member).pattern for member in members])))
    for name, size in plain_record.items():
        if key(name) == key(members[0]['name']) and (name not in names or names[name].get('size') != size):
            report.product.append('BE4 plain_name_unchanged %s: the plain entry %s of %d bytes held by the 0.3.20 snapshot is not listed with that name and size (listed %s)'
                                  % (ascii(members[0]['name']), ascii(name), size, ascii({n: names[n].get('size') for n in plain})))


def run() -> None:
    '''Raise CheckFailure when a probed collision group is not kept as two files in the latest sharepoint snapshot of library 1.'''
    report = Report()
    try:
        data = dupprobe.load()
        library = data['library']
        tag = 'drive-' + _stable_key(library['drive_id'])
        snapshot = _latest(report, tag)
        prefix = 'sharepoint/%s/%s/%s' % (_stable_key(library['site_id']), _stable_key(library['drive_id']), data['folder'])
        listed = _folder_files(report, snapshot, prefix) if snapshot else None
        if listed is not None and snapshot:
            plain_record = {item['name']: int(item['size']) for item in data['snapshot_0_3_20']['plain']}
            report.info.append('latest sharepoint snapshot of library 1: %s, %d files in the probed folder' % (snapshot, len(listed)))
            for group in data['groups']:
                _group_cases(report, listed, group, plain_record, snapshot)
    except live.LiveUnreachable as exc:
        report.env.append('the service cannot be used: %s' % exc)
    except (OSError, ValueError, KeyError, ImportError) as exc:
        report.env.append('the probe data or the product module cannot be used: %s: %s' % (type(exc).__name__, exc))
    report.finish('duplicate_copies_in_snapshot')
