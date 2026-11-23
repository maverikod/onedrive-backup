'''client_cmd_backup_suggest_names: rows C-K18 and CK-TREE3, BackupClient.suggest_names (matrix TODO 10.19.5 and 10.21.4 CLIENT, blocks FILTER-REV11, TREE-REV13).'''

from __future__ import annotations

from pipeline import rev13cli


def run() -> None:
    '''Raise CheckFailure when the method, its 10.21.4 signature or wire map differs, or it differs from the command.

    Returns:
        None.
    '''
    rev13cli.client_scope('suggest_names', 'client_cmd_backup_suggest_names')
