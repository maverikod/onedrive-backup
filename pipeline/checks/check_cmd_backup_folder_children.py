'''cmd_backup_folder_children: every focused case of matrix row M19 (backup_folder_children) runs against the deployed service (matrix TODO 10.21.7 TC1-TC6, TC12, TC15, TC16 and 10.22.9 TD3, TD11; blocks TREE-REV13, DATES-REV14).'''

from __future__ import annotations

from pipeline import rev13tree, rev14, rev14dates2


def run() -> None:
    '''Raise CheckFailure when a case of row M19 is RED.

    Returns:
        None.
    '''
    rev14.run_row('M19', 'cmd_backup_folder_children', rev14dates2.TREE_VALIDATORS, rev14dates2.TREE_ERRORS, old=rev13tree.VALIDATORS)
