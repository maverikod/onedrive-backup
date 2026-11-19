'''adapter_version_pin: mcp-proxy-adapter is pinned to ONE exact version everywhere (matrix row VR2).

The expected pin is not a constant of this check: it is derived from the single source docker/requirements-server.txt, which must
carry exactly one declaration mcp-proxy-adapter==X.Y.Z (today 8.11.20, ADAPTER-8.11.20 coder, commit 1a8f785). Mode: source-static.
Declarations inspected: every requirements*.txt, pyproject.toml, setup.py, setup.cfg, Pipfile and Dockerfile of the repository
(generated and vendored directories, the prompt packages and the pipeline itself are skipped). Rules: every declaration of the package
must be the exact pin ==X.Y.Z; docker/requirements-server.txt and client/pyproject.toml must declare it (the client builds on the
adapter JsonRpcClient, approval 7); the Dockerfile must install the requirements file or pin the package inline; no document or script
may state another version of the adapter (the CHANGELOG is history and only its top entry is read; an upgrade statement 'A.B.C -> X.Y.Z'
whose target is the pin is allowed there); the matrix text that says 'pinned to', 'live', 'pin' or '==' before an adapter version names the pin. That the running server reports
the pinned adapter version is checked live by the B4 checks, never here.
'''

from __future__ import annotations

import os
import re
from pathlib import Path

from pipeline.checks import CheckFailure

ROOT = Path(__file__).resolve().parents[2]
SOURCE = 'docker/requirements-server.txt'
PINNED = re.compile(r'^\s*mcp[-_.]proxy[-_.]adapter\s*==\s*([0-9]+[.][0-9]+[.][0-9]+)\s*$', re.I | re.M)
NAME = r'mcp[-_.]proxy[-_.]adapter'
DECLARATION = re.compile(NAME + r'\s*(?:\[[^\]]*\])?\s*(===|==|>=|<=|~=|!=|>|<)?\s*([0-9A-Za-z.*+-]+)?', re.I)
PROSE = re.compile(NAME + r'[\s=:v]*([0-9]+[.][0-9]+[.][0-9]+)', re.I)
SKIP_DIRS = {'.git', '.venv', '.build-venv', 'build', 'dist', 'node_modules', '__pycache__', '.terminals',
             '.test-run', 'claude', 'codex', 'pipeline', 'old_code', '.mypy_cache'}
DECLARATION_NAMES = ('pyproject.toml', 'setup.py', 'setup.cfg', 'Pipfile')
REQUIRED = ('docker/requirements-server.txt', 'client/pyproject.toml')
PROSE_FILES = ('README.md', 'client/README.md', 'src/onedrive_api/ONEDRIVE_INFO.md', 'docker/compose.yml',
               'docker/container.env.example', 'build.sh', 'scripts/build-deb.sh', 'docker/deploy.sh')


def _declaration_files() -> list[str]:
    '''Return repository-relative paths of every dependency declaration file.'''
    found: list[str] = []
    for base, dirs, files in os.walk(ROOT):
        dirs[:] = sorted(d for d in dirs if d not in SKIP_DIRS and not d.endswith('.egg-info'))
        for name in sorted(files):
            if (name.startswith('requirements') and name.endswith('.txt')) or name in DECLARATION_NAMES \
                    or name == 'Dockerfile' or name.startswith('Dockerfile.'):
                found.append((Path(base) / name).relative_to(ROOT).as_posix())
    return found


def _read(rel: str) -> str:
    return (ROOT / rel).read_text(encoding='utf-8', errors='replace')


def _check_declarations(rel: str, text: str, pin: str, problems: list[str]) -> bool:
    '''Check every declaration line of one file; return True when the file pins the package.'''
    pinned = False
    for number, raw in enumerate(text.splitlines(), 1):
        if raw.lstrip().startswith('#'):
            continue
        for match in DECLARATION.finditer(raw):
            operator, version = match.group(1), match.group(2)
            if operator == '==' and version == pin:
                pinned = True
            else:
                problems.append('%s:%d: declares %s (%s); the only allowed declaration is mcp-proxy-adapter==%s'
                                % (rel, number, 'mcp-proxy-adapter' + (operator or '') + (version or ''),
                                   raw.strip(), pin))
    return pinned


def _expected() -> str | None:
    '''The pin of the single source file, or None when it declares no exact pin.'''
    try:
        found = PINNED.findall(_read(SOURCE))
    except OSError:
        return None
    return found[0] if len(found) == 1 else None


def _changelog(pin: str, problems: list[str]) -> None:
    changelog = _read('CHANGELOG.md') if (ROOT / 'CHANGELOG.md').is_file() else ''
    lines = changelog.splitlines()
    starts = [i for i, raw in enumerate(lines) if raw.startswith('## ')]
    if not starts:
        return
    series = re.compile(r'(?<![0-9.])' + re.escape('.'.join(pin.split('.')[:2])) + r'[.]([0-9]+)(?![0-9])')
    end = starts[1] if len(starts) > 1 else len(lines)
    for index in range(starts[0], end):
        for match in series.finditer(lines[index]):
            version = match.group(0)
            if version != pin and not re.search(re.escape(version) + r'\s*(->|\u2192)\s*' + re.escape(pin), lines[index]):
                problems.append('CHANGELOG.md:%d: top entry states adapter version %s, pin is %s' % (index + 1, version, pin))


def run() -> None:
    '''Raise CheckFailure listing every dependency declaration or statement that breaks the pin.'''
    problems: list[str] = []
    pin = _expected()
    if pin is None:
        raise CheckFailure('%s must declare exactly one pin mcp-proxy-adapter==X.Y.Z (the single source of the expected version)' % SOURCE)
    pinned: dict[str, bool] = {}
    declarations = _declaration_files()
    for rel in REQUIRED:
        if rel not in declarations:
            problems.append('%s: file is missing' % rel)
    for rel in declarations:
        pinned[rel] = _check_declarations(rel, _read(rel), pin, problems)
    for rel in REQUIRED:
        if rel in declarations and not pinned[rel]:
            if not re.search(NAME, _read(rel), re.I):
                problems.append('%s: does not declare mcp-proxy-adapter==%s' % (rel, pin))
    for rel in declarations:
        if rel.endswith('Dockerfile') or '/Dockerfile.' in rel or rel.startswith('Dockerfile'):
            text = _read(rel)
            if not pinned[rel] and not re.search(r'pip install[^\n]*-r\s+\S*requirements-server[.]txt', text):
                problems.append('%s: neither installs requirements-server.txt nor pins mcp-proxy-adapter==%s' % (rel, pin))

    for rel in PROSE_FILES:
        if not (ROOT / rel).is_file():
            continue
        for number, raw in enumerate(_read(rel).splitlines(), 1):
            for match in PROSE.finditer(raw):
                if match.group(1) != pin:
                    problems.append('%s:%d: states adapter version %s, pin is %s (%s)'
                                    % (rel, number, match.group(1), pin, raw.strip()[:100]))
    _changelog(pin, problems)
    matrix_file = ROOT / 'pipeline' / 'matrix.yaml'
    if matrix_file.is_file():
        statement = re.compile(r'(pinned to|live|pin|==)\s?(' + re.escape('.'.join(pin.split('.')[:2])) + r'[.][0-9]+)')
        for number, raw in enumerate(matrix_file.read_text(encoding='utf-8').splitlines(), 1):
            for match in statement.finditer(raw):
                if match.group(2) != pin:
                    problems.append('pipeline/matrix.yaml:%d: says "%s %s", pin is %s' % (number, match.group(1), match.group(2), pin))

    if problems:
        raise CheckFailure('adapter pin is %s (from %s); %d violation(s):\n  %s' % (pin, SOURCE, len(problems), '\n  '.join(problems)))
    print('[INFO] adapter pin %s derived from %s' % (pin, SOURCE))
