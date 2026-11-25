'''endpoints_env_contract: the pipeline takes every endpoint only from the committed endpoints.env.

RED when pipeline/endpoints.env is missing, untracked, malformed, holds a secret, differs between
DEV and PROD for this production-only service, when the branch-to-environment rule is wrong, or
when any pipeline module holds a hardcoded URL, host:port or IP address (bug 7201e383).
'''

from __future__ import annotations

import ast
import re
import subprocess
from pathlib import Path
from urllib.parse import urlsplit

from pipeline import environment
from pipeline.checks import CheckFailure

ROOT = Path(__file__).resolve().parents[2]
URL = re.compile(r'[A-Za-z][A-Za-z0-9+.-]*://(?![^/?#\s]*[\[\]()\\^$*+?|])')
IPV4 = re.compile(r'(?<![0-9.])[0-9]{1,3}([.][0-9]{1,3}){3}(?![0-9.])')
HOSTPORT = re.compile(r'(?<![A-Za-z0-9_.-])[A-Za-z][A-Za-z0-9-]*([.][A-Za-z0-9-]+)*:[0-9]{2,5}(?![0-9:])')
SECRET_KEY = re.compile(r'PASSWORD|SECRET|TOKEN|PRIVATE|CREDENTIAL|API_KEY', re.I)
FORBIDDEN_VALUE = re.compile(r'-dev|_dev|lmrs', re.I)
KEY_SPLIT = re.compile(r'^(.+)_(DEV|PROD)$')
GOOD = (('main', '', 'prod'), ('cas', '', 'dev'), ('local', '', 'dev'), ('HEAD', '', 'dev'),
        ('main', 'prod', 'prod'), ('cas', 'dev', 'dev'))
REFUSED = (('main', 'dev'), ('cas', 'prod'), ('local', 'staging'), ('cas', 'DEV'))


def _docstring_ids(tree: ast.AST) -> set[int]:
    found: set[int] = set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.Module, ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            first = node.body[0] if node.body else None
            if (isinstance(first, ast.Expr) and isinstance(first.value, ast.Constant)
                    and isinstance(first.value.value, str)):
                found.add(id(first.value))
    return found


def hardcoded_endpoints(path: Path) -> list[tuple[int, str, str]]:
    '''Return (line, kind, literal) for every hardcoded endpoint string literal of a module.'''
    tree = ast.parse(path.read_text(encoding='utf-8'), filename=str(path))
    skip = _docstring_ids(tree)
    found = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Constant) and isinstance(node.value, str) and id(node) not in skip:
            for kind, rx in (('URL', URL), ('IPv4 address', IPV4), ('host:port', HOSTPORT)):
                if rx.search(node.value):
                    found.append((node.lineno, kind, node.value))
                    break
    return sorted(found)


def _endpoint_file_problems(problems: list[str]) -> None:
    name = 'pipeline/endpoints.env'
    tracked = subprocess.run(['git', '-c', 'safe.directory=%s' % ROOT, 'ls-files', '--error-unmatch', name], cwd=ROOT,
                             capture_output=True, text=True)
    if tracked.returncode != 0:
        problems.append('%s is not committed to git (or does not exist)' % name)
    try:
        values = environment.parse_endpoints()
    except (OSError, environment.PipelineEnvError) as exc:
        problems.append('%s: %s' % (name, exc))
        return
    pending = environment.pending_bases(values)
    bases: dict[str, dict[str, str]] = {}
    for key, value in values.items():
        if key == environment.PENDING_KEY:
            continue
        split = KEY_SPLIT.match(key)
        if not split:
            problems.append('%s: key %s does not end with _DEV or _PROD' % (name, key))
            continue
        bases.setdefault(split.group(1), {})[split.group(2)] = value
        if SECRET_KEY.search(key):
            problems.append('%s: key %s looks like a secret; secrets never go into git' % (name, key))
    for base, pair in sorted(bases.items()):
        if set(pair) != {'DEV', 'PROD'}:
            problems.append('%s: %s must have both _DEV and _PROD' % (name, base))
            continue
        if pair['DEV'] != pair['PROD']:
            problems.append('%s: %s differs between DEV and PROD, but onedrive-backup is a production-only '
                            'service and the MCP Proxy is shared' % (name, base))
        if base in pending:
            if pair['DEV'] or pair['PROD']:
                problems.append('%s: %s is declared pending and must stay empty' % (name, base))
            continue
        for env, value in sorted(pair.items()):
            if not value:
                problems.append('%s: %s_%s is empty but %s is not declared pending' % (name, base, env, base))
            if FORBIDDEN_VALUE.search(value):
                problems.append('%s: %s_%s names a -dev or lmrs endpoint' % (name, base, env))
            if base.endswith('_URL') and value and (urlsplit(value).scheme != 'https' or '@' in value):
                problems.append('%s: %s_%s must be an https URL without credentials' % (name, base, env))
    for base in pending:
        if base not in bases:
            problems.append('%s: %s is declared pending but has no _DEV/_PROD entries' % (name, base))


def _branch_rule_problems(problems: list[str]) -> None:
    for branch, explicit, expected in GOOD:
        try:
            got = environment.resolve_env(branch, explicit)
        except environment.PipelineEnvError as exc:
            got = 'refused: %s' % exc
        if got != expected:
            problems.append('environment.resolve_env(%r, %r) gave %r, expected %r' % (branch, explicit, got, expected))
    for branch, explicit in REFUSED:
        try:
            environment.resolve_env(branch, explicit)
        except environment.PipelineEnvError:
            continue
        problems.append('environment.resolve_env(%r, %r) must be refused' % (branch, explicit))
    try:
        environment.resolve_env()
    except environment.PipelineEnvError as exc:
        problems.append('the live PIPELINE_ENV/branch pair is refused: %s' % exc)


def _hardcode_problems(problems: list[str]) -> None:
    for path in sorted((ROOT / 'pipeline').rglob('*.py')):
        for line, kind, literal in hardcoded_endpoints(path):
            problems.append('%s:%d: hardcoded %s %r; it must come from pipeline/endpoints.env through '
                            'pipeline/environment.py' % (path.relative_to(ROOT), line, kind, literal))


def run() -> None:
    problems: list[str] = []
    _endpoint_file_problems(problems)
    _branch_rule_problems(problems)
    _hardcode_problems(problems)
    if problems:
        raise CheckFailure('%d violation(s):\n  - %s' % (len(problems), '\n  - '.join(problems)))
