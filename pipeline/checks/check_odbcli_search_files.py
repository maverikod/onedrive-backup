'''odbcli_search_files: row O18, the odbcli subcommand search-files (matrix TODO 10.19.5 CLIENT AND CLI, block FILTER-REV11).'''

from __future__ import annotations

from pipeline import rev11


def run() -> None:
    '''Raise CheckFailure when odbcli has no search-files or it does not print the command result.

    Returns:
        None.
    '''
    rev11.odbcli_check('search-files', ['--name-part', 'акт*', '--limit', '5'], 'backup_search_files', 'odbcli_search_files')
