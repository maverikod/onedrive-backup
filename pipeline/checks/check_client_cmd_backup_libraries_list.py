'''client_cmd_backup_libraries_list: C-K9 client method of the command backup_libraries_list (row M9)

Mode: live against the production service (block B4, decisions 1..7 of the matrix TODO); the logic is in pipeline.b4client.
Findings are kept apart as PRODUCT, STATE and ENVIRONMENT; a case that needs S1 or credentials is RED with that reason.
'''

from __future__ import annotations

from pipeline import b4client


def run() -> None:
    '''Raise CheckFailure when the check is RED.'''
    b4client.client_cmd('backup_libraries_list', 'M9', 'client_cmd_backup_libraries_list')
