'''run_log: every backup run leaves a persistent run log under <data>/schedule/logs and a reason in its runs.jsonl end record (matrix row PL20, cases RL1-RL5, block SCHEDULE-REV12).'''

from __future__ import annotations

from pipeline import runlog13


def run() -> None:
    '''Raise CheckFailure when a refused run leaves no run log, no reason, or the run log directory is missing on the data volume.

    Returns:
        None.
    '''
    runlog13.run_log()
