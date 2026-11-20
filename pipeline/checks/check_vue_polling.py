'''vue_polling: UI-VUE named check, logic in pipeline.vuechecks (matrix row V7, blocks UI-VUE and UI-ROUTES)'''

from __future__ import annotations

from pipeline import vuechecks


def run() -> None:
    '''Raise CheckFailure when the check is RED.'''
    vuechecks.vue_polling()
