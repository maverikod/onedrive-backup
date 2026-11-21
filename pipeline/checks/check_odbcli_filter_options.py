'''odbcli_filter_options: row O17, the odbcli subcommand filter-options (matrix TODO 10.19.5 CLIENT AND CLI, block FILTER-REV11).'''

from __future__ import annotations

from pipeline import rev11


def run() -> None:
    '''Raise CheckFailure when odbcli has no filter-options or it does not print the command result.

    Returns:
        None.
    '''
    rev11.odbcli_check('filter-options', [], 'backup_filter_options', 'odbcli_filter_options')
