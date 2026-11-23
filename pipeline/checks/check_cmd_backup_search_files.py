'''cmd_backup_search_files: every focused case of matrix row M13 (backup_search_files) runs against the deployed service (matrix TODO 10.19.5 and 10.21.7 TC7-TC12, TC14; blocks FILTER-REV11, TREE-REV13).'''

from __future__ import annotations

from pipeline import rev13, rev13scope


def run() -> None:
    '''Raise CheckFailure when a case of row M13 is RED.

    Returns:
        None.
    '''
    rev13.run_row('M13', 'cmd_backup_search_files', rev13scope.VALIDATORS)
