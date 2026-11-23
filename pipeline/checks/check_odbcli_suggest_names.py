'''odbcli_suggest_names: rows O19 and OC-TREE3, the odbcli subcommand suggest-names (matrix TODO 10.19.5 and 10.21.4 ODBCLI, blocks FILTER-REV11, TREE-REV13).'''

from __future__ import annotations

from pipeline import rev13cli


def run() -> None:
    '''Raise CheckFailure when odbcli has no suggest-names, its scope arguments or wire map differ, or it does not print the command result.

    Returns:
        None.
    '''
    rev13cli.odbcli_scope('backup_suggest_names', 'odbcli_suggest_names')
