'''odbcli_schedule_status: row OC-SCH3, the odbcli subcommand schedule-status (matrix TODO 10.20.3 CLIENT AND CLI, block SCHEDULE-REV12).'''

from __future__ import annotations

from pipeline import rev14runcli


def run() -> None:
    '''Raise CheckFailure when odbcli has no schedule-status, it does not print the command result or a non-ok run has no readable reason line.

    Returns:
        None.
    '''
    rev14runcli.odbcli_status('odbcli_schedule_status')
