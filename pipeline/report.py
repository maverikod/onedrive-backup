'''Result collector of the B3 and B4 checks: product, state and environment findings kept apart.'''

from __future__ import annotations

import re

from pipeline import credentials
from pipeline.checks import CheckFailure

# R17: every check whose cases send the token T of the run credentials. A missing or unusable run environment makes the
# cases that need T RED as STATE or ENVIRONMENT, never PRODUCT, never skipped and never a pass.
TOKEN_CHECKS = ('auth_token', 'cmd_', 'client_cmd_', 'odbcli_', 'download_link', 'transfer_confinement', 'client_download',
                'client_auth', 'client_call_raw', 'client_fetch_integrity', 'ws_closed', 'surface_framework_routes',
                'rest_removed', 'vue_', 'rclone_remote_access')
# A finding that only reports what the token gate answered to a request that carried no usable token.
GATE_ANSWER = re.compile(r'(answered|got|code=|HTTP|status) ?401|ClientAuthenticationError|authentication_error')


def needs_token(name: str) -> bool:
    '''True when the named check sends the run token T (R17).'''
    return any(name == item or (item.endswith('_') and name.startswith(item)) or
               (item == 'client_download' and name.startswith(item)) for item in TOKEN_CHECKS)


class Report:
    '''Collects findings; finish() raises CheckFailure when any finding exists.

    product: the code or the deployed service violates the contract (a defect for the coder);
    state: a case needs the owner to provision state first (S1: host directory, container mount,
    restic password, login and password, finished inventory) and is RED with that reason;
    environment: the pipeline cannot reach or use what it needs (reported separately, never a defect).

    R17: when the run credentials (login and password of row PX11) are missing or unusable, a token check never reports
    PRODUCT for what the token gate answered: those findings move to STATE and one ENVIRONMENT line names the problem.
    '''

    def __init__(self) -> None:
        self.product: list[str] = []
        self.state: list[str] = []
        self.env: list[str] = []
        self.info: list[str] = []
        self.gap: list[str] = []

    def _classify_run_environment(self, name: str) -> None:
        problem = credentials.problem() if needs_token(name) else None
        if not problem:
            return
        kept = []
        for item in self.product:
            if GATE_ANSWER.search(item):
                self.state.append('needs the run token T, not a product finding (R17): ' + item)
            else:
                kept.append(item)
        self.product = kept
        self.env.append('R17 run credentials: ' + problem)

    def finish(self, name: str) -> None:
        self._classify_run_environment(name)
        for line in self.info:
            print('[INFO]', line, flush=True)
        if not (self.product or self.state or self.env or self.gap):
            return
        lines = ['[PRODUCT] ' + item for item in self.product]
        lines += ['[STATE] ' + item for item in self.state]
        lines += ['[ENVIRONMENT] ' + item for item in self.env]
        lines += ['[GAP] ' + item for item in self.gap]
        extra = ', %d matrix-gap assertion(s) pending' % len(self.gap) if self.gap else ''
        raise CheckFailure('%s: %d product violation(s), %d state RED(s), %d environment error(s)%s:\n  %s'
                           % (name, len(self.product), len(self.state), len(self.env), extra, '\n  '.join(lines)))
