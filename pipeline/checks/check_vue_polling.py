'''vue_polling: UI-VUE named check, revision 11 polls discovery only in the visible service tab and sends nothing after logout (logic in pipeline.vue11, rows V7, V10).'''

from __future__ import annotations

from pipeline import vue11


def run() -> None:
    '''Raise CheckFailure when the check is RED.

    Returns:
        None.
    '''
    vue11.vue_polling()
