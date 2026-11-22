'''run_records: backup_run writes a start and an end record for every start (matrix TODO 10.20.5 RUN RECORDS, 10.20.6 PL18 RR1-RR5, block SCHEDULE-REV12).'''

from __future__ import annotations

from pipeline import sched12_pkg


def run() -> None:
    '''Raise CheckFailure when the run records differ from the contract.

    Returns:
        None.
    '''
    sched12_pkg.run_records()
