'''folder_index_live: row PL19, the index file_dir of the host file index opened read-only (matrix TODO 10.21.2 and 10.21.8, block TREE-REV13).'''

from __future__ import annotations

from pipeline import rev13index


def run() -> None:
    '''Raise CheckFailure when the index file_dir is absent or an invariant of PL19 is broken.

    Returns:
        None.
    '''
    rev13index.folder_index_live()
