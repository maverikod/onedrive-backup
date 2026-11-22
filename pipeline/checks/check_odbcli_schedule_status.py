'''odbcli_schedule_status: row OC-SCH3, the odbcli subcommand schedule-status (matrix TODO 10.20.3 CLIENT AND CLI, block SCHEDULE-REV12).'''

from __future__ import annotations

from pipeline import sched12_live


def run() -> None:
    '''Raise CheckFailure when odbcli has no schedule-status or it does not print the command result.

    Returns:
        None.
    '''
    sched12_live.odbcli_check('schedule-status', 'odbcli_schedule_status')
