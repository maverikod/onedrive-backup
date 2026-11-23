'''cmd_backup_folder_children: every focused case of matrix row M19 (backup_folder_children) runs against the deployed service (matrix TODO 10.21.7 TC1-TC6, TC12, TC15, TC16; block TREE-REV13).'''

from __future__ import annotations

from pipeline import rev13, rev13tree


def run() -> None:
    '''Raise CheckFailure when a case of row M19 is RED.

    Returns:
        None.
    '''
    rev13.run_row('M19', 'cmd_backup_folder_children', rev13tree.VALIDATORS)
