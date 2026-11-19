'''source_size: tracked Python modules under src/ and client/ stay within 400 lines.

RED when a git-tracked .py file under src/ or client/ has more than MAX_LINES lines, when such a
file is tracked but missing from the checked tree, or when a client/build directory exists in the
checked tree (stale build output, bug 0cb17da5; it is untracked and git-ignored, so only the tree
shows it). Every offending file is listed with its line count. The check needs no service, no
credentials and no network.
'''

from __future__ import annotations

import subprocess
from pathlib import Path

from pipeline.checks import CheckFailure

ROOT = Path(__file__).resolve().parents[2]
MAX_LINES = 400
SCOPES = ('src/', 'client/')


def _tracked_python() -> list[str]:
    '''Return the git-tracked .py files under the scoped directories, sorted.'''
    listed = subprocess.run(['git', '-c', 'safe.directory=%s' % ROOT, 'ls-files'], cwd=ROOT,
                            capture_output=True, text=True, check=False)
    if listed.returncode != 0:
        raise CheckFailure('git ls-files failed in %s: %s' % (ROOT, listed.stderr.strip()))
    return sorted(path for path in listed.stdout.splitlines()
                  if path.endswith('.py') and path.startswith(SCOPES))


def run() -> None:
    '''Raise CheckFailure listing every oversize module and any client/build directory.'''
    problems: list[str] = []
    files = _tracked_python()
    if not files:
        raise CheckFailure('no git-tracked .py file under src/ or client/ was found')
    for path in files:
        target = ROOT / path
        if not target.is_file():
            problems.append('%s: tracked but missing from the checked tree' % path)
            continue
        lines = len(target.read_text(encoding='utf-8').splitlines())
        if lines > MAX_LINES:
            problems.append('%s: %d lines (limit %d)' % (path, lines, MAX_LINES))
    if (ROOT / 'client' / 'build').is_dir():
        problems.append('client/build: stale build output directory exists in the checked tree')
    if problems:
        raise CheckFailure('%d violation(s):\n  - %s' % (len(problems), '\n  - '.join(problems)))
    print('[INFO] %d tracked python modules under src/ and client/ within %d lines'
          % (len(files), MAX_LINES))
