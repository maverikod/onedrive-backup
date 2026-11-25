'''cmd_backup_download_chunk: every focused case of matrix row M21 (backup_download_chunk, NEW) runs against the production service (matrix TODO 10.22.4.3, 10.22.6.8, TM4, TM5, TM12; block MODEL-REV14); the case tm14_model_recipe is executed by the check model_recipe.'''

from __future__ import annotations

from pipeline import rev14, rev14bytes


def run() -> None:
    '''Raise CheckFailure when the check is RED.

    Returns:
        None.
    '''
    rev14.run_row('M21', 'cmd_backup_download_chunk', rev14bytes.CHUNK_VALIDATORS, rev14bytes.CHUNK_ERRORS, setup=rev14bytes.setup, only=lambda cid: cid != 'tm14_model_recipe', all_new=True)
