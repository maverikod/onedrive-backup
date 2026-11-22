'''vue_static_serve: UI-VUE named check, revision 11 adds the nav of the single filter page (logic in pipeline.vue11 over pipeline.vuechecks, matrix rows V1, V9).'''

from __future__ import annotations

from pipeline import vue12


def run() -> None:
    '''Raise CheckFailure when the check is RED (revision 12: the service page carries the tab svc-tab-schedule, rows V1, V11).

    Returns:
        None.
    '''
    vue12.vue_static_serve()
