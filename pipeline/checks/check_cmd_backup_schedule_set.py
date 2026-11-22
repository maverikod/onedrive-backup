'''cmd_backup_schedule_set: every focused case of matrix row M16 (backup_schedule_set) runs against the deployed service; no case writes (matrix TODO 10.20.3 and 10.20.7, block SCHEDULE-REV12).'''

from __future__ import annotations

from pipeline import sched12_rows


def run() -> None:
    '''Raise CheckFailure when a case of row M16 is RED.

    Returns:
        None.
    '''
    sched12_rows.run_row('M16', 'cmd_backup_schedule_set')
