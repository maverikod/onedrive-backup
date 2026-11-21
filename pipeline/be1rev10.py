'''Revision 10 additions to the BE1 checks (matrix row BE1, matrix TODO 10.17.6 and 10.17.9 R29), kept beside pipeline.be1.

pipeline.be1 stays unchanged. While be1.run_all runs, three of its parts are wrapped in this process only: the stub rclone answers the
recursive scan (rclone lsjson -R, the scan of 10.17.4 (1)) with Name, Size and ID, every checked run record must carry duplicates []
and an all-zero duplicate_summary (10.17.6), and a library that is not synced must not be scanned either (R29). The new case
mixed_run_with_duplicate_incomplete of pipeline.dupcases3 runs after them.
'''

from __future__ import annotations

import json
from typing import Any
from unittest import mock

from pipeline import be1, dupcases3
from pipeline.report import Report

ZERO = {'groups': 0, 'kept': 0, 'failed': 0, 'stale': 0}
ORIGINAL_RCLONE = be1.Sandbox._rclone
ORIGINAL_RUN_RECORD = be1._run_record
ORIGINAL_UNTOUCHED = be1._untouched


def rclone(self: Any, cmd: list[str]) -> str:
    '''The be1 stub rclone plus the recursive listing of a revision 10 scan (ID is <drive_id>#<item id>, as rclone 1.76.0 prints it).'''
    if 'lsjson' in cmd and ('-R' in cmd or '--recursive' in cmd):
        drive = cmd[cmd.index('--onedrive-drive-id') + 1]
        if drive not in self.remote:
            raise self.ob.BackupError('rclone: unknown drive %s' % drive)
        if '--dirs-only' in cmd:
            return '[]'
        return json.dumps([{'Path': name, 'Name': name.rpartition('/')[2], 'Size': len((drive + ':' + self.remote[drive][name]).encode()),
                            'IsDir': False, 'ID': drive + '#ID-' + name, 'ModTime': '2026-01-01T00:00:00Z'} for name in sorted(self.remote[drive])])
    return str(ORIGINAL_RCLONE(self, cmd))


def no_duplicates(report: Report, label: str, value: Any) -> None:
    '''A library without a collision carries duplicates [] (always present) and an all-zero duplicate_summary (10.17.6).'''
    for row in (value.get('libraries') if isinstance(value, dict) else None) or []:
        if row.get('duplicates') != [] or row.get('duplicate_summary') != ZERO:
            report.product.append('%s: the entry of %s carries duplicates %r and duplicate_summary %r, expected [] and {groups, kept, failed, stale} all 0 (10.17.6)'
                                  % (label, row.get('drive_id'), row.get('duplicates'), row.get('duplicate_summary')))


def run_record(report: Report, label: str, value: Any, error: Any, expected: dict[str, str], status: str | None = None) -> Any:
    '''be1._run_record, then the duplicates fields of every library entry once the run record is observable.'''
    found = ORIGINAL_RUN_RECORD(report, label, value, error, expected, status)
    if found is not None:
        no_duplicates(report, label, value)
    return found


def untouched(report: Report, label: str, box: Any, drive: str, before: dict[str, Any]) -> None:
    '''be1._untouched, then: no recursive scan ran for a library that is neither fetched, synced nor snapshotted (10.17.9 R29).'''
    ORIGINAL_UNTOUCHED(report, label, box, drive, before)
    if [cmd for cmd in box.commands(drive, 'rclone', 'lsjson') if '-R' in cmd or '--recursive' in cmd]:
        report.product.append('%s: a recursive scan (rclone lsjson -R) ran for %s although nothing is scanned, fetched, synced or snapshotted for it (10.17.9 R29)' % (label, drive))


def run_all(report: Report) -> None:
    '''Run the BE1 cases of be1.run_all with the revision 10 assertions, then mixed_run_with_duplicate_incomplete.'''
    with mock.patch.object(be1.Sandbox, '_rclone', rclone), mock.patch.object(be1, '_run_record', run_record), \
            mock.patch.object(be1, '_untouched', untouched):
        be1.run_all(report)
    dupcases3.mixed_run_with_duplicate_incomplete(report)
