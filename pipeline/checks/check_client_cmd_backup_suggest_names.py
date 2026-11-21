'''client_cmd_backup_suggest_names: row C-K18, BackupClient.suggest_names (matrix TODO 10.19.5 CLIENT AND CLI, block FILTER-REV11).'''

from __future__ import annotations

from pipeline import rev11


def run() -> None:
    '''Raise CheckFailure when the client method is missing or differs from the command.

    Returns:
        None.
    '''
    rev11.client_check('backup_suggest_names', 'suggest_names', 'client_cmd_backup_suggest_names')
