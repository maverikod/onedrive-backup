'''cmd_backup_suggest_names: every focused case of matrix row M14 (backup_suggest_names) runs against the deployed service (matrix TODO 10.19.5 and 10.21.7 TC12, TC13; blocks FILTER-REV11, TREE-REV13).'''

from __future__ import annotations

from pipeline import rev13, rev13scope


def run() -> None:
    '''Raise CheckFailure when a case of row M14 is RED.

    Returns:
        None.
    '''
    rev13.run_row('M14', 'cmd_backup_suggest_names', rev13scope.VALIDATORS)
