'''vue_schedule: the schedule section of the service page, live Playwright cases L10-L15 (matrix TODO 10.20.7, row V11, block SCHEDULE-REV12).'''

from __future__ import annotations

from pipeline import vue12


def run() -> None:
    '''Raise CheckFailure when the check is RED.

    Returns:
        None.
    '''
    vue12.vue_schedule()
