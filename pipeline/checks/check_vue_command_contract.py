'''vue_command_contract: UI-VUE named check, revision 11 adds the three commands to the live help and the manifest (logic in pipeline.vue11, matrix rows V3, V9).'''

from __future__ import annotations

from pipeline import vue13


def run() -> None:
    '''Raise CheckFailure when the check is RED (revision 13: the manifest lists the 18 commands with backup_folder_children and the new cells, rows V3, V12).

    Returns:
        None.
    '''
    vue13.vue_command_contract()
