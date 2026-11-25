'''client_cmd_backup_prepare_download: C-K5 and CK-BYTE1, the client method of the command backup_prepare_download (row M5; matrix TODO 10.22.6.11 CLIENT, block MODEL-REV14).'''

from __future__ import annotations

from pipeline import rev14cli


def run() -> None:
    '''Raise CheckFailure when the check is RED.

    Returns:
        None.
    '''
    rev14cli.client_prepare('client_cmd_backup_prepare_download')
