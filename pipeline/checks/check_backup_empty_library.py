'''backup_empty_library: row BE1, the backup cycle per library with empty SharePoint libraries (matrix TODO 10.14, 10.14.1).

Mode: stub-isolated over the REAL onedrive_api.sharepoint_backup.backup_libraries (pipeline.be1): a temporary data directory,
fake rclone and restic in this process, no network, no production state, no real backup. Cases: empty_new_library_skipped,
emptied_library_not_synced_error, mixed_run_continues, plus a control that proves the sandbox with a library that has files.
User decision 2026-11-19: a never backed up empty library is skipped (status empty) and the run continues; an emptied library
with snapshots is not synced and an error is recorded; the checked-at timestamp is optional and is not asserted.
'''

from __future__ import annotations

from pipeline import be1
from pipeline.report import Report


def run() -> None:
    '''Raise CheckFailure when the backup cycle does not meet the BE1 contract.'''
    report = Report()
    be1.run_all(report)
    report.finish('backup_empty_library')
