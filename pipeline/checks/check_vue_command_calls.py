'''vue_command_calls: UI-VUE named check, revision 11 replaces the routes and the nav of 10.18 by the filter page and the service page (logic in pipeline.vue11, rows V4, V9, V10).'''

from __future__ import annotations

from pipeline import vue13


def run() -> None:
    '''Raise CheckFailure when the check is RED (revision 13: '#/' sends the calls of 10.21.6 incl. backup_folder_children, rows V4, V12).

    Returns:
        None.
    '''
    vue13.vue_command_calls()
