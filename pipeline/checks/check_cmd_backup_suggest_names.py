'''cmd_backup_suggest_names: every focused case of matrix row M14 (backup_suggest_names) runs against the deployed service (matrix TODO 10.19.5, block FILTER-REV11).'''

from __future__ import annotations

from pipeline import rev11


def run() -> None:
    '''Raise CheckFailure when a case of row M14 is RED.

    Returns:
        None.
    '''
    rev11.run_row('M14', 'cmd_backup_suggest_names')
