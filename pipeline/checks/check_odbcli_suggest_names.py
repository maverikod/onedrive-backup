'''odbcli_suggest_names: row O19, the odbcli subcommand suggest-names (matrix TODO 10.19.5 CLIENT AND CLI, block FILTER-REV11).'''

from __future__ import annotations

from pipeline import rev11


def run() -> None:
    '''Raise CheckFailure when odbcli has no suggest-names or it does not print the command result.

    Returns:
        None.
    '''
    rev11.odbcli_check('suggest-names', ['--text', 'акт'], 'backup_suggest_names', 'odbcli_suggest_names')
