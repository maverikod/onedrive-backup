'''client_cmd_backup_search_files: rows C-K17 and CK-TREE2, BackupClient.search_files (matrix TODO 10.19.5 and 10.21.4 CLIENT, blocks FILTER-REV11, TREE-REV13).'''

from __future__ import annotations

from pipeline import rev13cli


def run() -> None:
    '''Raise CheckFailure when the method, its 10.21.4 signature or wire map differs, or it differs from the command.

    Returns:
        None.
    '''
    rev13cli.client_scope('search_files', 'client_cmd_backup_search_files')
