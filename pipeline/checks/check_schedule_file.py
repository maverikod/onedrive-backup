'''schedule_file: the schedule parser and store on a fixture directory (matrix TODO 10.20.2, 10.20.3 SC4, SC5, 10.20.6 PL16 ST1-ST9, block SCHEDULE-REV12).'''

from __future__ import annotations

from pipeline import sched12_file


def run() -> None:
    '''Raise CheckFailure when the parser or the store differs from the contract.

    Returns:
        None.
    '''
    sched12_file.run()
