'''odbcli_search_files: rows O18 and OC-TREE2, the odbcli subcommand search-files (matrix TODO 10.19.5 and 10.21.4 ODBCLI, blocks FILTER-REV11, TREE-REV13).'''

from __future__ import annotations

from pipeline import rev13cli


def run() -> None:
    '''Raise CheckFailure when odbcli has no search-files, its scope arguments or wire map differ, or it does not print the command result.

    Returns:
        None.
    '''
    rev13cli.odbcli_scope('backup_search_files', 'odbcli_search_files')
