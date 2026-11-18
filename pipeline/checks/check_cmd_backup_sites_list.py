'''cmd_backup_sites_list: every focused case of matrix row M8 (backup_sites_list) runs against the production service

Mode: live against the production service (block B4, decisions 1..7 of the matrix TODO); the logic is in pipeline.cmdcases.
Findings are kept apart as PRODUCT, STATE and ENVIRONMENT; a case that needs S1 or credentials is RED with that reason.
'''

from __future__ import annotations

from pipeline import cmdcases


def run() -> None:
    '''Raise CheckFailure when the check is RED.'''
    cmdcases.run_row('M8', 'cmd_backup_sites_list')
