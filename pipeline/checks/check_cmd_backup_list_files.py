'''cmd_backup_list_files: every focused case of matrix row M4 (backup_list_files) runs against the production service: the cases of block B3 through pipeline.cmdcases, the revision 14 cases TM8, TD14 (matrix TODO 10.22.6.3) through pipeline.rev14.'''

from __future__ import annotations

from pipeline import rev14bytes, rev14cmd


def run() -> None:
    '''Raise CheckFailure when a case of row M4 is RED.

    Returns:
        None.
    '''
    rev14cmd.run_cmd_row('M4', 'cmd_backup_list_files', rev14bytes.FILES_VALIDATORS, {})
