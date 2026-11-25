'''help_text_contract: the help and info text of revision 14 (matrix TODO 10.22.9 TM9, TM10; rows M1 help and M2 info; block MODEL-REV14).'''

from __future__ import annotations

from pipeline import rev14docs


def run() -> None:
    '''Raise CheckFailure when the help or info text breaks a TM9 or TM10 point.

    Returns:
        None.
    '''
    rev14docs.help_text_contract('help_text_contract')
