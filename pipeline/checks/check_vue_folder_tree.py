'''vue_folder_tree: the folder tree of the main page '#/', live Playwright cases L16-L27 and the stub cases (matrix TODO 10.21.6 and 10.21.8, row V12, block UI-TREE).'''

from __future__ import annotations

from pipeline import vue13


def run() -> None:
    '''Raise CheckFailure when the check is RED.

    Returns:
        None.
    '''
    vue13.vue_folder_tree()
