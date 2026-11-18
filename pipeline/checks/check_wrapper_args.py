'''wrapper_args: onedrive-backup-docker passes every argument to docker-run.sh unchanged (row PL4, defect a).

Mode: fixture. A copy of packaging/onedrive-backup-docker runs with its docker-run.sh path redirected to
a stub that records the argv it receives. Every argument must arrive, in order and unchanged (quoting
and an empty argument included); with no argument the wrapper keeps its documented default, status.
'''

from __future__ import annotations

from pathlib import Path

from pipeline import fixtures
from pipeline.report import Report

ROOT = Path(__file__).resolve().parents[2]
CASES = (
    ['discover'], ['discover', '--dry-run'], ['backup', '--dry-run'], ['init'], ['check'], ['stop'],
    ['discover', '--dry-run', 'extra'], ['backup', 'two words', ''],
)


def _exec_line() -> int:
    text = (ROOT / 'packaging' / 'onedrive-backup-docker').read_text(encoding='utf-8')
    for number, raw in enumerate(text.splitlines(), 1):
        if fixtures.WRAPPER_DOCKER_RUN in raw:
            return number
    return 0


def run() -> None:
    '''Raise CheckFailure when an argument is dropped, changed or reordered by the wrapper.'''
    report = Report()
    line = _exec_line()
    where = 'packaging/onedrive-backup-docker:%d' % line
    for args in CASES + ([],):
        expected = args if args else ['status']
        rc, got, err, redirected = fixtures.run_wrapper(list(args))
        if not redirected:
            report.product.append('%s: the wrapper must exec %s (the fixture redirects that path)'
                                  % (where, fixtures.WRAPPER_DOCKER_RUN))
            break
        if rc != 0 or got != expected:
            report.product.append('%s: wrapper arguments %r reached docker-run.sh as %r (exit %d), expected %r %s'
                                  % (where, args, got, rc, expected, err))
    report.info.append('%d argument vectors run through a redirected copy of the wrapper' % (len(CASES) + 1))
    report.finish('wrapper_args')
