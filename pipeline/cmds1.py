'''S1 executors of the matrix rows M8..M11 and of the case snapshot_id_unknown of the rows M4 and M5.

M8 backup_sites_list, M9 backup_libraries_list, M10 backup_discovery_status and M11 backup_download_begin answer
their S1 cases here; cmdcases routes to execute() every S1 case it has no executor of. Every assertion is taken from
the result contract of pipeline/matrix.yaml and nothing is invented: where the matrix contradicts itself or declares
nothing the finding is a MATRIX GAP naming the exact rows (Report.gap), never a product verdict and never a pass.

The case snapshot_id_unknown (revision 6, section 10.13, user decision "Files: the empty list") needs no snapshot: it
sends a well-formed snapshot id that the catalog does not carry. backup_list_files answers success {snapshot_id,
items: [], total: 0, offset: 0, limit: 1000}; backup_prepare_download answers the command error 404 Snapshot not found.
The case S1_not_discovered_503 (state S1 without a finished inventory) cannot be constructed on a service whose inventory
is READY, so it runs on the real SharePointInventory class over an empty temporary directory, like the cases of
cmdcases that run on the real Catalog class.
'''

from __future__ import annotations

import importlib
import json
import sys

from pipeline import b4base, fixtures, live, matrix
from pipeline.report import Report

PAGE_KEYS = ('items', 'total', 'offset', 'limit')
STATUS_ALWAYS = ('complete', 'ready', 'state')
STATUS_SCANNED = ('checked_at', 'coverage', 'errors')
STATUS_STATES = ('READY', 'DISCOVERY_INCOMPLETE', 'NOT_DISCOVERED')
BEGIN_KEYS = ('transfer_id', 'filename', 'size_bytes', 'checksum_algorithm', 'checksum_value', 'compression', 'expires_at', 'transport')


def _cc():
    '''Import cmdcases lazily: it imports this module, so a top-level import would be circular.'''
    from pipeline import cmdcases
    return cmdcases


def _page_problems(data: object, limit: int, offset: int) -> list[str]:
    '''Judge one stable-offset page {items, total, offset, limit}: the echoes, the bound and the length the offset and limit imply.'''
    if not isinstance(data, dict) or sorted(data) != sorted(PAGE_KEYS):
        return ['expected exactly the fields %s, got %s' % (list(PAGE_KEYS), sorted(data) if isinstance(data, dict) else repr(data)[:80])]
    problems = []
    if not isinstance(data['items'], list) or any(not isinstance(item, dict) for item in data['items']):
        problems.append('items is not a list of objects')
    problems += ['%s %r is not an integer' % (key, data[key]) for key in ('total', 'offset', 'limit') if type(data[key]) is not int]
    if problems:
        return problems
    for key, wanted in (('limit', limit), ('offset', offset)):
        if data[key] != wanted:
            problems.append('%s %r differs from the effective %s %r' % (key, data[key], key, wanted))
    wanted_length = max(0, min(limit, data['total'] - offset))
    if len(data['items']) != wanted_length:
        problems.append('%d items for total %d, offset %d and limit %d: a page holds %d' % (len(data['items']), data['total'], offset, limit, wanted_length))
    return problems


def _case_value(row_id: str, cid: str):
    '''Return the resolved matrix value of one case, or None when the case carries none.'''
    row = next(item for item in matrix.load()['rows'] if item['id'] == row_id)
    case = next(item for item in row['cases'] if item['id'] == cid)
    return _cc().resolve(case['value']) if 'value' in case else None


def _call(report: Report, desc: str, command: str, sent: dict):
    '''Call one command; return its data, or None after a PRODUCT finding when it does not succeed.'''
    kind, code, message, data = live.request(command, sent)
    if kind != 'success':
        report.product.append('%s: expected success, got %s' % (desc, _cc()._brief(kind, code, message, data)))
        return None
    return data


def unknown_snapshot(report: Report, row_id: str, desc: str) -> None:
    '''Rows M4 and M5, case snapshot_id_unknown: a well-formed snapshot id absent from the catalog (revision 6, section 10.13).'''
    snapshot_id = b4base.unknown_snapshot_id()
    if row_id == 'M4':
        kind, code, message, data = live.request('backup_list_files', {'snapshot_id': snapshot_id})
        problems = ['expected success, got ' + _cc()._brief(kind, code, message, data)] if kind != 'success' else b4base.unknown_files_problems(data, snapshot_id)
        for problem in problems:
            report.product.append('%s with the unknown snapshot %s: %s (revision 6: success {snapshot_id, items: [], total: 0, offset: 0, limit: 1000})' % (desc, snapshot_id, problem))
        if not problems:
            report.info.append('M4 snapshot_id_unknown conformant: the unknown snapshot %s answers the empty list' % snapshot_id)
        return
    kind, code, message, data = live.request('backup_prepare_download', {'snapshot_id': snapshot_id})
    if kind == 'success' and isinstance(data, dict):
        live.request('backup_delete_export', {'export_id': data.get('export_id', b4base.ZERO_ID)})
    if kind == 'command_error' and code == 404 and 'snapshot not found' in message.lower():
        report.info.append('M5 snapshot_id_unknown conformant: the unknown snapshot %s answers 404 %r' % (snapshot_id, message))
    else:
        report.product.append('%s with the unknown snapshot %s: expected command error 404 Snapshot not found (revision 6), got %s' % (desc, snapshot_id, _cc()._brief(kind, code, message, data)))


def _inventory_not_ready(report: Report, desc: str, call) -> None:
    '''Run the real SharePointInventory over an empty directory: no discovery status file, so the answer is 503 SOURCE_NOT_READY (R5).'''
    for item in (str(fixtures.SRC), str(fixtures.ROOT)):
        if item not in sys.path:
            sys.path.insert(0, item)
    module = importlib.import_module('onedrive_api.sharepoint_inventory')
    work = fixtures._work_dir('b4-inventory-')
    try:
        try:
            call(module.SharePointInventory(work / 'sharepoint'))
        except module.DiscoveryError as exc:
            if (exc.code, exc.status) != ('SOURCE_NOT_READY', 503):
                report.product.append('%s (fixture): expected 503 SOURCE_NOT_READY, got %s %s' % (desc, exc.status, exc.code))
        else:
            report.product.append('%s (fixture): expected 503 SOURCE_NOT_READY on an inventory that was never discovered, got a success' % desc)
    finally:
        fixtures._remove(work)


def _sites(report: Report, row_id: str, cid: str, desc: str) -> None:
    if cid == 'S1_not_discovered_503':
        _inventory_not_ready(report, desc, lambda inventory: inventory.sites())
        return
    sent = {} if cid == 'baseline' else {cid.rsplit('_valid_', 1)[0]: _case_value(row_id, cid)}
    data = _call(report, desc, 'backup_sites_list', sent)
    if data is None:
        return
    for problem in _page_problems(data, sent.get('limit', 100), sent.get('offset', 0)):
        report.product.append('%s: %s' % (desc, problem))
    query = str(sent.get('query', '')).casefold()
    for item in data.get('items', []) if isinstance(data, dict) else []:
        if query and query not in str(item.get('display_name', '')).casefold() and query not in str(item.get('web_url', '')).casefold():
            report.product.append('%s: the site %r matches the query neither in display_name nor in web_url' % (desc, item.get('display_name')))


def _libraries(report: Report, row_id: str, cid: str, desc: str) -> None:
    if cid == 'site_id_invalid_3':
        site = b4base.unknown_site_id()
        kind, code, message, data = live.request('backup_libraries_list', {'site_id': site})
        if not (kind == 'command_error' and code == 404 and 'SITE_NOT_FOUND' in message):
            report.product.append('%s with the unknown site %s: expected command error 404 SITE_NOT_FOUND, got %s' % (desc, site, _cc()._brief(kind, code, message, data)))
        return
    if cid == 'site_id_valid_1':
        site = _case_value(row_id, cid)
        kind, code, message, data = live.request('backup_libraries_list', {'site_id': site})
        if not (kind == 'command_error' and code == 404 and 'SITE_NOT_FOUND' in message):
            report.product.append('%s with the %d-character site id: it passes the validation and the inventory holds no such site, expected command error 404 SITE_NOT_FOUND (revision 7, 10.14 (2) and 10.14.1), got %s' % (desc, len(site), _cc()._brief(kind, code, message, data)))
        return
    site = b4base.baseline_site(report, desc)
    if site is None:
        return
    value = _case_value(row_id, cid)
    sent = {'site_id': site} if cid == 'baseline' else {'site_id': site, cid.rsplit('_valid_', 1)[0]: value}
    data = _call(report, desc, 'backup_libraries_list', sent)
    if data is None:
        return
    for problem in _page_problems(data, sent.get('limit', 100), sent.get('offset', 0)):
        report.product.append('%s: %s' % (desc, problem))
    foreign = [item for item in data.get('items', []) if isinstance(item, dict) and item.get('site_id') != site]
    if foreign:
        report.product.append('%s: %d libraries do not belong to the requested site %s' % (desc, len(foreign), site))


def _names(report: Report) -> list[str]:
    '''Return the site and library names of the live inventory (at least four characters) that the status must not disclose.'''
    names: list[str] = []
    kind, code, message, data = live.request('backup_sites_list', {'limit': 1000})
    for site in data.get('items', []) if kind == 'success' and isinstance(data, dict) else []:
        names.append(str(site.get('display_name', '')))
        k2, c2, m2, d2 = live.request('backup_libraries_list', {'site_id': site.get('site_id', ''), 'limit': 1000})
        for library in d2.get('items', []) if k2 == 'success' and isinstance(d2, dict) else []:
            names += [str(library.get(key, '')) for key in ('name', 'display_name')]
    return [name for name in names if len(name) >= 4]


def _strings(value: object):
    '''Yield every string leaf of a JSON value.'''
    if isinstance(value, str):
        yield value
    elif isinstance(value, dict):
        for item in value.values():
            yield from _strings(item)
    elif isinstance(value, list):
        for item in value:
            yield from _strings(item)


def _status(report: Report, desc: str) -> None:
    data = _call(report, desc, 'backup_discovery_status', {})
    if not isinstance(data, dict):
        return
    state = data.get('state')
    needed = STATUS_ALWAYS + (STATUS_SCANNED if state != 'NOT_DISCOVERED' else ())
    if sorted(data) != sorted(needed) or state not in STATUS_STATES:
        report.product.append('%s: expected the fields %s and a state of %s, got %s' % (desc, list(needed), list(STATUS_STATES), json.dumps(data)[:160]))
        return
    if type(data['ready']) is not bool or type(data['complete']) is not bool or data['ready'] != (state == 'READY'):
        report.product.append('%s: ready %r and complete %r disagree with the state %s (ready is true exactly in READY)' % (desc, data['ready'], data['complete'], state))
    if state == 'READY' and not data['complete']:
        report.product.append('%s: the state READY with complete false' % desc)
    if state != 'NOT_DISCOVERED' and not (isinstance(data['checked_at'], str) and isinstance(data['coverage'], dict) and isinstance(data['errors'], list)):
        report.product.append('%s: checked_at, coverage and errors must be a string, an object and a list' % desc)
    leaked = sorted({name for name in _names(report) for text in _strings(data) if name in text})
    if leaked:
        report.product.append('%s: the status discloses %d site or library names (the contract withholds them)' % (desc, len(leaked)))


def _begin(report: Report, desc: str) -> None:
    made = _cc()._prepare_small(report, desc)
    if not made:
        return
    export_id, meta = made[2]['export_id'], made[2]
    try:
        data = _call(report, desc, 'backup_download_begin', {'export_id': export_id})
        if not isinstance(data, dict):
            return
        missing = [key for key in BEGIN_KEYS if key not in data]
        if missing:
            report.product.append('%s: the result lacks %s' % (desc, missing))
            return
        transport = data['transport']
        if (data['checksum_algorithm'], data['checksum_value'], data['compression']) != ('sha256', meta['sha256'], 'identity'):
            report.product.append('%s: checksum_algorithm %r, checksum_value or compression %r differ from sha256, the export sha256 and identity' % (desc, data['checksum_algorithm'], data['compression']))
        if data['size_bytes'] != meta['size_bytes'] or data['filename'] != meta['filename']:
            report.product.append('%s: size_bytes or filename differ from the export metadata' % desc)
        if not (isinstance(transport, dict) and transport.get('chunk_method') == 'GET' and isinstance(transport.get('chunk_path_template'), str)):
            report.product.append('%s: transport must carry chunk_method GET and a chunk_path_template' % desc)
    finally:
        live.request('backup_delete_export', {'export_id': export_id})


def execute(report: Report, row_id: str, cid: str, desc: str) -> None:
    '''Execute one S1 case of M8..M11, or the case snapshot_id_unknown of M4 and M5.'''
    if cid == 'snapshot_id_unknown':
        unknown_snapshot(report, row_id, desc)
    elif row_id == 'M8':
        _sites(report, row_id, cid, desc)
    elif row_id == 'M9':
        _libraries(report, row_id, cid, desc)
    elif row_id == 'M10' and cid == 'baseline':
        _status(report, desc)
    elif row_id == 'M11' and cid == 'baseline':
        _begin(report, desc)
    else:
        report.state.append('%s: no S1 executor for this case' % desc)
