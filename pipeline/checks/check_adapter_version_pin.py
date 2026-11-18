'''adapter_version_pin: mcp-proxy-adapter is pinned to exactly 8.11.16 everywhere (matrix row VR2).

Mode: source-static. Declarations inspected: every requirements*.txt, pyproject.toml, setup.py,
setup.cfg, Pipfile and Dockerfile of the repository (generated and vendored directories, the
prompt packages and the pipeline itself are skipped). Rules: every declaration of the package must
be the exact pin ==8.11.16; docker/requirements-server.txt and client/pyproject.toml must declare
it (the client builds on the adapter JsonRpcClient, approval 7); the Dockerfile must install the
requirements file or pin the package inline; no document or script may state another 8.11.x
version (the CHANGELOG is history and only its top entry is read). That the running server reports
the pinned adapter version is checked live by the B4 checks, never here.
'''

from __future__ import annotations

import os
import re
from pathlib import Path

from pipeline.checks import CheckFailure

ROOT = Path(__file__).resolve().parents[2]
PIN = '8.11.16'
NAME = r'mcp[-_.]proxy[-_.]adapter'
DECLARATION = re.compile(NAME + r'\s*(?:\[[^\]]*\])?\s*(===|==|>=|<=|~=|!=|>|<)?\s*([0-9A-Za-z.*+-]+)?', re.I)
PROSE = re.compile(NAME + r'[\s=:v]*([0-9]+[.][0-9]+[.][0-9]+)', re.I)
ANY_ADAPTER_VERSION = re.compile(r'(?<![0-9.])8[.]11[.]([0-9]+)(?![0-9])')
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


def _check_declarations(rel: str, text: str, problems: list[str]) -> bool:
    '''Check every declaration line of one file; return True when the file pins the package.'''
    pinned = False
    for number, raw in enumerate(text.splitlines(), 1):
        if raw.lstrip().startswith('#'):
            continue
        for match in DECLARATION.finditer(raw):
            operator, version = match.group(1), match.group(2)
            if operator == '==' and version == PIN:
                pinned = True
            else:
                problems.append('%s:%d: declares %s (%s); the only allowed declaration is mcp-proxy-adapter==%s'
                                % (rel, number, 'mcp-proxy-adapter' + (operator or '') + (version or ''),
                                   raw.strip(), PIN))
    return pinned


def run() -> None:
    '''Raise CheckFailure listing every dependency declaration or statement that breaks the pin.'''
    problems: list[str] = []
    pinned: dict[str, bool] = {}
    declarations = _declaration_files()
    for rel in REQUIRED:
        if rel not in declarations:
            problems.append('%s: file is missing' % rel)
    for rel in declarations:
        pinned[rel] = _check_declarations(rel, _read(rel), problems)
    for rel in REQUIRED:
        if rel in declarations and not pinned[rel]:
            if not re.search(NAME, _read(rel), re.I):
                problems.append('%s: does not declare mcp-proxy-adapter==%s' % (rel, PIN))
    for rel in declarations:
        if rel.endswith('Dockerfile') or '/Dockerfile.' in rel or rel.startswith('Dockerfile'):
            text = _read(rel)
            if not pinned[rel] and not re.search(r'pip install[^\n]*-r\s+\S*requirements-server[.]txt', text):
                problems.append('%s: neither installs requirements-server.txt nor pins mcp-proxy-adapter==%s'
                                % (rel, PIN))

    for rel in PROSE_FILES:
        if not (ROOT / rel).is_file():
            continue
        for number, raw in enumerate(_read(rel).splitlines(), 1):
            for match in PROSE.finditer(raw):
                if match.group(1) != PIN:
                    problems.append('%s:%d: states adapter version %s, pin is %s (%s)'
                                    % (rel, number, match.group(1), PIN, raw.strip()[:100]))
    changelog = _read('CHANGELOG.md') if (ROOT / 'CHANGELOG.md').is_file() else ''
    lines = changelog.splitlines()
    starts = [i for i, raw in enumerate(lines) if raw.startswith('## ')]
    if starts:
        end = starts[1] if len(starts) > 1 else len(lines)
        for index in range(starts[0], end):
            for match in ANY_ADAPTER_VERSION.finditer(lines[index]):
                if match.group(1) != '16':
                    problems.append('CHANGELOG.md:%d: top entry states adapter version 8.11.%s, pin is %s'
                                    % (index + 1, match.group(1), PIN))

    if problems:
        raise CheckFailure('adapter pin is %s; %d violation(s):\n  %s' % (PIN, len(problems), '\n  '.join(problems)))
