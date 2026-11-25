'''odbcli_prepare: O5 and OC-BYTE1, the odbcli subcommand prepare (row M5; matrix TODO 10.22.6.11 ODBCLI, block MODEL-REV14).'''

from __future__ import annotations

from pipeline import rev14cli


def run() -> None:
    '''Raise CheckFailure when the check is RED.

    Returns:
        None.
    '''
    rev14cli.odbcli_prepare('odbcli_prepare')
