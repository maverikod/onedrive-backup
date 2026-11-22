'''vue_command_calls: UI-VUE named check, revision 11 replaces the routes and the nav of 10.18 by the filter page and the service page (logic in pipeline.vue11, rows V4, V9, V10).'''

from __future__ import annotations

from pipeline import vue12


def run() -> None:
    '''Raise CheckFailure when the check is RED (revision 12: the schedule route sends exactly get and status, rows V4, V11).

    Returns:
        None.
    '''
    vue12.vue_command_calls()
