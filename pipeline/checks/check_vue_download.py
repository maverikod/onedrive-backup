'''vue_download: UI-VUE named check, logic in pipeline.vuechecks (matrix rows V1..V6, block UI-VUE)'''

from __future__ import annotations

from pipeline import vuechecks


def run() -> None:
    '''Raise CheckFailure when the check is RED.'''
    vuechecks.vue_download()
