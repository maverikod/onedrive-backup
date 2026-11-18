'''Fake restic binary of the catalog fixtures: snapshots, ls and dump over files in FAKE_RESTIC_STATE.

snapshots.json holds the snapshot list, nodes.json the nodes of any listed snapshot, blob.bin the dump
body. Like restic, snapshots with --tag keeps the snapshots that carry the tag (several --tag options
are alternatives). Every call is appended to calls.log as a JSON list.
'''

from __future__ import annotations

import json
import os
import sys


def main() -> int:
    '''Answer one restic invocation from the fixture state directory.'''
    state = os.environ['FAKE_RESTIC_STATE']
    args = sys.argv[1:]
    with open(os.path.join(state, 'calls.log'), 'a', encoding='utf-8') as log:
        log.write(json.dumps(args) + chr(10))
    if args[:1] == ['snapshots']:
        with open(os.path.join(state, 'snapshots.json'), encoding='utf-8') as fp:
            found = json.load(fp)
        tags = [args[i + 1] for i, item in enumerate(args) if item == '--tag' and i + 1 < len(args)]
        if tags:
            found = [s for s in found if any(set(t.split(',')) <= set(s.get('tags', [])) for t in tags)]
        print(json.dumps(found))
        return 0
    if args[:1] == ['ls']:
        with open(os.path.join(state, 'nodes.json'), encoding='utf-8') as fp:
            nodes = json.load(fp)
        print(json.dumps({'struct_type': 'snapshot', 'id': args[-1]}))
        for node in nodes:
            print(json.dumps(dict(node, struct_type='node')))
        return 0
    if args[:1] == ['dump']:
        with open(os.path.join(state, 'blob.bin'), 'rb') as fp:
            sys.stdout.buffer.write(fp.read())
        return 0
    sys.stderr.write('fake restic: unsupported call ' + ' '.join(args) + chr(10))
    return 2
