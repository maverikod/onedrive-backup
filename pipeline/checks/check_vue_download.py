'''vue_download: UI-VUE named check, revision 11 downloads a row of the filter page through the inline export panel (logic in pipeline.vue11, rows V5, V9).'''

from __future__ import annotations

from pipeline import vue11


def run() -> None:
    '''Raise CheckFailure when the check is RED.

    Returns:
        None.
    '''
    vue11.vue_download()
