'''cmd_backup_schedule_status: every focused case of matrix row M17 (backup_schedule_status) runs against the deployed service (matrix TODO 10.20.3, block SCHEDULE-REV12).'''

from __future__ import annotations

from pipeline import rev14run


def run() -> None:
    '''Raise CheckFailure when a case of row M17 is RED (revision 12 cases and the revision 14 keys reason, log, retried).

    Returns:
        None.
    '''
    rev14run.status_row('cmd_backup_schedule_status')
