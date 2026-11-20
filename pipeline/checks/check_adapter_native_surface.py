'''adapter_native_surface: F1-F11: the live route set equals the adapter-native routes of 8.11.20; any other route is a project-owned addition

Mode: live against the production service (revision 8, 10.15.9.3 PP-D1c); the logic is in pipeline.b4server.
Findings are kept apart as PRODUCT, STATE and ENVIRONMENT; a prerequisite that is missing is RED [ENVIRONMENT], never skipped.
'''

from __future__ import annotations

from pipeline import b4server


def run() -> None:
    '''Raise CheckFailure when the check is RED.'''
    b4server.adapter_native_surface()
