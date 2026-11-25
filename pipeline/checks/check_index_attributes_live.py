'''index_attributes_live: row PL20, the snapshot attribute columns and the backfill of the host file index opened read-only (matrix TODO 10.22.9 TD13, block DATES-REV14).'''

from __future__ import annotations

from pipeline import rev14index


def run() -> None:
    '''Raise CheckFailure when a column or a backfilled value of 10.22.2.5 is missing or an invariant of TD13 is broken.

    Returns:
        None.
    '''
    rev14index.index_attributes_live('index_attributes_live')
