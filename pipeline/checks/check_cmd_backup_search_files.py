'''cmd_backup_search_files: every focused case of matrix row M13 (backup_search_files) runs against the deployed service (matrix TODO 10.19.5, block FILTER-REV11).'''

from __future__ import annotations

from pipeline import rev11


def run() -> None:
    '''Raise CheckFailure when a case of row M13 is RED.

    Returns:
        None.
    '''
    rev11.run_row('M13', 'cmd_backup_search_files')
