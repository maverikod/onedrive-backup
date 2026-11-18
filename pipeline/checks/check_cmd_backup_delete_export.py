'''cmd_backup_delete_export: every focused case of matrix row M7 runs against the production service (block B3).

Mode: live over the interim JSON-RPC transport pipeline.live (the B4 client replaces it). The cases, their
placeholders and result contracts come from pipeline/matrix.yaml; execution, findings and the S0/S1 rules
are in pipeline.cmdcases. S1 cases are RED with an explicit reason until the owner provisions S1.
'''

from __future__ import annotations

from pipeline import cmdcases


def run() -> None:
    '''Raise CheckFailure when a case of row M7 is RED.'''
    cmdcases.run_row('M7', 'cmd_backup_delete_export')
