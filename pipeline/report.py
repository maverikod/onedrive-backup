'''Result collector of the B3 checks: product, state and environment findings kept apart.'''

from __future__ import annotations

from pipeline.checks import CheckFailure


class Report:
    '''Collects findings; finish() raises CheckFailure when any finding exists.

    product: the code or the deployed service violates the contract (a defect for the coder);
    state: a case needs the owner to provision state first (S1: host directory, container mount,
    restic password, login and password, finished inventory) and is RED with that reason;
    environment: the pipeline cannot reach or use what it needs (reported separately, never a defect).
    '''

    def __init__(self) -> None:
        self.product: list[str] = []
        self.state: list[str] = []
        self.env: list[str] = []
        self.info: list[str] = []

    def finish(self, name: str) -> None:
        for line in self.info:
            print('[INFO]', line, flush=True)
        if not (self.product or self.state or self.env):
            return
        lines = ['[PRODUCT] ' + item for item in self.product]
        lines += ['[STATE] ' + item for item in self.state]
        lines += ['[ENVIRONMENT] ' + item for item in self.env]
        raise CheckFailure('%s: %d product violation(s), %d state RED(s), %d environment error(s):\n  %s'
                           % (name, len(self.product), len(self.state), len(self.env), '\n  '.join(lines)))
