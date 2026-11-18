'''run_credentials_env: the run-credentials environment (PX11, R17)

Mode: live against the production service or its disposable instances (block B4, revision 4 of the matrix TODO); the logic is in pipeline.b4env.
Findings are kept apart as PRODUCT, STATE and ENVIRONMENT; a case that needs S1 or credentials is RED with that reason.
'''

from __future__ import annotations

from pipeline import b4env


def run() -> None:
    '''Raise CheckFailure when the check is RED.'''
    b4env.run_credentials_env()
