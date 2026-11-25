'''cmd_backup_download_status: every focused case of matrix row M6 (backup_download_status) runs against the production service: the cases of blocks B3/B4 through pipeline.cmdcases, the revision 14 cases of kind and file_id (matrix TODO 10.22.4.2, RM8) through pipeline.rev14.'''

from __future__ import annotations

from pipeline import rev14bytes, rev14cmd


def run() -> None:
    '''Raise CheckFailure when a case of row M6 is RED.

    Returns:
        None.
    '''
    rev14cmd.run_cmd_row('M6', 'cmd_backup_download_status', rev14bytes.STATUS_VALIDATORS, {}, setup=rev14bytes.setup)
