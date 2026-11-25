'''cmd_backup_filter_options: every focused case of matrix row M12 (backup_filter_options) runs against the deployed service (matrix TODO 10.19.5 and 10.22.9 TD9, TD14; blocks FILTER-REV11, DATES-REV14).'''

from __future__ import annotations

from pipeline import rev14, rev14dates2


def run() -> None:
    '''Raise CheckFailure when a case of row M12 is RED.

    Returns:
        None.
    '''
    rev14.run_row('M12', 'cmd_backup_filter_options', rev14dates2.FO_VALIDATORS, rev14dates2.NO_ERRORS)
