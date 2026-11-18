'''The ONE pipeline module that resolves the target environment and every endpoint value.

PIPELINE_ENV is decided by the git branch: main is always prod, every other branch is always dev.
The variable only carries that value; an explicit value that contradicts the branch, or any other
value, is refused. Endpoint values come only from the committed pipeline/endpoints.env, where every
endpoint has <NAME>_DEV and <NAME>_PROD. Nothing else in the pipeline may hold a URL, host or port.
'''

from __future__ import annotations

import os
import re
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ENDPOINTS_FILE = Path(__file__).resolve().with_name('endpoints.env')
ENV_VAR = 'PIPELINE_ENV'
VALUES = ('dev', 'prod')
PENDING_KEY = 'ENDPOINTS_PENDING'
LINE = re.compile(r'^([A-Z][A-Z0-9_]*)=(.*)$')


class PipelineEnvError(RuntimeError):
    '''The environment or an endpoint cannot be resolved; the pipeline must stop RED.'''


def current_branch(root: Path = ROOT) -> str:
    '''Return the current git branch name (HEAD when detached).'''
    done = subprocess.run(['git', 'rev-parse', '--abbrev-ref', 'HEAD'], cwd=root,
                          capture_output=True, text=True)
    if done.returncode != 0:
        raise PipelineEnvError('cannot read the git branch: ' + done.stderr.strip())
    return done.stdout.strip()


def resolve_env(branch: str | None = None, explicit: str | None = None) -> str:
    '''Return dev or prod from the branch; refuse a contradicting or unknown explicit value.'''
    name = current_branch() if branch is None else branch
    derived = 'prod' if name == 'main' else 'dev'
    given = os.environ.get(ENV_VAR) if explicit is None else explicit
    if given is None or given == '':
        return derived
    if given not in VALUES:
        raise PipelineEnvError('%s=%r is not one of %s' % (ENV_VAR, given, VALUES))
    if given != derived:
        raise PipelineEnvError('%s=%s contradicts branch %r which is always %s'
                               % (ENV_VAR, given, name, derived))
    return derived


def parse_endpoints(path: Path = ENDPOINTS_FILE) -> dict[str, str]:
    '''Parse NAME=VALUE lines of the committed endpoints file; reject malformed or duplicate lines.'''
    values: dict[str, str] = {}
    for number, raw in enumerate(path.read_text(encoding='utf-8').splitlines(), 1):
        text = raw.strip()
        if not text or text.startswith('#'):
            continue
        found = LINE.match(text)
        if not found:
            raise PipelineEnvError('%s:%d: not NAME=VALUE: %r' % (path.name, number, raw))
        if found.group(1) in values:
            raise PipelineEnvError('%s:%d: duplicate key %s' % (path.name, number, found.group(1)))
        values[found.group(1)] = found.group(2)
    return values


def pending_bases(values: dict[str, str]) -> list[str]:
    '''Endpoint base names declared as not deployed yet (their values stay empty).'''
    return [item for item in values.get(PENDING_KEY, '').split(',') if item]


def endpoint(base: str, env: str | None = None, values: dict[str, str] | None = None) -> str:
    '''Return the value of <base>_DEV or <base>_PROD for the resolved environment.'''
    table = parse_endpoints() if values is None else values
    if base in pending_bases(table):
        raise PipelineEnvError('endpoint %s is declared pending: its service is not deployed yet' % base)
    key = '%s_%s' % (base, (resolve_env() if env is None else env).upper())
    if table.get(key, '') == '':
        raise PipelineEnvError('endpoint %s is missing or empty in endpoints.env' % key)
    return table[key]
