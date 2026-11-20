'''auth_key_optional: AU6: the optional key path is configuration-only: a keyed disposable instance answers 401 without the key and runs with it; the clients carry it and never print it

Mode: disposable instance of the deployed image on the host (run as root there) plus the open production service (revision 8, 10.15.9.2 PP-D1b); the logic is in pipeline.b4key.
Findings are kept apart as PRODUCT, STATE and ENVIRONMENT; a prerequisite that is missing is RED [ENVIRONMENT], never skipped.
'''

from __future__ import annotations

from pipeline import b4key


def run() -> None:
    '''Raise CheckFailure when the check is RED.'''
    b4key.auth_key_optional()
