'''vue_polling: UI-VUE named check, revision 11 polls discovery only in the visible service tab and sends nothing after logout (logic in pipeline.vue11, rows V7, V10).'''

from __future__ import annotations

from pipeline import vue12


def run() -> None:
    '''Raise CheckFailure when the check is RED (revision 12: the schedule status poll lives only in the visible section, rows V7, V11).

    Returns:
        None.
    '''
    vue12.vue_polling()
