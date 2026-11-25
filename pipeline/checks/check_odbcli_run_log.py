'''odbcli_run_log: OC-RUN2, the odbcli subcommand run-log of the command backup_run_log (matrix TODO 10.23.R.5 ODBCLI, TR6, block RUN-REASON).'''

from __future__ import annotations

from pipeline import rev14runcli


def run() -> None:
    '''Raise CheckFailure when the check is RED.

    Returns:
        None.
    '''
    rev14runcli.odbcli_run_log('odbcli_run_log')
