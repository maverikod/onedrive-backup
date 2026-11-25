'''cmd_backup_prepare_download: every focused case of matrix row M5 (backup_prepare_download) runs against the production service: the cases of blocks B3/B4 through pipeline.cmdcases, the revision 14 cases TM1-TM3, TM6, TM11, TM12 (matrix TODO 10.22.4) through pipeline.rev14.'''

from __future__ import annotations

from pipeline import rev14bytes, rev14cmd


def run() -> None:
    '''Raise CheckFailure when a case of row M5 is RED.

    Returns:
        None.
    '''
    rev14cmd.run_cmd_row('M5', 'cmd_backup_prepare_download', rev14bytes.PREPARE_VALIDATORS, rev14bytes.PREPARE_ERRORS, setup=rev14bytes.setup)
