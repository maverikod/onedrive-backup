'''client_cmd_backup_discovery_status: C-K10 client method of the command backup_discovery_status (row M10)

Mode: live against the production service (block B4, decisions 1..7 of the matrix TODO); the logic is in pipeline.b4client.
Findings are kept apart as PRODUCT, STATE and ENVIRONMENT; a case that needs S1 or credentials is RED with that reason.
'''

from __future__ import annotations

from pipeline import b4client


def run() -> None:
    '''Raise CheckFailure when the check is RED.'''
    b4client.client_cmd('backup_discovery_status', 'M10', 'client_cmd_backup_discovery_status')
