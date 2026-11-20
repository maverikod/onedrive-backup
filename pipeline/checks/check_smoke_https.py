'''smoke_https: PX6: scripts/smoke-https.sh and a disposable server-auth HTTPS instance: health 200 without a client certificate, plain HTTP refused, an untrusting client fails, snapshots 503

Mode: disposable instance of the deployed image on the host (run as root there, in the manner of the former smoke_mtls); the logic is in pipeline.b4key.
Findings are kept apart as PRODUCT, STATE and ENVIRONMENT; a prerequisite that is missing is RED [ENVIRONMENT], never skipped.
'''

from __future__ import annotations

from pipeline import b4key


def run() -> None:
    '''Raise CheckFailure when the check is RED.'''
    b4key.smoke_https()
