'''version_consistency: VERSION is the single source of the release version (matrix row VR1, R11).

Mode: source-static. Every place of the repository that states the release version must equal the
content of VERSION or read it at runtime; a literal version in server or test code is a violation.
Places inspected: client/pyproject.toml, client __version__, every version literal in src/ (server
help/info/OpenAPI), version literals in tests/ fixtures, the release scripts build.sh,
scripts/build-deb.sh and docker/deploy.sh (they must read VERSION and tag image, deb and wheel with
it), the image tag in docker/compose.yml and docker/container.env.example, artifact names in the
README files and packaging, the README title and the top CHANGELOG entry.
The version a running server reports is checked live by the B4 checks cmd_info and cmd_help; this
check never reaches the service.
'''

from __future__ import annotations

import ast
import re
from pathlib import Path

from pipeline.checks import CheckFailure

ROOT = Path(__file__).resolve().parents[2]
EXACT = re.compile(r'^[0-9]+[.][0-9]+[.][0-9]+$')
PYPROJECT_VERSION = re.compile(r'^version\s*=\s*"([^"]+)"', re.M)
ARTIFACTS = (
    ('image tag', re.compile(r'onedrive-backup:([0-9]+[.][0-9]+[.][0-9]+)')),
    ('deb name', re.compile(r'onedrive-backup_([0-9]+[.][0-9]+[.][0-9]+)_all')),
    ('wheel name', re.compile(r'onedrive_backup_client-([0-9]+[.][0-9]+[.][0-9]+)')),
)
ARTIFACT_FILES = ('README.md', 'client/README.md', 'docker/compose.yml', 'docker/container.env.example',
                  'build.sh', 'scripts/build-deb.sh', 'docker/deploy.sh',
                  'docker/Dockerfile', 'docker/dockerhub_repo.sh')
# Revision 8 (PX6): the smoke script is scripts/smoke-https.sh and smoke-mtls.sh is retired; whichever of the two exists is inspected (the
# absence of smoke-https.sh is the RED of the named check smoke_https, not of this version check).
ARTIFACT_FILES += tuple(item for item in ('scripts/smoke-https.sh', 'scripts/smoke-mtls.sh') if (ROOT / item).is_file())
MUST_CARRY_IMAGE_TAG = ('docker/compose.yml', 'docker/container.env.example')
READS_VERSION_FILE = ('build.sh', 'scripts/build-deb.sh', 'docker/deploy.sh')
TAGS_WITH_VARIABLE = (('build.sh', r'onedrive-backup:\$VERSION'), ('scripts/build-deb.sh', r'onedrive-backup:\$VERSION'),
                      ('scripts/build-deb.sh', r'Version:\s*\$VERSION'))
VERSION_LITERAL = re.compile(r'^[0-9]+[.][0-9]+[.][0-9]+')


def _text(rel: str, problems: list[str]) -> str:
    '''Return the text of a repository file or record that it is missing.'''
    path = ROOT / rel
    if not path.is_file():
        problems.append('%s: file is missing' % rel)
        return ''
    return path.read_text(encoding='utf-8', errors='replace')


def _line(text: str, offset: int) -> int:
    '''Return the 1-based line number of a character offset.'''
    return text.count('\n', 0, offset) + 1


def _literal_versions(tree: ast.AST) -> list[tuple[int, str]]:
    '''Return (line, value) of version literals: version = '..', version='..', {'version': '..'}.'''
    found: list[tuple[int, str]] = []

    def is_literal(node: ast.AST | None) -> bool:
        return (isinstance(node, ast.Constant) and isinstance(node.value, str)
                and VERSION_LITERAL.match(node.value) is not None)

    for node in ast.walk(tree):
        if isinstance(node, (ast.Assign, ast.AnnAssign)):
            targets = node.targets if isinstance(node, ast.Assign) else [node.target]
            named = any(isinstance(t, ast.Name) and t.id in ('version', '__version__') for t in targets)
            if named and is_literal(node.value):
                found.append((node.lineno, node.value.value))
        elif isinstance(node, ast.keyword):
            if node.arg == 'version' and is_literal(node.value):
                found.append((node.value.lineno, node.value.value))
        elif isinstance(node, ast.Dict):
            for key, value in zip(node.keys, node.values):
                if isinstance(key, ast.Constant) and key.value == 'version' and is_literal(value):
                    found.append((value.lineno, value.value))
    return sorted(set(found))


def _scan_code(base: str, advice: str, problems: list[str]) -> None:
    '''Report every version literal of the python files under base.'''
    for path in sorted((ROOT / base).rglob('*.py')):
        rel = path.relative_to(ROOT).as_posix()
        try:
            tree = ast.parse(path.read_text(encoding='utf-8'))
        except (SyntaxError, UnicodeDecodeError) as exc:
            problems.append('%s: cannot parse: %s' % (rel, exc))
            continue
        for line, value in _literal_versions(tree):
            problems.append('%s:%d: hardcoded version literal %r; %s' % (rel, line, value, advice))


def run() -> None:
    '''Raise CheckFailure listing every place whose version differs from VERSION or is hardcoded.'''
    problems: list[str] = []
    version = _text('VERSION', problems).strip()
    if not EXACT.match(version):
        raise CheckFailure('VERSION: %r is not MAJOR.MINOR.PATCH' % version)

    pyproject = _text('client/pyproject.toml', problems)
    found = PYPROJECT_VERSION.search(pyproject)
    if not found:
        problems.append('client/pyproject.toml: no version = "..." line')
    elif found.group(1) != version:
        problems.append('client/pyproject.toml:%d: version %s, VERSION is %s'
                        % (_line(pyproject, found.start()), found.group(1), version))

    init = _text('client/onedrive_backup_client/__init__.py', problems)
    if init:
        literals = [item for item in _literal_versions(ast.parse(init))]
        if not re.search(r'^__version__\s*=', init, re.M):
            problems.append('client/onedrive_backup_client/__init__.py: no __version__')
        for line, value in literals:
            if value != version:
                problems.append('client/onedrive_backup_client/__init__.py:%d: __version__ %s, VERSION is %s'
                                % (line, value, version))

    _scan_code('src', 'the server must read VERSION at runtime (help, info, OpenAPI and command metadata)', problems)
    _scan_code('tests', 'a test fixture must derive the version from VERSION', problems)

    for rel in READS_VERSION_FILE:
        text = _text(rel, problems)
        if text and not re.search(r'^VERSION=.*VERSION', text, re.M):
            problems.append('%s: does not read the VERSION file into VERSION' % rel)
    for rel, pattern in TAGS_WITH_VARIABLE:
        text = _text(rel, problems)
        if text and not re.search(pattern, text):
            problems.append('%s: no %s; image tag and deb version must come from VERSION' % (rel, pattern))

    for rel in ARTIFACT_FILES:
        path = ROOT / rel
        if not path.is_file():
            continue
        text = path.read_text(encoding='utf-8', errors='replace')
        seen_image_tag = False
        for label, pattern in ARTIFACTS:
            for match in pattern.finditer(text):
                seen_image_tag = seen_image_tag or label == 'image tag'
                if match.group(1) != version:
                    problems.append('%s:%d: %s %s, VERSION is %s'
                                    % (rel, _line(text, match.start()), label, match.group(1), version))
        if rel in MUST_CARRY_IMAGE_TAG and not seen_image_tag:
            problems.append('%s: no image tag onedrive-backup:<version>' % rel)

    readme = _text('README.md', problems)
    title = re.search(r'^# onedrive-backup\s+(\S+)', readme, re.M)
    if not title:
        problems.append('README.md: no title "# onedrive-backup <version>"')
    elif title.group(1) != version:
        problems.append('README.md:%d: title version %s, VERSION is %s'
                        % (_line(readme, title.start()), title.group(1), version))

    changelog = _text('CHANGELOG.md', problems)
    top = re.search(r'^##\s+([0-9]+[.][0-9]+[.][0-9]+)', changelog, re.M)
    if not top:
        problems.append('CHANGELOG.md: no "## <version>" entry')
    elif top.group(1) != version:
        problems.append('CHANGELOG.md:%d: top entry %s, VERSION is %s'
                        % (_line(changelog, top.start()), top.group(1), version))

    if problems:
        raise CheckFailure('VERSION is %s; %d violation(s):\n  %s' % (version, len(problems), '\n  '.join(problems)))
