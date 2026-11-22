'''schedule_host_timer: the host lists no onedrive-backup.timer after the deploy (matrix TODO 10.20.8 U6 and 10.20.10, block SCHEDULE-REV12); read-only systemctl queries.'''

from __future__ import annotations

from pipeline import sched12_pkg


def run() -> None:
    '''Raise CheckFailure when the host still lists or enables the timer.

    Returns:
        None.
    '''
    sched12_pkg.schedule_host_timer()
