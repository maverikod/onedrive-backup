'''vue_auth: UI-VUE named check, revision 11 adds the nav ids (logic in pipeline.vue11 over pipeline.vuechecks, matrix rows V2, V9).'''

from __future__ import annotations

from pipeline import vue11


def run() -> None:
    '''Raise CheckFailure when the check is RED.

    Returns:
        None.
    '''
    vue11.vue_auth()
