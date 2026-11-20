'''adapter_only_transport: AU5: no project-owned transport, TLS, route-filter, middleware or authentication code; one StaticFiles mount; the CLAUDE.md standards text of revision 8

Mode: source-static over src/ and CLAUDE.md (revision 8, 10.15.9.2 PP-D1a); the logic is in pipeline.b4tls.
Findings are kept apart as PRODUCT, STATE and ENVIRONMENT; a prerequisite that is missing is RED [ENVIRONMENT], never skipped.
'''

from __future__ import annotations

from pipeline import b4tls


def run() -> None:
    '''Raise CheckFailure when the check is RED.'''
    b4tls.adapter_only_transport()
