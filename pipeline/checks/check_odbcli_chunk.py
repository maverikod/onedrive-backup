'''odbcli_chunk: OC-BYTE2, the odbcli subcommand chunk of the command backup_download_chunk (matrix TODO 10.22.6.11 ODBCLI, block MODEL-REV14).'''

from __future__ import annotations

from pipeline import rev14cli


def run() -> None:
    '''Raise CheckFailure when the check is RED.

    Returns:
        None.
    '''
    rev14cli.odbcli_chunk('odbcli_chunk')
