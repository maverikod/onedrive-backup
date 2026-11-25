'''cmd_backup_run_log: every focused case of matrix row M24 (backup_run_log) runs against the deployed service (matrix TODO 10.23.R.2, 10.23.R.6 TR5, block RUN-REASON).'''

from __future__ import annotations

from pipeline import rev14runlog


def run() -> None:
    '''Raise CheckFailure when a case of row M24 is RED.

    Returns:
        None.
    '''
    rev14runlog.run_log_row('cmd_backup_run_log')
