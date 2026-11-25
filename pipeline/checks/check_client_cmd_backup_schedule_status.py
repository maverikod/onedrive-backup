'''client_cmd_backup_schedule_status: row CK-SCH3, BackupClient.schedule_status (matrix TODO 10.20.3 CLIENT AND CLI, block SCHEDULE-REV12).'''

from __future__ import annotations

from pipeline import rev14runcli


def run() -> None:
    '''Raise CheckFailure when the client method is missing, differs from the command or the run keys reason, log, retried are absent.

    Returns:
        None.
    '''
    rev14runcli.client_status('client_cmd_backup_schedule_status')
