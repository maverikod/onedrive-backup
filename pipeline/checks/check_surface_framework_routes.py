'''surface_framework_routes: framework routes F1..F11 of the adapter and the returned download routes

Mode: live against the production service (block B4, decisions 1..7 of the matrix TODO); the logic is in pipeline.b4server.
Findings are kept apart as PRODUCT, STATE and ENVIRONMENT; a case that needs S1 or credentials is RED with that reason.
'''

from __future__ import annotations

from pipeline import b4server


def run() -> None:
    '''Raise CheckFailure when the check is RED.'''
    b4server.surface_framework_routes()
