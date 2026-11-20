'''tls_server_auth: PX10: a handshake without a client certificate succeeds, the certificate matches the LAN IP and the alias, TLS < 1.2 and plain HTTP are refused

Mode: live against the production service and its LAN URL (revision 8, 10.15.3); the logic is in pipeline.b4tls.
Findings are kept apart as PRODUCT, STATE and ENVIRONMENT; a prerequisite that is missing is RED [ENVIRONMENT], never skipped.
'''

from __future__ import annotations

from pipeline import b4tls


def run() -> None:
    '''Raise CheckFailure when the check is RED.'''
    b4tls.tls_server_auth()
