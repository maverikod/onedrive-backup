'''Revision 14 model path (matrix TODO 10.22.4.4, 10.22.9 TM14, TM7, TM12; rows M21 and PL22): check model_recipe.

A model reaches the bytes of a backed-up file with JSON-RPC calls only: the client's raw surface (BackupClient.raw_call), no HTTP
download. Small file: backup_search_files with collapse 'file', order_by 'snapshot_time' and fields gives a file_id, then
backup_prepare_download {file_id, inline_max_bytes: 65536} returns the whole file inline: exactly two calls. Larger file:
backup_prepare_download {file_id}, backup_download_chunk until eof, the sha256 compared, backup_delete_export. Text view:
backup_preview {file_id, format: 'text'}. PL22: form A and form C resolve to the bytes of the item (RM2, RM3); a well-formed unknown
file id of the largest snapshot answers 404 within 1 s (TM12). Samples are chosen live (pipeline.rev14bytes).
'''

from __future__ import annotations

import base64
import hashlib
from typing import Any

from pipeline import cmdcases, live, matrix
from pipeline.report import Report
from pipeline.rev14 import Tree14
from pipeline.rev14bytes import BOUND_RESOLVE, Samples, setup

FIELDS = ['name', 'dir', 'file_id', 'snapshot_date', 'size']
SLICE = 262144


def _small(report: Report, tree: Tree14, s: Samples) -> None:
    '''TM14 small file: search -> file_id, prepare inline: two calls, the bytes match the sha256 field.

    Args:
        report: the findings collector.
        tree: the revision 14 state.
        s: the live samples.

    Returns:
        None.
    '''
    start = len(tree.sent)
    kind, code, message, data = tree.send('backup_search_files', {'name_part': '*.txt', 'collapse': 'file', 'order_by': 'snapshot_time',
                                                                  'fields': FIELDS, 'limit': 20})
    rows = [i for i in (data.get('items', []) if kind == 'success' and isinstance(data, dict) else []) if 1 <= int(i.get('size', 0)) <= 65536]
    if kind != 'success' or not rows or sorted(rows[0]) != sorted(FIELDS):
        report.product.append('TM14 step 1 backup_search_files {collapse file, order_by snapshot_time, fields %s}: %s; expected rows with exactly these keys and a file_id'
                              % (FIELDS, cmdcases._brief(kind, code, message, data) if kind != 'success' else '%d small rows' % len(rows)))
    fid = str(rows[0]['file_id']) if rows and rows[0].get('file_id') else s.fid('small')
    kind, code, message, data = tree.send('backup_prepare_download', {'file_id': fid, 'inline_max_bytes': 65536})
    if kind != 'success' or not isinstance(data, dict):
        report.product.append('TM14 step 2 backup_prepare_download {file_id %s, inline_max_bytes 65536}: %s; the two-call path does not exist'
                              % (fid, cmdcases._brief(kind, code, message, data)))
        return
    raw = base64.b64decode(str(data.get('content_b64') or ''))
    if data.get('staged') is not False or hashlib.sha256(raw).hexdigest() != data.get('sha256') or len(raw) != data.get('size_bytes'):
        report.product.append('TM14 step 2: staged %r, %d inline bytes for size_bytes %s; expected the whole file inline with its sha256'
                              % (data.get('staged'), len(raw), data.get('size_bytes')))
    calls = len(tree.sent) - start
    if calls != 2:
        report.product.append('TM14: the small-file path took %d calls, expected exactly 2' % calls)


def _large(report: Report, tree: Tree14, s: Samples) -> None:
    '''TM14 larger file: prepare by file_id, slices of 262144 until eof, the sha256 compared, the export deleted.

    Args:
        report: the findings collector.
        tree: the revision 14 state.
        s: the live samples.

    Returns:
        None.
    '''
    kind, code, message, data = tree.send('backup_prepare_download', {'file_id': s.fid('mid')})
    if kind != 'success' or not isinstance(data, dict) or not data.get('export_id'):
        report.product.append('TM14 large path backup_prepare_download {file_id}: %s' % cmdcases._brief(kind, code, message, data))
        return
    parts: list[bytes] = []
    eof = False
    while not eof and len(parts) < 64:
        reply = tree.send('backup_download_chunk', {'export_id': data['export_id'], 'offset': sum(map(len, parts)), 'limit': SLICE})
        if reply[0] != 'success' or not isinstance(reply[3], dict):
            report.product.append('TM14 large path backup_download_chunk: %s' % cmdcases._brief(*reply))
            return
        parts.append(base64.b64decode(str(reply[3].get('data_b64', ''))))
        eof = bool(reply[3].get('eof'))
    whole = b''.join(parts)
    if hashlib.sha256(whole).hexdigest() != data.get('sha256') or len(whole) != data.get('size_bytes'):
        report.product.append('TM14 large path: %d bytes in %d slices, sha256 differs from the prepare sha256' % (len(whole), len(parts)))
    tree.send('backup_delete_export', {'export_id': data['export_id']})


def _preview(report: Report, tree: Tree14, s: Samples) -> None:
    '''TM14 text view: backup_preview {file_id, format 'text'} returns text.

    Args:
        report: the findings collector.
        tree: the revision 14 state.
        s: the live samples.

    Returns:
        None.
    '''
    kind, code, message, data = tree.send('backup_preview', {'file_id': s.fid('small'), 'format': 'text'})
    if kind != 'success' or not isinstance(data, dict) or not isinstance(data.get('text'), str):
        report.product.append("TM14 text view backup_preview {file_id, format 'text'}: %s; expected text" % cmdcases._brief(kind, code, message, data))


def _resolver(report: Report, tree: Tree14, s: Samples) -> None:
    '''PL22 (TM7, TM12): form A and form C stage the bytes of the item; an unknown file id of the largest snapshot is 404 within 1 s.

    Args:
        report: the findings collector.
        tree: the revision 14 state.
        s: the live samples.

    Returns:
        None.
    '''
    row, ref = s.row('small'), s.stage('small')
    forms: dict[str, dict[str, Any]] = {'tm7_resolve_form_a': {'file_id': s.fid('small')},
                                        'tm7_resolve_form_c': {k: row.get(k) for k in ('snapshot_id', 'site_id', 'drive_id', 'dir', 'name')} | {'copy_index': 0}}
    for cid, params in forms.items():
        reply = tree.send('backup_prepare_download', params)
        got = reply[3] if reply[0] == 'success' and isinstance(reply[3], dict) else {}
        if not got or (got.get('size_bytes'), got.get('sha256'), got.get('filename')) != (ref.get('size_bytes'), ref.get('sha256'), ref.get('filename')):
            report.product.append('PL22 %s backup_prepare_download %s: %s; expected the bytes of the item (size, sha256, filename of form B, RM2)'
                                  % (cid, sorted(params), cmdcases._brief(*reply) if not got else got.get('sha256')))
    reply = tree.send('backup_prepare_download', {'file_id': s.largest()})
    if not (reply[0] == 'command_error' and reply[1] == 404 and tree.seconds <= BOUND_RESOLVE):
        report.product.append('PL22 tm12_resolver_bound: %s in %.2f s; expected 404 File not found in snapshot within %.1f s' % (cmdcases._brief(*reply), tree.seconds, BOUND_RESOLVE))


def model_recipe(name: str) -> None:
    '''TM14 and PL22: the model path through JSON-RPC only; raise CheckFailure on a finding.

    Args:
        name: the named check.

    Returns:
        None.
    '''
    rows = {row['id']: row for row in matrix.load()['rows']}
    report = Report()
    tree: Tree14 | None = None
    try:
        state = live.service_state()
        tree = Tree14(report)
        s = setup(tree)
        if state != 'S1':
            report.state.append('model_recipe: the path needs an S1 service, production answers %s' % state)
        else:
            for step in (_small, _large, _preview, _resolver):
                before = len(report.product) + len(report.state)
                step(report, tree, s)
                report.info.append('%s: %s' % (step.__doc__.split(':')[0] if step.__doc__ else step.__name__, 'GREEN' if len(report.product) + len(report.state) == before else 'RED'))
        report.info.append('rows %s; %d JSON-RPC calls through BackupClient.raw_call, no HTTP download' % (sorted(r for r in rows if r in ('M21', 'PL22')), len(tree.sent)))
    except live.LiveUnreachable as exc:
        report.env.append('model_recipe: not executed, production service unreachable: %s' % exc)
    finally:
        if tree is not None:
            tree.cleanup()
    report.finish(name)
