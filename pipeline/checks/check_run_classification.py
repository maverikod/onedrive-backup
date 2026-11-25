'''run_classification: exit 2 refused only for a guard before discovery, any discovery, tool or mirror failure is exit 1 with a reason, the other libraries continue (matrix TODO 10.23.R.3, TR3, row PL25, block RUN-CLASS).'''

from __future__ import annotations

from pipeline import rev14class


def run() -> None:
    '''Raise CheckFailure when the real run function classifies a failure differently from the contract.

    Returns:
        None.
    '''
    rev14class.run_classification('run_classification')
