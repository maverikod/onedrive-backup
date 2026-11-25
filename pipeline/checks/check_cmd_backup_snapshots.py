'''cmd_backup_snapshots: every focused case of matrix row M3 (backup_snapshots) runs against the production service: the cases of block B3 through pipeline.cmdcases, the revision 14 cases TD10 (matrix TODO 10.22.6.2) through pipeline.rev14.'''

from __future__ import annotations

from pipeline import rev14cmd, rev14dates2


def run() -> None:
    '''Raise CheckFailure when a case of row M3 is RED.

    Returns:
        None.
    '''
    rev14cmd.run_cmd_row('M3', 'cmd_backup_snapshots', rev14dates2.SNAP_VALIDATORS, rev14dates2.NO_ERRORS)
