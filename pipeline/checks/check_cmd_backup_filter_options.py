'''cmd_backup_filter_options: every focused case of matrix row M12 (backup_filter_options) runs against the deployed service (matrix TODO 10.19.5, block FILTER-REV11).'''

from __future__ import annotations

from pipeline import rev11


def run() -> None:
    '''Raise CheckFailure when a case of row M12 is RED.

    Returns:
        None.
    '''
    rev11.run_row('M12', 'cmd_backup_filter_options')
