'''client_folder_children: row CK-TREE1, BackupClient.folder_children (matrix TODO 10.21.4 CLIENT, block TREE-REV13).'''

from __future__ import annotations

from pipeline import rev13cli


def run() -> None:
    '''Raise CheckFailure when the client method is missing, its signature or wire map differs, or it differs from the command.

    Returns:
        None.
    '''
    rev13cli.client_scope('folder_children', 'client_folder_children')
