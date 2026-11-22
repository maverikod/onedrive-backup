'''schedule_live: SC1, SC10 (two status reads 35 s apart), SC12 and the guarded real write SC6 against the deployed service (matrix TODO 10.20.3, 10.20.7 safety rule, block SCHEDULE-REV12).'''

from __future__ import annotations

from pipeline import sched12_live


def run() -> None:
    '''Raise CheckFailure when the live schedule cases are RED.

    Returns:
        None.
    '''
    sched12_live.schedule_live()
