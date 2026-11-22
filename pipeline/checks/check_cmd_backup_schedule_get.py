'''cmd_backup_schedule_get: every focused case of matrix row M15 (backup_schedule_get) runs against the deployed service (matrix TODO 10.20.3, block SCHEDULE-REV12).'''

from __future__ import annotations

from pipeline import sched12_rows


def run() -> None:
    '''Raise CheckFailure when a case of row M15 is RED.

    Returns:
        None.
    '''
    sched12_rows.run_row('M15', 'cmd_backup_schedule_get')
