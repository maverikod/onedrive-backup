'''client_cmd_backup_schedule_get: row CK-SCH1, BackupClient.schedule_get (matrix TODO 10.20.3 CLIENT AND CLI, block SCHEDULE-REV12).'''

from __future__ import annotations

from pipeline import sched12_live


def run() -> None:
    '''Raise CheckFailure when the client method is missing or differs from the command.

    Returns:
        None.
    '''
    sched12_live.client_check('schedule_get', 'client_cmd_backup_schedule_get')
