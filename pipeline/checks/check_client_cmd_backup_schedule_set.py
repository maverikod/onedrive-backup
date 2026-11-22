'''client_cmd_backup_schedule_set: row CK-SCH2, BackupClient.schedule_set; the pipeline sends a dry run (matrix TODO 10.20.3 CLIENT AND CLI, block SCHEDULE-REV12).'''

from __future__ import annotations

from pipeline import sched12_live


def run() -> None:
    '''Raise CheckFailure when the client method is missing or differs from the command.

    Returns:
        None.
    '''
    sched12_live.client_check('schedule_set', 'client_cmd_backup_schedule_set')
