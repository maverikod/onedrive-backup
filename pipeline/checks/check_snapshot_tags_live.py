'''snapshot_tags_live: row PL20, LAGGING check of the tags of the first scheduled run after the deployment (matrix TODO 10.22.9 TD17, block DATES-REV14).'''

from __future__ import annotations

from pipeline import rev14index


def run() -> None:
    '''Raise CheckFailure until the three newest snapshots are one scheduled run tagged by the backup command (never skipped, never starts a backup).

    Returns:
        None.
    '''
    rev14index.snapshot_tags_live('snapshot_tags_live')
