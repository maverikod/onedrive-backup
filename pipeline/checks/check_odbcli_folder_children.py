'''odbcli_folder_children: row OC-TREE1, the odbcli subcommand folder-children (matrix TODO 10.21.4 ODBCLI, block TREE-REV13).'''

from __future__ import annotations

from pipeline import rev13cli


def run() -> None:
    '''Raise CheckFailure when odbcli has no folder-children, its help or wire map differs, or it does not print the command result.

    Returns:
        None.
    '''
    rev13cli.odbcli_scope('backup_folder_children', 'odbcli_folder_children')
