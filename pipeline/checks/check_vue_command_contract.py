'''vue_command_contract: UI-VUE named check, revision 11 adds the three commands to the live help and the manifest (logic in pipeline.vue11, matrix rows V3, V9).'''

from __future__ import annotations

from pipeline import vue12


def run() -> None:
    '''Raise CheckFailure when the check is RED (revision 12: the live help lists 17 commands and the manifest the three schedule commands, rows V3, V11).

    Returns:
        None.
    '''
    vue12.vue_command_contract()
