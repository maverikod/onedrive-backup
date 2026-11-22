'''vue_build: UI-VUE named check, revision 11 adds the Vitest groups filters, autocomplete, datelabel and service-sections (logic in pipeline.vue11, rows V6, V9).'''

from __future__ import annotations

from pipeline import vue12


def run() -> None:
    '''Raise CheckFailure when the check is RED (revision 12 adds the Vitest groups of the schedule section, rows V6, V11).

    Returns:
        None.
    '''
    vue12.vue_build()
