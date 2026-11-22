'''odbcli_schedule_set: row OC-SCH2, the odbcli subcommand schedule-set; the pipeline sends a dry run (matrix TODO 10.20.3 CLIENT AND CLI, block SCHEDULE-REV12).'''

from __future__ import annotations

from pipeline import sched12_live


def run() -> None:
    '''Raise CheckFailure when odbcli has no schedule-set or its dry run does not print the revision.

    Returns:
        None.
    '''
    sched12_live.odbcli_check('schedule-set', 'odbcli_schedule_set')
