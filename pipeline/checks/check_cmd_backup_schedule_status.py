'''cmd_backup_schedule_status: every focused case of matrix row M17 (backup_schedule_status) runs against the deployed service (matrix TODO 10.20.3, block SCHEDULE-REV12).'''

from __future__ import annotations

from pipeline import sched12_rows


def run() -> None:
    '''Raise CheckFailure when a case of row M17 is RED.

    Returns:
        None.
    '''
    sched12_rows.run_row('M17', 'cmd_backup_schedule_status')
