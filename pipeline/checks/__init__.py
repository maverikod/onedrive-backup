'''Auto-discovered named checks: one file pipeline/checks/check_<name>.py per check.

A check module defines run() and raises CheckFailure when it is RED. A check that the matrix
registers as pending has no module yet; it is registered here as a stub that ALWAYS FAILS, so a
planned check can never pass before it is really written.
'''

from __future__ import annotations

import importlib
import pkgutil
from pathlib import Path
from types import ModuleType

DIR = Path(__file__).resolve().parent
PREFIX = 'check_'


class CheckFailure(AssertionError):
    '''A named check is RED; the message lists every violation.'''


def discover() -> dict[str, ModuleType]:
    '''Import every check_<name>.py module and return {name: module}.'''
    found: dict[str, ModuleType] = {}
    for info in sorted(pkgutil.iter_modules([str(DIR)]), key=lambda item: item.name):
        if info.name.startswith(PREFIX):
            found[info.name[len(PREFIX):]] = importlib.import_module(__name__ + '.' + info.name)
    return found


def pending_entries() -> dict[str, dict]:
    '''Matrix checks that are registered as pending and have no module yet.'''
    from pipeline import matrix
    try:
        entries = matrix.registry()
    except (OSError, ValueError, KeyError):
        return {}
    have = set(discover())
    return {name: entry for name, entry in entries.items()
            if entry.get('status') == 'pending' and name not in have}


def all_names() -> list[str]:
    '''Names of every check this package serves: implemented modules first, then pending stubs.'''
    return sorted(discover()) + sorted(pending_entries())


def run(name: str) -> None:
    '''Run one named check; a pending stub always raises CheckFailure.'''
    modules = discover()
    if name in modules:
        modules[name].run()
        return
    pending = pending_entries()
    if name in pending:
        raise CheckFailure('PENDING: %s is registered in pipeline/matrix.yaml (blocks %s) but is not'
                           ' implemented; it stays RED until check_%s.py exists'
                           % (name, ','.join(pending[name].get('blocks', [])), name))
    raise KeyError(name)
