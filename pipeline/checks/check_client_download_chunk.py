'''client_download_chunk: CK-BYTE2, BackupClient.download_chunk of the command backup_download_chunk (matrix TODO 10.22.4.3, 10.22.6.11 CLIENT, block MODEL-REV14).'''

from __future__ import annotations

from pipeline import rev14cli


def run() -> None:
    '''Raise CheckFailure when the check is RED.

    Returns:
        None.
    '''
    rev14cli.client_chunk('client_download_chunk')
