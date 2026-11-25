'''model_recipe: the model path of matrix TODO 10.22.4.4 (TM14) and the file id resolver PL22 (TM7, TM12) through JSON-RPC only (rows M21, PL22; block MODEL-REV14).'''

from __future__ import annotations

from pipeline import rev14recipe


def run() -> None:
    '''Raise CheckFailure when the check is RED.

    Returns:
        None.
    '''
    rev14recipe.model_recipe('model_recipe')
