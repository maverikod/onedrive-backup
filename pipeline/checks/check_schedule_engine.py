'''schedule_engine: decide(), the slot rules and the scheduler core with a fake clock and runner (matrix TODO 10.20.5, 10.20.6 PL17 EN1-EN20, block SCHEDULE-REV12).'''

from __future__ import annotations

from pipeline import sched12_engine


def run() -> None:
    '''Raise CheckFailure when the engine differs from the contract.

    Returns:
        None.
    '''
    sched12_engine.run()
