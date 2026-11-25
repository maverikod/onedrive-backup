'''last_run_diagnosable: every failed run after the deployment has a reason and an available log; older runs predate the fix (matrix TODO 10.23.R.6 TR2, LAGGING and read-only, row M17, block RUN-REASON).'''

from __future__ import annotations

from pipeline import rev14run


def run() -> None:
    '''Raise CheckFailure when a run keeps no reason or log key, or a failed run after the deployment has none.

    Returns:
        None.
    '''
    rev14run.last_run_diagnosable('last_run_diagnosable')
