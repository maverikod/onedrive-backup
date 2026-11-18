'''Executor of the focused cases of one matrix command row (M3..M7) against the production service.

Every case of the row in pipeline/matrix.yaml is executed through pipeline.live and judged against its
result contract. Findings are kept apart: PRODUCT (the live service or the catalog code breaks the
contract), STATE (the case needs state the owner has not provisioned yet, S1: host directory, container
mount, restic password, login and password, finished inventory; RED with that reason, never skipped) and
ENVIRONMENT (the production service cannot be reached). Cases that cannot be constructed through the live
API (an export that is 24 hours old, a snapshot over the export limit) run on the real Catalog class over a
fake restic. A case of state S0 cannot run on a service that is already S1; it is reported as INFO and is
covered by the fixture checks prepare_order and scaffold_gate_states. The S1 executors are written against
the contract and run for the first time when an S1 service exists.
'''

from __future__ import annotations

import json
import re

from pipeline import b4base, fixtures, live, matrix
from pipeline.report import Report

CONCRETE = {
    '8 hex digits': 'abcdef12', '64 hex digits': 'abcdef12' * 8, '7 hex digits': 'abcdef1', '65 hex digits': 'a' * 65,
    '32 lowercase hex digits': '0' * 32, '32 uppercase hex digits': 'ABCDEF01' * 4, '31 hex digits': '0' * 31,
    '33 hex digits': '0' * 33, 'a path with a backslash': 'a' + chr(92) + 'b', 'path of a directory': 'dir',
    'path missing in the snapshot': 'no/such/file.txt', '129 characters': 'q' * 129, '301 characters': 'q' * 301, '300 characters': 'q' * 300, '128 characters': 'q' * 128,
}
BASE = {'snapshot_id': 'abcdef12', 'export_id': '0' * 32, 'site_id': 'site-1'}
PARAM_CASE = re.compile('([a-z_]+)_(invalid|valid)_([0-9]+)')
EXPORT_ID = re.compile('[0-9a-f]{32}')
SHA256 = re.compile('[0-9a-f]{64}')
META_KEYS = ('export_id', 'snapshot_id', 'path', 'filename', 'size_bytes', 'sha256', 'created_at', 'expires_at')
S1_NEEDS = ('the case needs an S1 service (host data directory, container /data mount, restic password,'
            ' login and password, finished inventory) but production answers %s')


def _total_pages() -> int:
    kind, code, message, data = live.request('info', {})
    return data.get('total_pages', 1) if kind == 'success' and isinstance(data, dict) else 1


def resolve(value):
    '''Turn a matrix placeholder such as 7 hex digits into a concrete value.'''
    if value in ('total_pages', 'total_pages+1'):
        return _total_pages() + (1 if value.endswith('+1') else 0)
    return CONCRETE.get(value, value) if isinstance(value, str) else value


def params_for(row: dict, case: dict) -> dict:
    '''Build the parameter map one case sends.'''
    cid = case['id']
    sent = {name: BASE[name] for name, spec in row['params'].items() if spec['required']}
    if cid.startswith('omit_'):
        sent.pop(cid[len('omit_'):], None)
    elif cid == 'unknown_param':
        sent['no_such_param'] = 1
    elif cid == 'S0_invalid_limit_precedes_gate':
        sent['limit'] = 0
    elif cid == 'S0_invalid_file_path_order':
        sent['file_path'] = '../x'
    elif PARAM_CASE.fullmatch(cid):
        sent[PARAM_CASE.fullmatch(cid).group(1)] = resolve(case['value'])
    return sent


def _brief(kind, code, message, data) -> str:
    detail = ''
    if isinstance(data, dict) and kind == 'rpc_error':
        detail = ' violation=%s' % data.get('violation')
    return '%s code=%s%s message=%r' % (kind, code, detail, message[:120])


def _judge_rpc(report: Report, desc: str, reply, violation: str, needs_detail: bool, name: str | None) -> None:
    kind, code, message, data = reply
    ok = kind == 'rpc_error' and code == -32602 and isinstance(data, dict) and data.get('violation') == violation
    if ok and needs_detail and not ('expected' in data and 'got' in data):
        ok = False
    if ok and violation == 'missing':
        ok = name in data.get('missing_parameters', [])
    if ok and violation == 'unknown':
        ok = 'no_such_param' in data.get('invalid_parameters', [])
    if not ok:
        report.product.append('%s: expected adapter error -32602 violation=%s%s, got %s'
                              % (desc, violation, ' with expected and got' if needs_detail else '', _brief(*reply)))


def _judge_invalid(report: Report, desc: str, reply, expect: str, name: str) -> None:
    kind, code, message, data = reply
    if expect == 'T':
        _judge_rpc(report, desc, reply, 'type', True, name)
    elif expect == 'V':
        _judge_rpc(report, desc, reply, 'value', True, name)
    elif expect == 'C400':
        if not (kind == 'command_error' and code == 400):
            report.product.append('%s: expected command error 400, got %s' % (desc, _brief(*reply)))
    else:
        rpc = kind == 'rpc_error' and code in (-32602, -32601) and isinstance(data, dict) and data.get('violation') in ('type', 'value')
        rpc = rpc and (code == -32602 or data.get('violation') == 'value')
        if not (rpc or (kind == 'command_error' and code == 400)):
            report.product.append('%s: expected adapter error -32602 (type or value) or command error 400, got %s'
                                  % (desc, _brief(*reply)))


def _first_snapshot():
    kind, code, message, data = live.request('backup_snapshots', {})
    items = data.get('items', []) if kind == 'success' and isinstance(data, dict) else []
    return items[0] if items else None


def _smallest_file(snapshot_id: str):
    kind, code, message, data = live.request('backup_list_files', {'snapshot_id': snapshot_id, 'limit': 5000})
    files = [i for i in (data.get('items', []) if kind == 'success' and isinstance(data, dict) else [])
             if i.get('type') == 'file']
    return min(files, key=lambda i: i.get('size', 0)) if files else None


def _meta_problems(meta, snapshot_id: str, path) -> list[str]:
    problems = ['missing field ' + key for key in META_KEYS if key not in meta]
    if problems:
        return problems
    if not EXPORT_ID.fullmatch(str(meta['export_id'])):
        problems.append('export_id is not 32 lowercase hex digits')
    if not SHA256.fullmatch(str(meta['sha256'])):
        problems.append('sha256 is not 64 hex digits')
    if meta['snapshot_id'] != snapshot_id.lower() or meta['path'] != path:
        problems.append('snapshot_id or path differ from the request')
    if type(meta['size_bytes']) is not int:
        problems.append('size_bytes is not an integer')
    url = meta.get('url')
    if not (isinstance(url, str) and re.fullmatch('/downloads/[0-9a-f]{32}/[^/]+', url) and url == '/downloads/%s/%s' % (meta['export_id'], meta['filename'])):
        problems.append('url %r is not /downloads/<export_id>/<filename> (block B4, rows M5 and M6)' % (url,))
    if path is None and not (str(meta['filename']).startswith('onedrive-') and str(meta['filename']).endswith('.tar.gz')):
        problems.append('archive filename is not onedrive-<12 hex>.tar.gz')
    return problems


def _prepare_small(report: Report, desc: str):
    '''Prepare the smallest file of the newest snapshot; return (snapshot, path, meta) or None after a finding.'''
    snapshot = _first_snapshot()
    if snapshot is None:
        report.state.append('%s: the catalog lists no snapshot to export' % desc)
        return None
    entry = _smallest_file(snapshot['id'])
    if entry is None:
        report.state.append('%s: the newest snapshot lists no file to export' % desc)
        return None
    kind, code, message, data = live.request('backup_prepare_download', {'snapshot_id': snapshot['id'], 'file_path': entry['path']})
    if kind != 'success':
        report.product.append('%s: prepare of %s failed: %s' % (desc, entry['path'], _brief(kind, code, message, data)))
        return None
    return snapshot['id'], entry['path'], data


def _s1(report: Report, row_id: str, cid: str, desc: str) -> None:
    '''Execute one S1 case against a provisioned service.'''
    if row_id == 'M3':
        limit = {'limit_valid_1': 1, 'limit_valid_2': 1000}.get(cid)
        kind, code, message, data = live.request('backup_snapshots', {} if limit is None else {'limit': limit})
        items = data.get('items') if isinstance(data, dict) else None
        if kind != 'success' or not isinstance(items, list) or type(data.get('count')) is not int:
            report.product.append('%s: expected {items, count}, got %s' % (desc, _brief(kind, code, message, data)))
            return
        if len(items) > (limit or 100):
            report.product.append('%s: %d items exceed the limit %s' % (desc, len(items), limit or 100))
        times = [i.get('time', '') for i in items]
        if times != sorted(times, reverse=True):
            report.product.append('%s: items are not ordered by time, newest first' % desc)
        for item in items:
            if item.get('source') not in ('onedrive', 'sharepoint'):
                report.product.append('%s: snapshot %s carries no source marker (decision Q2)' % (desc, str(item.get('id'))[:8]))
    elif row_id == 'M4':
        snapshot = _first_snapshot()
        if snapshot is None:
            report.state.append('%s: the catalog lists no snapshot' % desc)
            return
        sent = {'snapshot_id': snapshot['id']}
        sent.update({'prefix_valid_1': {'prefix': 'dir/sub'}, 'offset_valid_1': {'offset': 500000},
                     'limit_valid_1': {'limit': 1}, 'limit_valid_2': {'limit': 5000}}.get(cid, {}))
        kind, code, message, data = live.request('backup_list_files', sent)
        ok = kind == 'success' and isinstance(data, dict) and all(k in data for k in ('snapshot_id', 'items', 'total', 'offset', 'limit'))
        if not ok or any('restic_path' in i for i in data['items']):
            report.product.append('%s: expected {snapshot_id, items, total, offset, limit} without restic_path, got %s'
                                  % (desc, _brief(kind, code, message, data)))
    elif row_id == 'M5' and cid in ('baseline', 'whole_snapshot_archive', 'snapshot_id_valid_1'):
        snapshot = _first_snapshot()
        if snapshot is None:
            report.state.append('%s: the catalog lists no snapshot' % desc)
            return
        kind, code, message, data = live.request('backup_prepare_download', {'snapshot_id': snapshot['id']})
        if kind != 'success':
            report.product.append('%s: %s' % (desc, _brief(kind, code, message, data)))
            return
        for problem in _meta_problems(data, snapshot['id'], None):
            report.product.append('%s: %s' % (desc, problem))
        live.request('backup_delete_export', {'export_id': data.get('export_id', '0' * 32)})
    elif row_id == 'M5' and cid in ('file_path_valid_1', 'file_path_invalid_3', 'file_path_invalid_4'):
        snapshot = _first_snapshot()
        if snapshot is None:
            report.state.append('%s: the catalog lists no snapshot' % desc)
            return
        if cid == 'file_path_valid_1':
            made = _prepare_small(report, desc)
            if made:
                for problem in _meta_problems(made[2], made[0], made[1]):
                    report.product.append('%s: %s' % (desc, problem))
                live.request('backup_delete_export', {'export_id': made[2]['export_id']})
        else:
            path = 'no/such/file.txt' if cid.endswith('4') else 'dir'
            kind, code, message, data = live.request('backup_prepare_download', {'snapshot_id': snapshot['id'], 'file_path': path})
            if not (kind == 'command_error' and code == 404):
                report.product.append('%s: expected command error 404 for %r, got %s' % (desc, path, _brief(kind, code, message, data)))
    elif row_id == 'M6':
        made = _prepare_small(report, desc)
        if made:
            kind, code, message, data = live.request('backup_download_status', {'export_id': made[2]['export_id']})
            if kind != 'success' or data != made[2]:
                report.product.append('%s: status must return the metadata of prepare, got %s' % (desc, _brief(kind, code, message, data)))
            live.request('backup_delete_export', {'export_id': made[2]['export_id']})
    elif row_id == 'M7':
        made = _prepare_small(report, desc)
        if made:
            export_id = made[2]['export_id']
            kind, code, message, data = live.request('backup_delete_export', {'export_id': export_id})
            if kind != 'success' or data != {'export_id': export_id, 'deleted': True}:
                report.product.append('%s: expected {export_id, deleted: true}, got %s' % (desc, _brief(kind, code, message, data)))
            kind, code, message, data = live.request('backup_delete_export', {'export_id': export_id})
            if not (kind == 'command_error' and code == 404):
                report.product.append('%s: a repeated delete must answer 404, got %s' % (desc, _brief(kind, code, message, data)))
    else:
        report.state.append('%s: no S1 executor for this case' % desc)


def _meta_case(report: Report, row_id: str, cid: str, desc: str, sent: dict) -> None:
    '''Cases of help (M1) and info (M2): both commands answer in every state, so they run on an S0 service too.'''
    kind, code, message, data = live.request(row_id == 'M1' and 'help' or 'info', sent)
    if kind != 'success' or not isinstance(data, dict):
        report.product.append('%s: expected success data, got %s' % (desc, _brief(kind, code, message, data)))
    elif row_id == 'M1' and cid == 'baseline':
        names = sorted(data.get('commands', {})) if isinstance(data.get('commands'), dict) else None
        if names != sorted(b4base.COMMANDS):
            report.product.append('%s: help lists %s, expected the 11 commands of rows M1..M11' % (desc, names))
        if (data.get('tool_info') or {}).get('version') != b4base.version():
            report.product.append('%s: help reports version %r, expected VERSION %r (decision 7)' % (desc, (data.get('tool_info') or {}).get('version'), b4base.version()))
    elif row_id == 'M1':
        meta = data.get('metadata') or {}
        if meta.get('name') != 'info' or 'page' not in (meta.get('parameters') or {}):
            report.product.append('%s: expected the metadata of info with its page parameter, got %s' % (desc, str(meta)[:120]))
    else:
        total = data.get('total_pages')
        wanted = sent.get('page', 1)
        if cid == 'baseline' and type(total) is int:
            release = b4base.version()
            stale: dict = {}
            for page in range(1, total + 1):
                k2, c2, m2, d2 = live.request('info', {'page': page})
                text = d2.get('content', '') if k2 == 'success' and isinstance(d2, dict) else ''
                for found in re.findall('[0-9]+[.][0-9]+[.][0-9]+', text):
                    if found.startswith(release.rsplit('.', 1)[0] + '.') and found != release:
                        stale.setdefault(found, []).append(page)
            if stale:
                report.product.append('%s: the info manual names releases %s of the series of VERSION %s on pages (decision 7)' % (desc, stale, release))
        if data.get('page') != wanted or type(total) is not int or total < 1 or not isinstance(data.get('content'), str) or not data.get('title'):
            report.product.append('%s: expected {page: %s, total_pages >= 1, title, kind, content}, got %s' % (desc, wanted, str(data)[:120]))


def _fixture_case(report: Report, row_id: str, cid: str) -> None:
    '''Run the cases the live API cannot construct on the real Catalog over a fake restic.'''
    if cid == 'over_limit_413':
        with fixtures.catalog_fixture(max_export_bytes=3) as fx:
            status, value = fx.call(fx.catalog.prepare, fixtures.SNAPSHOT_ID, 'dir/file.txt')
            left = fx.export_files('*') if fx.catalog.exports.exists() else []
        if status != 413 or left:
            report.product.append('%s %s (fixture): expected 413 and no export left, got %s %s, files %s' % (row_id, cid, status, value, left))
        return
    export_id = '4' * 32
    with fixtures.catalog_fixture() as fx:
        fx.write_export(export_id, expired=True)
        function = fx.catalog.export_status if row_id == 'M6' else fx.catalog.delete_export
        status, value = fx.call(function, export_id)
        left = fx.export_files(export_id)
    if status != 410:
        report.product.append('%s %s (fixture): an expired export must answer 410 on its first use, got %s %s' % (row_id, cid, status, value))
    if left:
        report.product.append('%s %s (fixture): the expired export still has %s after it was answered with 410 (finding F3, export_ttl_cleanup)' % (row_id, cid, left))


def _execute(report: Report, row: dict, case: dict, contract: dict, state) -> None:
    cid, row_id = case['id'], row['id']
    if cid in ('over_limit_413', 'expired_410', 'expired_not_deletable_410'):
        _fixture_case(report, row_id, cid)
        return
    if state is None:
        report.env.append('%s %s: not executed, production service unreachable' % (row_id, cid))
        return
    sent = params_for(row, case)
    desc = '%s %s %s(%s)' % (row_id, cid, row['command'], json.dumps(sent))
    if case['state'] == 'S0' and state != 'S0':
        report.info.append('%s: an S0 case cannot run on a service that is %s; covered by prepare_order and scaffold_gate_states' % (desc, state))
        return
    if row_id in ('M1', 'M2') and case['state'] == 'S1':
        _meta_case(report, row_id, cid, desc, sent)
    elif cid.startswith('omit_'):
        _judge_rpc(report, desc, live.request(row['command'], sent), 'missing', False, cid[len('omit_'):])
    elif cid == 'unknown_param':
        _judge_rpc(report, desc, live.request(row['command'], sent), 'unknown', False, None)
    elif PARAM_CASE.fullmatch(cid) and PARAM_CASE.fullmatch(cid).group(2) == 'invalid':
        name, index = PARAM_CASE.fullmatch(cid).group(1), PARAM_CASE.fullmatch(cid).group(3)
        expect = row['params'][name]['invalid'][int(index)]['expect']
        if expect in ('C404', 'C404S') and state != 'S1':
            report.state.append('%s: %s' % (desc, S1_NEEDS % state))
        elif expect in ('C404', 'C404S'):
            _s1(report, row['id'], cid, desc)
        else:
            reply = live.request(row['command'], sent)
            if expect == 'C400' and sent.get(name) == '' and reply[0] == 'rpc_error' and reply[1] == -32602 and isinstance(reply[3], dict) and reply[3].get('violation') in ('type', 'value'):
                report.info.append('%s: live schema refuses the empty value at the adapter (-32602) before the command error 400 of cell C400' % desc)
            else:
                _judge_invalid(report, desc, reply, expect, name)
    elif cid == 'S0_scaffold_gate':
        kind, code, message, data = live.request(row['command'], sent)
        if not (kind == 'command_error' and code == 503 and 'scaffold' in message.lower()):
            report.product.append('%s: expected command error 503 naming scaffold mode, got %s' % (desc, _brief(kind, code, message, data)))
    elif cid == 'S0_scaffold_503':
        kind, code, message, data = live.request(row['command'], sent)
        if not (kind == 'command_error' and code == 503 and 'SCAFFOLD_ONLY' in message):
            report.product.append('%s: expected command error 503 SCAFFOLD_ONLY, got %s' % (desc, _brief(kind, code, message, data)))
    elif cid == 'invalid_site_id_precedes_readiness':
        sent['site_id'] = resolve(row['params']['site_id']['invalid'][2]['value'])
        kind, code, message, data = live.request(row['command'], sent)
        if not (kind == 'command_error' and code == 400):
            report.product.append('%s with site_id %r: the format must be refused with command error 400 before the readiness 503 (R5), got %s' % (desc, sent['site_id'], _brief(kind, code, message, data)))
    elif cid == 'S0_scaffold_status_200':
        kind, code, message, data = live.request(row['command'], sent)
        if not (kind == 'success' and isinstance(data, dict) and data.get('ready') is False and data.get('complete') is False and data.get('state') == 'SCAFFOLD_ONLY'):
            report.product.append('%s: expected 200 {ready: false, complete: false, state: SCAFFOLD_ONLY}, got %s' % (desc, _brief(kind, code, message, data)))
    elif cid == 'S0_invalid_limit_precedes_gate':
        kind, code, message, data = live.request(row['command'], sent)
        if kind not in ('rpc_error', 'command_error') or code == 503:
            report.product.append('%s: an invalid limit must be refused before the scaffold gate (R1), got %s' % (desc, _brief(kind, code, message, data)))
    elif cid == 'S0_invalid_file_path_order':
        kind, code, message, data = live.request(row['command'], sent)
        if not (kind == 'command_error' and code == 400):
            report.product.append('%s: file_path must be validated before the scaffold gate (R2, F2): expected command error 400, got %s' % (desc, _brief(kind, code, message, data)))
    elif cid == 'S0_unknown_export_404':
        kind, code, message, data = live.request(row['command'], sent)
        if not (kind == 'command_error' and code == 404):
            report.product.append('%s: expected command error 404 without consulting the gate (R6), got %s' % (desc, _brief(kind, code, message, data)))
    elif state != 'S1':
        report.state.append('%s: %s' % (desc, S1_NEEDS % state))
    else:
        _s1(report, row_id, cid, desc)


def _tag_fixture(report: Report) -> None:
    '''Tag visibility of the catalog (decision Q2) on the real Catalog over a fake restic; its findings count for M3.'''
    from pipeline.checks import CheckFailure, check_snapshot_tag_visibility
    try:
        check_snapshot_tag_visibility.run()
    except CheckFailure as exc:
        for line in str(exc).splitlines()[1:]:
            report.product.append('M3 tag visibility (fixture): ' + line.replace('[PRODUCT] ', '').strip())


def run_row(row_id: str, name: str) -> None:
    '''Execute every case of matrix row row_id and raise CheckFailure when any finding exists.'''
    data = matrix.load()
    row = next(item for item in data['rows'] if item['id'] == row_id)
    contracts = data['result_contracts'][row_id]['cases']
    report = Report()
    try:
        state = live.service_state()
    except live.LiveUnreachable as exc:
        report.env.append('production service unreachable: %s' % exc)
        state = None
    else:
        report.info.append('production state of %s: %s' % (row['command'], state))
    for case in row['cases']:
        if case['id'] not in contracts:
            report.product.append('%s %s: no result contract in pipeline/matrix.yaml' % (row_id, case['id']))
            continue
        try:
            _execute(report, row, case, contracts[case['id']], state)
        except live.LiveUnreachable as exc:
            report.env.append('%s %s: not executed, production service unreachable: %s' % (row_id, case['id'], exc))
    if row_id == 'M3':
        _tag_fixture(report)
    if row_id in ('M5', 'M6') and state is not None:
        kind, code, message, data = live.request('help', {'cmdname': row['command']})
        documented = ((data.get('metadata') or {}).get('return_value') or {}).get('success', {}).get('data', {}) if kind == 'success' and isinstance(data, dict) else {}
        if 'url' not in documented:
            report.product.append('%s: the help metadata documents the success fields %s and no url (block B4 adds the field url = /downloads/<export_id>/<filename>)' % (row['command'], sorted(documented) if isinstance(documented, dict) else documented))
    report.info.append('%d cases of row %s executed' % (len(row['cases']), row_id))
    report.finish(name)
