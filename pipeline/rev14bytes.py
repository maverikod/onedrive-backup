'''Revision 14 BYTES group (matrix TODO 10.22.4, 10.22.6.3, 10.22.6.8, 10.22.9 TM1-TM8, TM11, TM12, TD14): rows M4, M5, M6, M21.

Samples are chosen LIVE from backup_search_files of the newest backup date (the pipeline never writes into a backup): a small text
file (1..65536 bytes), a middle file (150000..250000 bytes) and a png above the 4 MiB chunk cap. Their file_id is the RM3 hash
computed by the check (the 0.3.28 rows carry none). Exports are staged by backup_prepare_download form B (the 0.3.27 form) when a
case needs an export id, and pipeline.rev14.Tree14 deletes every staged export at the end.
'''

from __future__ import annotations

import base64
import hashlib
import re
from typing import Any

from pipeline.rev14 import Case14, ErrorChecks, Reply, Tree14, Validators, edata, file_id

SAMPLES = {'small': (('*.txt', '*.csv', '*.docx'), 1, 65536), 'mid': (('*.pdf', '*.docx'), 150000, 250000),
           'png': (('*.png',), 4194305, 20971520)}
MISSING = 'no-such-file-rev14.txt'
CHUNK_LIMIT = 65536
BOUND_RESOLVE = 1.0
BOUND_SLICE = 1.0
SHA = re.compile('[0-9a-f]{64}')


class Samples:
    '''The live samples and the exports staged for them.

    Attributes:
        tree: the revision 14 state.
        rows: search row by sample kind.
        staged: prepare result by sample kind or 'archive'.
    '''

    def __init__(self, tree: Tree14) -> None:
        '''Keep the state; nothing is read before a placeholder needs it.'''
        self.tree = tree
        self.rows: dict[str, dict] = {}
        self.staged: dict[str, dict] = {}

    def row(self, kind: str) -> dict:
        '''Return the search row of a sample kind, found once on the newest backup date; {} after a STATE finding.

        Args:
            kind: small, mid or png.

        Returns:
            The row.
        '''
        if kind not in self.rows:
            patterns, low, high = SAMPLES[kind]
            found: dict = {}
            for pattern in patterns:
                kind_, _, _, data = self.tree.send('backup_search_files', {'name_part': pattern, 'dates': self.tree.days[-1:], 'limit': 500})
                items = [i for i in (data.get('items', []) if kind_ == 'success' and isinstance(data, dict) else [])
                         if low <= int(i.get('size', -1)) <= high and not i.get('is_copy')]
                if items:
                    found = min(items, key=lambda i: int(i['size']))
                    break
            if not found:
                self.tree.report.state.append('sample %s: no row of %s between %d and %d bytes on %s' % (kind, patterns, low, high, self.tree.days[-1:]))
            self.rows[kind] = found
        return self.rows[kind]

    def fid(self, kind: str) -> str:
        '''Return the file_id of a sample: the row's own, else the RM3 hash computed by the check.

        Args:
            kind: small, mid or png.

        Returns:
            The file id.
        '''
        row = self.row(kind)
        return str(row.get('file_id') or file_id(str(row.get('snapshot_id', '0' * 8)), str(row.get('file_path', ''))))

    def stage(self, kind: str) -> dict:
        '''Stage a sample once by form B (or the archive of the ДЕНЬГИ snapshot of 2026-11-21) and return the prepare result.

        Args:
            kind: small, mid, png or archive.

        Returns:
            The result data, {} after a finding.
        '''
        if kind not in self.staged:
            row = self.row(kind) if kind != 'archive' else {}
            params = {'snapshot_id': self.tree.listing_id} if kind == 'archive' else {'snapshot_id': row.get('snapshot_id'), 'file_path': row.get('file_path')}
            reply = self.tree.send('backup_prepare_download', params)
            self.staged[kind] = reply[3] if reply[0] == 'success' and isinstance(reply[3], dict) else {}
            if not self.staged[kind]:
                self.tree.report.product.append('staging %s by backup_prepare_download %s failed: %s %s %s' % (kind, params, reply[0], reply[1], reply[2][:100]))
        return self.staged[kind]

    def largest(self) -> str:
        '''Return a well-formed unknown file id in the newest snapshot of the library with the most rows (TM12).

        Returns:
            The file id.
        '''
        best, snap = -1, '0' * 8
        for drive in self.tree.libraries:
            data = self.tree.send('backup_search_files', {'site_id': self.tree.site, 'drive_id': drive, 'recursive': True, 'dates': self.tree.days[-1:], 'limit': 1})[3]
            items = data.get('items', []) if isinstance(data, dict) else []
            if items and int(data.get('total', 0)) > best:
                best, snap = int(data['total']), str(items[0]['snapshot_id'])
        return snap[:8] + '.' + 'f' * 24


def setup(tree: Tree14) -> Samples:
    '''Register the lazy placeholders of the BYTES cases on the state.

    Args:
        tree: the revision 14 state.

    Returns:
        The samples object.
    '''
    s = Samples(tree)
    small = s.row
    tree.lazy.update({
        '$FILE_ID': lambda: s.fid('small'), '$FILE_ID_SMALL': lambda: s.fid('small'), '$FILE_ID_LARGE': lambda: s.fid('mid'),
        '$SNAPSHOT': lambda: small('small').get('snapshot_id', 'snapshot-none'), '$FILE_PATH': lambda: small('small').get('file_path', ''),
        '$DRIVE': lambda: small('small').get('drive_id', ''), '$DIR': lambda: small('small').get('dir', ''),
        '$NAME': lambda: small('small').get('name', ''), '$NAME_MISSING': lambda: MISSING,
        '$PATH_MISSING': lambda: str(small('small').get('file_path', '')).rsplit('/', 1)[0] + '/' + MISSING,
        '$FILE_ID_UNKNOWN': lambda: s.fid('small')[:9] + ('0' * 24 if not s.fid('small').endswith('0' * 24) else 'f' * 24),
        '$FILE_ID_UNKNOWN_LARGEST': s.largest, '$EXPORT_ID': lambda: s.stage('mid').get('export_id', '0' * 32),
        '$TOTAL_SIZE': lambda: int(small('mid').get('size', 0)), '$TOTAL_SIZE+1': lambda: int(small('mid').get('size', 0)) + 1,
        '$EXPORT_ID_PNG_8MB': lambda: s.stage('png').get('export_id', '0' * 32),
        '$EXPORT_ID_FILE': lambda: s.stage('small').get('export_id', '0' * 32),
        '$EXPORT_ID_ARCHIVE': lambda: s.stage('archive').get('export_id', '0' * 32),
    })
    setattr(tree, 'samples', s)
    return s


def samples(case: Case14) -> Samples:
    '''Return the samples object of the run.

    Args:
        case: the executed case.

    Returns:
        The samples.
    '''
    return getattr(case.tree14, 'samples')


def _staged(case: Case14, kind: str) -> None:
    '''TM1/TM2: a staged single file: file_id, kind 'file', staged true, how_to_fetch naming backup_download_chunk, RM2 equality.'''
    s = samples(case)
    row = s.row(kind)
    data = case.data
    want = {'file_id': s.fid(kind), 'kind': 'file', 'staged': True, 'content_b64': None, 'size_bytes': row.get('size')}
    got = {key: data.get(key, '<absent>') for key in want}
    if got != want or 'backup_download_chunk' not in str(data.get('how_to_fetch', '')):
        case.bad('result %s, expected %s and how_to_fetch naming backup_download_chunk (10.22.4.2)' % (got, want))
    ref = data if case.cid == 'tm1_form_b' else s.stage(kind)
    if ref and (ref.get('sha256'), ref.get('filename')) != (data.get('sha256'), data.get('filename')):
        case.bad('sha256/filename %s differ from the form B staging %s (RM2)' % ((data.get('sha256'), data.get('filename')), (ref.get('sha256'), ref.get('filename'))))


def _stage_small(case: Case14) -> None:
    '''TM1 forms A, B, C of the small sample (and TM2 above the inline limit for the middle sample).'''
    _staged(case, 'mid' if case.cid == 'tm2_inline_large' else 'small')


def _stage_archive(case: Case14) -> None:
    '''TM1: the archive form still stages the tar.gz of the snapshot, kind 'snapshot', file_id null.'''
    data = case.data
    if (data.get('kind'), data.get('file_id', '<absent>'), data.get('staged')) != ('snapshot', None, True) or not str(data.get('filename', '')).endswith('.tar.gz'):
        case.bad("result kind %r, file_id %r, staged %r, filename %r; expected 'snapshot', null, true and a .tar.gz"
                 % (data.get('kind', '<absent>'), data.get('file_id', '<absent>'), data.get('staged', '<absent>'), data.get('filename')))


def _inline(case: Case14) -> None:
    '''TM2: a small file inline: staged false, no export, content_b64 decodes to size_bytes bytes with the sha256 field (RM8).'''
    data = case.data
    raw: Any = None
    try:
        raw = base64.b64decode(str(data.get('content_b64')), validate=True)
    except ValueError:
        raw = None
    nulls = {key: data.get(key, '<absent>') for key in ('export_id', 'url', 'expires_at')}
    good = data.get('staged') is False and set(nulls.values()) == {None} and bool(data.get('how_to_fetch'))
    good = good and raw is not None and len(raw) == data.get('size_bytes') == samples(case).row('small').get('size')
    if not good or hashlib.sha256(raw or b'').hexdigest() != data.get('sha256'):
        case.bad('staged %r, %s, how_to_fetch %r, content of %s bytes; expected staged false, nulls, the whole file with the sha256 field'
                 % (data.get('staged', '<absent>'), nulls, data.get('how_to_fetch'), len(raw) if raw is not None else None))


def _nowrite(case: Case14) -> None:
    '''TM11/TM4: the call leaves snapshots, index counts, rows per date and the schedule revision unchanged; no export staged.'''
    tree = case.tree14
    after = tree.state()
    if after != tree.before:
        case.bad('the state changed: before %s, after %s' % (str(tree.before)[:160], str(after)[:160]))
    if case.data.get('export_id'):
        case.bad('an export %s was staged by an inline read' % case.data.get('export_id'))


def _status_kind(case: Case14) -> None:
    '''RM8/TM1: backup_download_status of a single-file export has kind 'file' and its file_id; of an archive kind 'snapshot'.'''
    s = samples(case)
    kind = 'archive' if case.cid == 'rm8_kind_snapshot' else 'small'
    want: dict[str, Any] = {'kind': 'snapshot', 'file_id': None} if kind == 'archive' else {'kind': 'file', 'file_id': s.fid('small')}
    want['sha256'] = s.staged.get(kind, {}).get('sha256')
    got = {key: case.data.get(key, '<absent>') for key in want}
    if got != want:
        case.bad('status %s, expected %s (10.22.4.2 M6)' % (got, want))


def _files_fid(case: Case14) -> None:
    '''TM8: every file node carries the RM3 file_id of its path, no directory does; warnings [] is present.'''
    items = case.data.get('items', [])
    snapshot = str(case.params['snapshot_id'])
    wrong = [i.get('path') for i in items if i.get('type') == 'file' and i.get('file_id') != file_id(snapshot, str(i.get('path')))]
    dirs = [i.get('path') for i in items if i.get('type') != 'file' and 'file_id' in i]
    if wrong or dirs or case.data.get('warnings') != []:
        case.bad('%d file node(s) without the RM3 file_id (e.g. %s), %d directory node(s) with one, warnings %r (10.22.6.3)'
                 % (len(wrong), str(wrong[:1])[:120], len(dirs), case.data.get('warnings', '<absent>')))


def _files_warn(case: Case14) -> None:
    '''TD14: an unknown well-formed snapshot keeps the empty success of 10.13 (1) and adds warnings [UNKNOWN_SNAPSHOT_ID].'''
    warnings = case.data.get('warnings')
    value = case.params['snapshot_id']
    first = warnings[0] if isinstance(warnings, list) and warnings and isinstance(warnings[0], dict) else {}
    if (case.data.get('items'), case.data.get('total')) != ([], 0) or not {'code': 'UNKNOWN_SNAPSHOT_ID', 'field': 'snapshot_id', 'value': value}.items() <= first.items():
        case.bad('items %s, total %s, warnings %r; expected [], 0 and [{code UNKNOWN_SNAPSHOT_ID, field snapshot_id, value %r, hint}]'
                 % (str(case.data.get('items'))[:60], case.data.get('total'), warnings, value))


def _slice_ok(case: Case14, data: dict, offset: int) -> bool:
    '''Judge one M21 slice: length, eof, sha256 of the slice, the whole sha256 and total size of the export (10.22.6.8).

    Args:
        case: the executed case.
        data: the slice.
        offset: the requested offset.

    Returns:
        True when conformant.
    '''
    s = samples(case)
    staged = s.staged.get('mid', {})
    try:
        raw = base64.b64decode(str(data.get('data_b64')), validate=True)
    except ValueError:
        raw = b''
    total = data.get('total_size')
    good = data.get('encoding') == 'base64' and data.get('offset') == offset and data.get('length') == len(raw)
    good = good and total == staged.get('size_bytes') and data.get('sha256') == staged.get('sha256') and data.get('eof') == (offset + len(raw) == total)
    good = good and data.get('chunk_sha256') == hashlib.sha256(raw).hexdigest() and len(raw) <= int(case.params.get('limit', CHUNK_LIMIT))
    if not good:
        case.bad('slice %s does not match the staged export (size %s, sha256 %s)' % ({k: v for k, v in data.items() if k != 'data_b64'}, staged.get('size_bytes'), str(staged.get('sha256'))[:12]))
    return good


def _chunk(case: Case14) -> None:
    '''TM4: one slice at offset 0.'''
    _slice_ok(case, case.data, 0)


def _chunk_all(case: Case14) -> None:
    '''TM4: slices of 65536 until eof reassemble the staged payload (RM8); M6 reports the same sha256.'''
    parts, offset, data = [case.data], 0, case.data
    while _slice_ok(case, data, offset) and not data.get('eof'):
        offset += int(data['length'])
        data = case.need('backup_download_chunk', {'export_id': case.params['export_id'], 'offset': offset, 'limit': CHUNK_LIMIT}) or {}
        parts.append(data)
    whole = b''.join(base64.b64decode(str(p.get('data_b64', ''))) for p in parts)
    status = case.need('backup_download_status', {'export_id': case.params['export_id']}) or {}
    staged = samples(case).staged.get('mid', {})
    if hashlib.sha256(whole).hexdigest() != staged.get('sha256') or status.get('sha256') != staged.get('sha256') or len(whole) != staged.get('size_bytes'):
        case.bad('the %d slices give %d bytes, sha256 %s; expected %s bytes, the M5 and M6 sha256 %s' % (len(parts), len(whole), hashlib.sha256(whole).hexdigest()[:12], staged.get('size_bytes'), str(staged.get('sha256'))[:12]))


def _chunk_eof(case: Case14) -> None:
    '''TM4: offset == total_size answers length 0, eof true, data_b64 ''.'''
    if (case.data.get('length'), case.data.get('eof'), case.data.get('data_b64')) != (0, True, ''):
        case.bad('expected length 0, eof true and data_b64 empty, got %s' % {k: case.data.get(k) for k in ('length', 'eof', 'total_size')})


def _chunk_nowrite(case: Case14) -> None:
    '''TM4/TM11: slices change nothing: the export expiry and the observable state are unchanged.'''
    tree = case.tree14
    before = samples(case).staged.get('mid', {}).get('expires_at')
    status = case.need('backup_download_status', {'export_id': case.params['export_id']}) or {}
    if status.get('expires_at') != before or tree.state() != tree.before:
        case.bad('expires_at %s -> %s or the state changed (RM8)' % (before, status.get('expires_at')))


def _chunk_latency(case: Case14) -> None:
    '''TM12: one slice of 262144 within 1 s.'''
    case.report.info.append('TM12 latency: backup_download_chunk %.2fs' % case.tree14.seconds)
    if case.tree14.seconds > BOUND_SLICE:
        case.bad('one slice answered in %.2f s, bound %.1f s (TM12)' % (case.tree14.seconds, BOUND_SLICE))


def _hint(*tokens: str) -> Any:
    '''Return the predicate: error.data.hint is present and names every token (RM4, RM6).

    Args:
        tokens: the words the hint must contain.

    Returns:
        The predicate.
    '''
    def check(reply: Reply, tree: Tree14) -> str:
        '''Judge error.data.hint.

        Args:
            reply: the classified error reply.
            tree: the revision 14 state.

        Returns:
            '' or the finding.
        '''
        hint = str(edata(reply).get('hint') or '')
        return '' if hint and all(token in hint for token in tokens) else 'error.data %s has no hint naming %s (RM4, RM6)' % (str(edata(reply))[:140], list(tokens))
    return check


def _address(reply: Reply, tree: Tree14) -> str:
    '''RM1: INVALID_FILE_ADDRESS lists the three forms, the supplied names and a hint.'''
    data = edata(reply)
    return '' if len(data.get('forms') or []) == 3 and data.get('got') and data.get('hint') else 'error.data %s lacks {forms (3), got, hint} (RM1)' % str(data)[:140]


def _pattern(reply: Reply, tree: Tree14) -> str:
    '''RM6: INVALID_FILE_ID names the expected pattern.'''
    data = edata(reply)
    return '' if '[0-9a-f]{8}' in str(data.get('expected')) and data.get('field') == 'file_id' else 'error.data %s lacks field file_id and the expected pattern (RM6)' % str(data)[:140]


def _name(reply: Reply, tree: Tree14) -> str:
    '''RM6: INVALID_FILE_NAME names the field, the value, the expectation and a hint.'''
    data = edata(reply)
    return '' if data.get('field') == 'name' and data.get('value') == '../x' and data.get('expected') and data.get('hint') else 'error.data %s lacks {field name, value, expected, hint} (RM6)' % str(data)[:140]


def _checked(reply: Reply, tree: Tree14) -> str:
    '''TM6: a form C miss names the checked dir, name and copy_index.'''
    checked = edata(reply).get('checked') or {}
    return '' if isinstance(checked, dict) and {'dir', 'name', 'copy_index'} <= set(checked) else 'error.data %s lacks checked {dir, name, copy_index} (TM6)' % str(edata(reply))[:140]


def _resolve_bound(reply: Reply, tree: Tree14) -> str:
    '''TM12: the unknown file id of the largest snapshot answers 404 within 1 s.'''
    tree.report.info.append('TM12 latency: backup_prepare_download unknown file_id %.2fs' % tree.seconds)
    return '' if tree.seconds <= BOUND_RESOLVE else 'answered in %.2f s, bound %.1f s (TM12, O-MD2 A)' % (tree.seconds, BOUND_RESOLVE)


def _offset(reply: Reply, tree: Tree14) -> str:
    '''TM4: INVALID_OFFSET names the total size.'''
    want = getattr(tree, 'samples').row('mid').get('size')
    return '' if edata(reply).get('total_size') == want else 'error.data %s lacks total_size %s (TM4)' % (str(edata(reply))[:140], want)


def _unknown_export(reply: Reply, tree: Tree14) -> str:
    '''TM4: a well-formed unknown export id answers 404 with the M6 text.'''
    return '' if 'Unknown export identifier' in reply[2] else 'message %r, expected the M6 text Unknown export identifier' % reply[2][:100]


PREPARE_VALIDATORS: Validators = {'stage_a': _stage_small, 'stage_b': _stage_small, 'stage_c': _stage_small, 'stage_archive': _stage_archive,
                                  'inline': _inline, 'nowrite': _nowrite}
PREPARE_ERRORS: ErrorChecks = {
    'tm3_file_id_bad': _pattern, 'tm3_file_id_with_snapshot': _address, 'tm3_snapshot_alone_mixed': _address, 'tm3_file_id_with_path': _address,
    'tm3_form_c_no_name': _address, 'tm3_name_dotdot': _name, 'tm3_unknown_file_id': _hint('backup_search_files'),
    'tm3_path_without_prefix': _hint('backup_search_files', 'sharepoint/'), 'tm6_hint_not_found': _hint('backup_search_files', 'sharepoint/'),
    'tm6_form_c_checked': _checked, 'tm12_latency': _resolve_bound,
}
STATUS_VALIDATORS: Validators = {'status_kind': _status_kind}
FILES_VALIDATORS: Validators = {'files_fid': _files_fid, 'files_warn': _files_warn}
CHUNK_VALIDATORS: Validators = {'chunk': _chunk, 'chunk_all': _chunk_all, 'chunk_eof': _chunk_eof, 'nowrite': _chunk_nowrite, 'latency': _chunk_latency}
CHUNK_ERRORS: ErrorChecks = {'tm4_offset_beyond': _offset, 'tm4_unknown_export': _unknown_export, 'tm5_too_large': _hint()}
