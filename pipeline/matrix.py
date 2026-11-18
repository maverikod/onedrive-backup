'''Loader of pipeline/matrix.yaml, the machine-readable snapshot of the project matrix TODO.

The snapshot is written as JSON, which is valid YAML, so the standard library parses it and no
third-party YAML package is needed. Lines that start with # are comments and are ignored.
'''

from __future__ import annotations

import json
from pathlib import Path

MATRIX_FILE = Path(__file__).resolve().with_name('matrix.yaml')


def load(path: Path = MATRIX_FILE) -> dict:
    '''Return the parsed matrix; raise OSError or ValueError when it is missing or malformed.'''
    lines = path.read_text(encoding='utf-8').splitlines()
    data = json.loads('\n'.join(line for line in lines if not line.lstrip().startswith('#')))
    if not isinstance(data, dict):
        raise ValueError('matrix.yaml must hold one mapping')
    return data


def registry(data: dict | None = None) -> dict[str, dict]:
    '''Return the named-check registry of the matrix as {name: entry}.'''
    source = load() if data is None else data
    return {entry['name']: entry for entry in source['checks']}
