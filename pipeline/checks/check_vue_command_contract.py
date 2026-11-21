'''vue_command_contract: UI-VUE named check, revision 11 adds the three commands to the live help and the manifest (logic in pipeline.vue11, matrix rows V3, V9).'''

from __future__ import annotations

from pipeline import vue11


def run() -> None:
    '''Raise CheckFailure when the check is RED.

    Returns:
        None.
    '''
    vue11.vue_command_contract()
