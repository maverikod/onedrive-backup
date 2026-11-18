'''odbcli_surface: OS1 odbcli parity with the live server command list

Mode: live against the production service (block B4, decisions 1..7 of the matrix TODO); the logic is in pipeline.b4cli.
Findings are kept apart as PRODUCT, STATE and ENVIRONMENT; a case that needs S1 or credentials is RED with that reason.
'''

from __future__ import annotations

from pipeline import b4cli


def run() -> None:
    '''Raise CheckFailure when the check is RED.'''
    b4cli.odbcli_surface()
