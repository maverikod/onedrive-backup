'''cmd_backup_suggest_names: every focused case of matrix row M14 (backup_suggest_names) runs against the deployed service (matrix TODO 10.19.5, 10.21.7 TC12, TC13 and 10.22.9 TD2, TD12, TD14; blocks FILTER-REV11, TREE-REV13, DATES-REV14).'''

from __future__ import annotations

from pipeline import rev13scope, rev14, rev14dates2


def run() -> None:
    '''Raise CheckFailure when a case of row M14 is RED.

    Returns:
        None.
    '''
    rev14.run_row('M14', 'cmd_backup_suggest_names', rev14dates2.SUGGEST_VALIDATORS, rev14dates2.SUGGEST_ERRORS, old=rev13scope.VALIDATORS)
