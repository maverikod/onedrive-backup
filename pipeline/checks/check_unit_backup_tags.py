'''unit_backup_tags: row PL20, the restic tags type-full, trigger-<..> and run-<id> of a NEW snapshot through the real seam of sync_library (matrix TODO 10.22.9 TD16, block DATES-REV14).'''

from __future__ import annotations

from pipeline import rev14tags


def run() -> None:
    '''Raise CheckFailure when the restic backup argv of sync_library lacks the run attribute tags.

    Returns:
        None.
    '''
    rev14tags.unit_backup_tags('unit_backup_tags')
