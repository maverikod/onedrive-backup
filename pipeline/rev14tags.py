'''Revision 14 tagging unit check (matrix TODO 10.22.2.5 TAGGING OF NEW SNAPSHOTS, 10.22.9 TD16; row PL20; check unit_backup_tags, block DATES-REV14).

The restic argv of the backup of a library is built INLINE in onedrive_api.sharepoint_backup.sync_library (no separable builder; its only caller is
backup_libraries), so the check goes through the real seam of tests/test_sharepoint_backup.py: mock.patch.object(backup, 'run_command') with a
fake runner that records every argv and answers lsjson like a non-empty remote. TESTER ASSUMPTION (the coder aligns the product): the run id and
the trigger reach sync_library as the KEYWORD arguments run_id and trigger, after dry_run:
sync_library(cfg, site_id, drive_id, target, dry_run=False, run_id='r-1', trigger='schedule'). Cases: td16_tags_builder (run id r-1, trigger
schedule -> the three old tags plus type-full, trigger-scheduled, run-r-1, exact list and order), td16_trigger_manual (trigger cli ->
trigger-manual), td16_trigger_unknown (trigger None -> trigger-unknown) and td16_reader_keys (sharepoint_snapshots fed restic JSON with the new tags
returns the same id, time, site and drive keys as with the old tags; attributes, when the reader returns them, must be full, scheduled, r-1).
'''

from __future__ import annotations

import importlib
import json
import tempfile
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from unittest import mock

from pipeline import fixtures
from pipeline.report import Report

SITE, DRIVE = 'host,1,2', 'drive-A'
SNAPSHOT_ID = 'ab' * 32
WHEN = '2026-11-23T23:41:13.517346781Z'


def _config(root: Path) -> dict[str, Any]:
    '''Build the isolated local backup configuration of tests/test_sharepoint_backup.py.

    Args:
        root: a temporary directory.

    Returns:
        The configuration dict.
    '''
    return {'mirror_dir': root / 'mirror', 'repository_dir': root / 'repo', 'rclone_bin': 'rclone', 'restic_bin': 'restic', 'rclone_config': root / 'rclone.conf',
            'password_file': root / 'password', 'onedrive_remote': 'onedrive:', 'max_delete': 100, 'transfers': 4, 'checkers': 8, 'allow_empty_source': False}


def _tags(backup: Any, trigger: Any, run_id: str) -> list[str]:
    '''Run sync_library over a fake runner and return the --tag values of the restic backup argv.

    Args:
        backup: the module onedrive_api.sharepoint_backup.
        trigger: the trigger passed to sync_library.
        run_id: the run id passed to sync_library.

    Returns:
        The tag values in argv order.
    '''
    calls: list[list[str]] = []

    def fake_run(command: list[str], env: dict[str, str] | None = None, *, capture: bool = False) -> str:
        calls.append([str(value) for value in command])
        if 'lsjson' in command:
            return '[]' if '-R' in command else '[{"Name":"file.txt","IsDir":false}]'
        return ''

    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        with mock.patch.object(backup, 'run_command', side_effect=fake_run):
            backup.sync_library(_config(root), SITE, DRIVE, root / 'mirror' / 'library', dry_run=False, run_id=run_id, trigger=trigger)
    found = [call for call in calls if call[:1] == ['restic'] and 'backup' in call]
    if len(found) != 1:
        raise LookupError('%d restic backup calls seen in %d calls, expected exactly one' % (len(found), len(calls)))
    argv = found[0]
    return [argv[index + 1] for index, value in enumerate(argv) if value == '--tag' and index + 1 < len(argv)]


def _builder_case(report: Report, backup: Any, cid: str, trigger: Any, label: str) -> None:
    '''Judge the tag list of one trigger value.

    Args:
        report: the findings collector.
        backup: the module onedrive_api.sharepoint_backup.
        cid: the case id.
        trigger: the trigger passed to sync_library.
        label: the expected trigger tag value.

    Returns:
        None.
    '''
    wanted = ['sharepoint', 'site-' + backup.stable_key(SITE), 'drive-' + backup.stable_key(DRIVE), 'type-full', 'trigger-' + label, 'run-r-1']
    try:
        got = _tags(backup, trigger, 'r-1')
    except (TypeError, LookupError, OSError, ValueError, backup.BackupError) as exc:
        report.product.append('PL20 %s: sync_library(..., dry_run=False, run_id=%r, trigger=%r) raised %s: %s (tester assumption: keyword arguments run_id and trigger)'
                              % (cid, 'r-1', trigger, type(exc).__name__, exc))
        return
    if got != wanted:
        report.product.append('PL20 %s: the restic backup argv carries the tags %s, expected exactly %s (10.22.2.5 TAGGING OF NEW SNAPSHOTS)' % (cid, got, wanted))


def _listing(tags: list[str]) -> str:
    '''Build the restic snapshots JSON of one snapshot.

    Args:
        tags: the restic tags.

    Returns:
        The JSON text.
    '''
    return json.dumps([{'id': SNAPSHOT_ID, 'time': WHEN, 'tags': tags}])


def _reader_case(report: Report) -> None:
    '''td16_reader_keys: sharepoint_snapshots reads the same keys with the old and with the new tags.

    Args:
        report: the findings collector.

    Returns:
        None.
    '''
    reader = importlib.import_module('onedrive_api.file_index_build').sharepoint_snapshots
    old = ['sharepoint', 'site-' + 'a' * 64, 'drive-' + 'b' * 64]
    new = old + ['type-full', 'trigger-scheduled', 'run-r-1']
    try:
        before = reader(SimpleNamespace(_run=lambda args: _listing(old)))
        after = reader(SimpleNamespace(_run=lambda args: _listing(new)))
    except Exception as exc:  # noqa: BLE001 - any reader failure is a finding
        report.product.append('PL20 td16_reader_keys: sharepoint_snapshots raised %s: %s' % (type(exc).__name__, exc))
        return
    keys = ('id', 'time', 'site_key', 'drive_key')
    if [{key: item.get(key) for key in keys} for item in before] != [{key: item.get(key) for key in keys} for item in after] or len(after) != 1:
        report.product.append('PL20 td16_reader_keys: the reader returns %s for the new tags, expected the keys of the old tags %s' % (after, before))
    attributes = {key: after[0].get(key) for key in ('backup_type', 'trigger', 'run_id') if after and key in after[0]}
    if attributes and attributes != {'backup_type': 'full', 'trigger': 'scheduled', 'run_id': 'r-1'}:
        report.product.append('PL20 td16_reader_keys: the reader returns the attributes %s, expected full, scheduled, r-1' % attributes)


def unit_backup_tags(name: str) -> None:
    '''Run the four TD16 cases and finish the report.

    Args:
        name: the name of the named check.

    Returns:
        None.
    '''
    report = Report()
    fixtures.catalog_module()
    backup = importlib.import_module('onedrive_api.sharepoint_backup')
    cases = (('td16_tags_builder', lambda: _builder_case(report, backup, 'td16_tags_builder', 'schedule', 'scheduled')),
             ('td16_trigger_manual', lambda: _builder_case(report, backup, 'td16_trigger_manual', 'cli', 'manual')),
             ('td16_trigger_unknown', lambda: _builder_case(report, backup, 'td16_trigger_unknown', None, 'unknown')),
             ('td16_reader_keys', lambda: _reader_case(report)))
    for cid, run in cases:
        before = len(report.product)
        run()
        report.info.append('PL20 %s: %s' % (cid, 'GREEN' if len(report.product) == before else 'RED'))
    report.finish(name)
