'''timer_retired: the package retires the systemd timer and creates the schedule file (matrix TODO 10.20.8 PL15 PK1-PK6, replaces timer_state_preserved, block SCHEDULE-REV12).'''

from __future__ import annotations

from pipeline import sched12_pkg


def run() -> None:
    '''Raise CheckFailure when the maintainer scripts or the payload keep the timer or skip the schedule file.

    Returns:
        None.
    '''
    sched12_pkg.timer_retired()
