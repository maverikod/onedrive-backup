'''client_run_log: CK-RUN2, BackupClient.run_log of the command backup_run_log (matrix TODO 10.23.R.5 CLIENT, TR6, block RUN-REASON).'''

from __future__ import annotations

from pipeline import rev14runcli


def run() -> None:
    '''Raise CheckFailure when the check is RED.

    Returns:
        None.
    '''
    rev14runcli.client_run_log('client_run_log')
