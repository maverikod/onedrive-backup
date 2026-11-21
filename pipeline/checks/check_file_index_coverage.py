'''file_index_coverage: row PL14, the per-snapshot file index covers every snapshot of the deployed service (matrix TODO 10.19.6, block FILTER-REV11).'''

from __future__ import annotations

from pipeline import rev11


def run() -> None:
    '''Raise CheckFailure when the index does not cover every snapshot.

    Returns:
        None.
    '''
    rev11.file_index_coverage()
