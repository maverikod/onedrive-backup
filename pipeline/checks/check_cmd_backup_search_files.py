'''cmd_backup_search_files: every focused case of matrix row M13 (backup_search_files) runs against the deployed service (matrix TODO 10.19.5, 10.21.7 TC7-TC12, TC14 and 10.22.9 TD1-TD8, TD14, TD15, TM7, TM12; blocks FILTER-REV11, TREE-REV13, DATES-REV14).'''

from __future__ import annotations

from pipeline import rev13scope, rev14, rev14dates


def run() -> None:
    '''Raise CheckFailure when a case of row M13 is RED.

    Returns:
        None.
    '''
    rev14.run_row('M13', 'cmd_backup_search_files', rev14dates.VALIDATORS, rev14dates.ERRORS, old=rev13scope.VALIDATORS)
