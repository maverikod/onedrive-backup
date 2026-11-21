'''Revision 11 live executors (matrix TODO 10.19, block FILTER-REV11): rows M12-M14, PL14 and the client and odbcli checks of the three commands.

Every case of a command row is executed through pipeline.live with the parameters the matrix names and judged against its result contract
(`expect`: rpc:<violation>, cmd:<code>:<token> or ok:<validator>). Findings are PRODUCT, STATE or ENVIRONMENT as in pipeline.report.
'''

from __future__ import annotations

import inspect
import json
import re
import unicodedata
from datetime import datetime
from typing import Any, Callable
from zoneinfo import ZoneInfo

from pipeline import b4cli, b4client, cmdcases, live, matrix
from pipeline.report import Report

TZ = 'Europe/Kyiv'
KEY_SEGMENT = re.compile('[0-9a-f]{64}')
ITEM_KEYS = ['dir', 'file_path', 'is_copy', 'copy_index', 'library_name', 'mtime', 'name', 'site_id', 'site_name', 'size', 'snapshot_id', 'snapshot_time']
INDEX_KEYS = ['complete', 'snapshots_indexed', 'snapshots_total']
FO_KEYS = ['sites', 'dates', 'timezone', 'index']
CLIENT_METHODS = {'filter_options': ['site_ids'], 'search_files': ['site_ids', 'dates', 'name_part', 'limit', 'offset'],
                  'suggest_names': ['text', 'site_ids', 'dates', 'limit']}
BASELINE: dict[str, dict[str, Any]] = {'backup_filter_options': {}, 'backup_search_files': {'name_part': 'акт*', 'limit': 5},
                                       'backup_suggest_names': {'text': 'акт'}}


def key(text: str) -> str:
    '''Return casefold(NFC(text)), the name key of 10.17.2 and 10.19.3.

    Args:
        text: a name or a pattern.

    Returns:
        The key.
    '''
    return unicodedata.normalize('NFC', text).casefold()


def matcher(text: str) -> Callable[[str], bool]:
    '''Return the name matcher of 10.19.3: no unescaped star is a contains match, any star makes an anchored pattern.

    Args:
        text: the name part as typed.

    Returns:
        A function that tells whether a shown name matches.
    '''
    text, parts, wild, index = key(text.strip()), [], False, 0
    while index < len(text):
        char = text[index]
        if char == chr(92) and text[index + 1:index + 2] in ('*', chr(92)):
            parts.append(re.escape(text[index + 1]))
            index += 1
        elif char == '*':
            wild = True
            parts.append('.*')
        else:
            parts.append(re.escape(char))
        index += 1
    regex = re.compile(''.join(parts), re.S)
    return (lambda name: bool(regex.fullmatch(key(name)))) if wild else (lambda name: bool(regex.search(key(name))))


class Context:
    '''Runtime placeholders of the cases.

    Attributes:
        snapshots: the live snapshots.
        days: the backup dates of the snapshots in the service time zone, oldest first.
        site: the id of the first site that has libraries, or None.
    '''

    def __init__(self) -> None:
        '''Read the live snapshots and sites once.'''
        kind, _, _, data = live.request('backup_snapshots', {'limit': 1000})
        self.snapshots: list[dict] = list(data.get('items', [])) if kind == 'success' and isinstance(data, dict) else []
        zone = ZoneInfo(TZ)
        self.days = sorted({datetime.fromisoformat(str(i.get('time')).replace('Z', '+00:00')).astimezone(zone).date().isoformat() for i in self.snapshots})
        self.site: str | None = None
        kind, _, _, sites = live.request('backup_sites_list', {'limit': 1000})
        for item in sites.get('items', []) if kind == 'success' and isinstance(sites, dict) else []:
            if item.get('library_count') and self.site is None:
                self.site = item.get('site_id')

    def resolve(self, value: Any) -> Any:
        '''Replace the placeholders $SITE, $NEWEST, $OLD and $129 inside a case parameter map.

        Args:
            value: a parameter value, list or map.

        Returns:
            The value with the placeholders replaced.
        '''
        if isinstance(value, list):
            return [self.resolve(item) for item in value]
        if isinstance(value, dict):
            return {name: self.resolve(item) for name, item in value.items()}
        table = {'$SITE': self.site or 'site-none', '$NEWEST': self.days[-1] if self.days else '2000-01-01',
                 '$OLD': self.days[0] if self.days else '2000-01-01', '$129': 'q' * 129}
        return table.get(value, value) if isinstance(value, str) else value


class Case:
    '''One executed case with a successful reply.

    Attributes:
        report: the findings collector.
        desc: the case description for findings.
        data: the data of the success reply.
        ctx: the runtime placeholders.
        params: the parameter map that was sent.
    '''

    def __init__(self, report: Report, desc: str, data: dict, ctx: Context, params: dict) -> None:
        '''Keep the case parts.'''
        self.report, self.desc, self.data, self.ctx, self.params = report, desc, data, ctx, params

    def bad(self, text: str) -> None:
        '''PRODUCT finding with the case description.

        Args:
            text: what differs.

        Returns:
            None.
        '''
        self.report.product.append('%s: %s' % (self.desc, text))

    def fields(self, keys: list[str]) -> bool:
        '''PRODUCT finding unless the result holds exactly the keys and a well-formed index when it names one.

        Args:
            keys: the exact field names.

        Returns:
            True when the shape is right.
        '''
        index = self.data.get('index')
        if sorted(self.data) != sorted(keys):
            self.bad('expected exactly the fields %s, got %s' % (keys, sorted(self.data)))
        elif 'index' in keys and not (isinstance(index, dict) and sorted(index) == INDEX_KEYS):
            self.bad('index must be an object with %s, got %s' % (INDEX_KEYS, index))
        else:
            return True
        return False


def _call(command: str, params: dict) -> dict:
    '''Return the data of a successful command call, or an empty map.

    Args:
        command: the service command.
        params: its parameters.

    Returns:
        The data map, empty after a failure.
    '''
    kind, _, _, data = live.request(command, params)
    return data if kind == 'success' and isinstance(data, dict) else {}


def _fo_base(case: Case) -> None:
    '''C1: sites with snapshots, dates newest first, the service time zone; counts equal the live snapshots once the index is complete.

    Args:
        case: the executed case.

    Returns:
        None.
    '''
    data = case.data
    if not case.fields(FO_KEYS):
        return
    if data['timezone'] != TZ:
        case.bad('timezone %r, expected %s' % (data['timezone'], TZ))
    sites, dates = data['sites'], data['dates']
    if any(sorted(item) != ['last_snapshot_time', 'name', 'site_id', 'snapshot_count'] or item['snapshot_count'] < 1 for item in sites):
        case.bad('a site entry lacks {site_id, name, snapshot_count >= 1, last_snapshot_time}')
    if [key(item['name']) for item in sites] != sorted(key(item['name']) for item in sites):
        case.bad('sites are not ordered by name key')
    day = [item.get('date') for item in dates]
    if day != sorted(day, reverse=True) or any(sorted(item) != ['date', 'snapshot_count'] for item in dates):
        case.bad('dates are not {date, snapshot_count} newest first')
    if data['index']['complete'] and (sum(item['snapshot_count'] for item in sites) != len(case.ctx.snapshots) or set(day) != set(case.ctx.days)):
        case.bad('counts %s and dates %s differ from the %d live snapshots on %s' % ([i['snapshot_count'] for i in sites], day, len(case.ctx.snapshots), case.ctx.days))


def _fo_site(case: Case) -> None:
    '''C2: the dates of one ticked site are a non-empty subset of the dates of all sites.

    Args:
        case: the executed case.

    Returns:
        None.
    '''
    if case.fields(FO_KEYS):
        found = {item.get('date') for item in case.data['dates']}
        if not found or not found <= set(case.ctx.days):
            case.bad('dates %s are not a non-empty subset of %s' % (sorted(found), case.ctx.days))


def _fo_unknown(case: Case) -> None:
    '''C3: an unknown well-formed site id hides no site and gives no date.

    Args:
        case: the executed case.

    Returns:
        None.
    '''
    if case.fields(FO_KEYS) and (case.data['dates'] != [] or not case.data['sites']):
        case.bad('expected dates [] and the sites of C1, got %d sites and dates %s' % (len(case.data['sites']), case.data['dates']))


def _nowrite(case: Case) -> None:
    '''C10: the call leaves the snapshot list unchanged.

    Args:
        case: the executed case.

    Returns:
        None.
    '''
    after = _call('backup_snapshots', {'limit': 1000}).get('items', [])
    if [item.get('id') for item in after] != [item.get('id') for item in case.ctx.snapshots]:
        case.bad('the snapshot list changed during the call')


def _page(case: Case, limit: int, offset: int) -> bool:
    '''Judge one search page: fields, echoes, bound, item shape, no identifier fragment, order.

    Args:
        case: the executed case.
        limit: the effective limit.
        offset: the effective offset.

    Returns:
        True when the page is conformant.
    '''
    data = case.data
    if not case.fields(['items', 'total', 'offset', 'limit', 'timezone', 'index']):
        return False
    before = len(case.report.product)
    if (data['limit'], data['offset']) != (limit, offset) or len(data['items']) > limit or data['total'] < len(data['items']):
        case.bad('limit/offset echo %s/%s or %d items for total %s, expected %s/%s' % (data['limit'], data['offset'], len(data['items']), data['total'], limit, offset))
    for item in data['items']:
        text = json.dumps([item.get('name'), item.get('dir'), item.get('site_name'), item.get('library_name')], ensure_ascii=False)
        if sorted(item) != ITEM_KEYS or '.dup-' in text or 'sharepoint/' in text or KEY_SEGMENT.search(text):
            case.bad('item %s has other fields than %s or a key, sharepoint/ or .dup- fragment in a shown value' % (str(item)[:100], ITEM_KEYS))
            break
    order = [(key(i['name']), [-ord(c) for c in i['snapshot_time']]) for i in data['items']]
    if order != sorted(order):
        case.bad('items are not ordered by name key, then snapshot_time newest first')
    return len(case.report.product) == before


def _s_default(case: Case) -> None:
    '''An unfiltered page: limit 100, offset 0, shape and order.

    Args:
        case: the executed case.

    Returns:
        None.
    '''
    _page(case, 100, 0)


def _s_dates(case: Case) -> None:
    '''C4: every row of the newest date is a snapshot of that date in the service time zone.

    Args:
        case: the executed case.

    Returns:
        None.
    '''
    if _page(case, 100, 0):
        zone = ZoneInfo(TZ)
        days = {datetime.fromisoformat(i['snapshot_time'].replace('Z', '+00:00')).astimezone(zone).date().isoformat() for i in case.data['items']}
        if not days <= set(case.params['dates']) or not case.data['items']:
            case.bad('rows on dates %s and %d items, expected only %s and at least one row' % (sorted(days), len(case.data['items']), case.params['dates']))


def _s_case(case: Case) -> None:
    '''C5: the case, a lower-case, an upper-case and a decomposed spelling give identical rows.

    Args:
        case: the executed case.

    Returns:
        None.
    '''
    base = json.dumps(case.data.get('items'))
    for text in ('акт', 'АКТ', unicodedata.normalize('NFD', case.params['name_part'])):
        if json.dumps(_call('backup_search_files', {'name_part': text, 'limit': case.params['limit']}).get('items')) != base:
            case.bad('name_part %r gives other rows than %r' % (text, case.params['name_part']))


def _s_glob(case: Case) -> None:
    '''C6: with a star the pattern is anchored: every name ends with .pdf.

    Args:
        case: the executed case.

    Returns:
        None.
    '''
    if _page(case, 100, 0) and any(not key(i['name']).endswith('.pdf') for i in case.data['items']):
        case.bad('a name does not end with .pdf')


def _s_contains(case: Case) -> None:
    '''C6: without a star the text is a contains match and finds at least the names of the anchored pattern.

    Args:
        case: the executed case.

    Returns:
        None.
    '''
    other = _call('backup_search_files', {'name_part': '*.pdf'}).get('total', 0)
    if _page(case, 100, 0) and (case.data['total'] < other or any('pdf' not in key(i['name']) for i in case.data['items'])):
        case.bad('total %s below the %s of *.pdf or a name without pdf' % (case.data['total'], other))


def _s_versions(case: Case) -> None:
    '''C7: a file present in both runs appears once per snapshot, newest first.

    Args:
        case: the executed case.

    Returns:
        None.
    '''
    if not _page(case, 500, 0):
        return
    groups: dict[tuple, list[str]] = {}
    for item in case.data['items']:
        groups.setdefault((item['site_id'], item['dir'], item['name'], item['copy_index']), []).append(item['snapshot_time'])
    versions = [times for times in groups.values() if len(set(times)) > 1]
    if not versions:
        case.report.state.append('%s: no file occurs in two snapshots within the first 500 rows (dates %s)' % (case.desc, case.params['dates']))
    elif any(times != sorted(times, reverse=True) for times in versions):
        case.bad('the versions of a file are not newest first')


def _s_paging(case: Case) -> None:
    '''RF5: the concatenation of pages equals one big page.

    Args:
        case: the executed case.

    Returns:
        None.
    '''
    second = _call('backup_search_files', dict(case.params, offset=5)).get('items', [])
    big = _call('backup_search_files', dict(case.params, limit=10)).get('items')
    if case.data.get('items', []) + second != big or not case.data.get('items'):
        case.bad('pages 0..5 and 5..10 differ from one page of 10 rows')


def _s_beyond(case: Case) -> None:
    '''RF5: an offset beyond the total gives no item and the exact total.

    Args:
        case: the executed case.

    Returns:
        None.
    '''
    total = _call('backup_search_files', {'dates': case.params['dates']}).get('total')
    if case.data.get('items') != [] or case.data.get('total') != total or not total:
        case.bad('expected items [] and the total %s, got %s' % (total, str(case.data)[:100]))


def _u_check(case: Case, limit: int, text: str) -> list[str]:
    '''Judge a suggestion result and return its names.

    Args:
        case: the executed case.
        limit: the effective limit.
        text: the typed text.

    Returns:
        The suggested names.
    '''
    if not case.fields(['items', 'text', 'truncated']):
        return []
    names = [item.get('name', '') for item in case.data['items']]
    match = matcher(text)
    if len(names) > limit or case.data['text'] != text.strip() or type(case.data['truncated']) is not bool or not all(match(name) for name in names):
        case.bad('%d names (limit %d), text %r, truncated %r or a name that does not match %r' % (len(names), limit, case.data['text'], case.data['truncated'], text))
    order = [(not key(name).startswith(key(text)), key(name), name) for name in names]
    if '*' not in text and order != sorted(order):
        case.bad('names with the typed prefix do not come first in key order')
    return names


def _u_basic(case: Case) -> None:
    '''C9: at most 10 names that contain the text, prefix matches first.

    Args:
        case: the executed case.

    Returns:
        None.
    '''
    _u_check(case, 10, case.params['text'])


def _u_glob(case: Case) -> None:
    '''C9: with a trailing star every name starts with the text.

    Args:
        case: the executed case.

    Returns:
        None.
    '''
    if any(not key(name).startswith('акт') for name in _u_check(case, 20, case.params['text'])):
        case.bad('a name does not start with акт')


def _u_rf3(case: Case) -> None:
    '''RF3: every suggested name is the name of a row of the search with the same text.

    Args:
        case: the executed case.

    Returns:
        None.
    '''
    shown = {item['name'] for item in _call('backup_search_files', {'name_part': case.params['text'], 'limit': 500}).get('items', [])}
    missing = [item.get('name') for item in case.data.get('items', []) if item.get('name') not in shown]
    if missing or not case.data.get('items'):
        case.bad('names %s are not rows of backup_search_files, or there is no name' % missing)


VALIDATORS: dict[str, Callable[[Case], None]] = {
    'fo_base': _fo_base, 'fo_site': _fo_site, 'fo_unknown': _fo_unknown, 'nowrite': _nowrite, 's_default': _s_default, 's_dates': _s_dates,
    's_case': _s_case, 's_glob': _s_glob, 's_contains': _s_contains, 's_versions': _s_versions, 's_paging': _s_paging, 's_beyond': _s_beyond,
    'u_basic': _u_basic, 'u_glob': _u_glob, 'u_rf3': _u_rf3,
}


def _judge(report: Report, desc: str, command: str, params: dict, expect: str, ctx: Context) -> None:
    '''Send one case and judge the reply against its expectation.

    Args:
        report: the findings collector.
        desc: the case description.
        command: the service command.
        params: the parameter map to send.
        expect: the expectation of the result contract.
        ctx: the runtime placeholders.

    Returns:
        None.
    '''
    reply = live.request(command, params)
    kind, code, message, data = reply
    mode, _, rest = expect.partition(':')
    if mode == 'rpc':
        cmdcases._judge_rpc(report, desc, reply, rest, rest in ('type', 'value'), 'text')
    elif mode == 'cmd':
        want, _, token = rest.partition(':')
        if not (kind == 'command_error' and code == int(want) and token in message):
            report.product.append('%s: expected command error %s %s, got %s' % (desc, want, token, cmdcases._brief(*reply)))
    elif kind != 'success' or not isinstance(data, dict):
        report.product.append('%s: expected success, got %s' % (desc, cmdcases._brief(*reply)))
    else:
        VALIDATORS[rest](Case(report, desc, data, ctx, params))


def run_row(row_id: str, name: str) -> None:
    '''Execute every case of the command row row_id against the deployed service and raise CheckFailure on a finding.

    Args:
        row_id: the matrix row, M12, M13 or M14.
        name: the named check.

    Returns:
        None.
    '''
    data = matrix.load()
    row = next(item for item in data['rows'] if item['id'] == row_id)
    contracts = data['result_contracts'][row_id]['cases']
    report = Report()
    try:
        state = live.service_state()
        ctx = Context()
        if state != 'S1':
            report.state.append('%s: the cases need an S1 service, production answers %s' % (row_id, state))
        for case in row['cases'] if state == 'S1' else []:
            expect = contracts.get(case['id'], {}).get('expect')
            params = ctx.resolve(case['params'])
            desc = '%s %s %s(%s)' % (row_id, case['id'], row['command'], json.dumps(params, ensure_ascii=False))
            if expect is None:
                report.product.append('%s: no result contract with an expectation in pipeline/matrix.yaml' % desc)
            else:
                _judge(report, desc, row['command'], params, expect, ctx)
        report.info.append('%d cases of row %s executed on %d live snapshots' % (len(row['cases']), row_id, len(ctx.snapshots)))
    except live.LiveUnreachable as exc:
        report.env.append('%s: not executed, production service unreachable: %s' % (row_id, exc))
    report.finish(name)


def file_index_coverage() -> None:
    '''PL14: every snapshot of the service is indexed, so the index counts equal the live snapshot count.

    Returns:
        None.
    '''
    report = Report()
    try:
        kind, code, message, data = live.request('backup_filter_options', {})
        total = len(_call('backup_snapshots', {'limit': 1000}).get('items', []))
        index = data.get('index') if kind == 'success' and isinstance(data, dict) else None
        if kind != 'success':
            report.product.append('PL14 catchup_all_snapshots_indexed: backup_filter_options must answer the index state, got %s' % cmdcases._brief(kind, code, message, data))
        elif not isinstance(index, dict) or (index.get('complete'), index.get('snapshots_total'), index.get('snapshots_indexed')) != (True, total, total):
            report.product.append('PL14 catchup_all_snapshots_indexed: index %s, expected complete true with %d of %d snapshots indexed' % (index, total, total))
    except live.LiveUnreachable as exc:
        report.env.append('PL14: not executed, production service unreachable: %s' % exc)
    report.finish('file_index_coverage')


def client_check(command: str, method: str, name: str) -> None:
    '''C-K16..C-K18: BackupClient has the method with the contract parameters and it returns what the command returns.

    Args:
        command: the service command.
        method: the client method.
        name: the named check.

    Returns:
        None.
    '''
    report = Report()
    module = b4client.load_client(report)
    func = getattr(module.BackupClient, method, None) if module is not None else None
    if module is not None and not callable(func):
        report.product.append('client/onedrive_backup_client/api.py: BackupClient has no method %s (10.19.5 CLIENT AND CLI, command %s)' % (method, command))
    elif module is not None and func is not None:
        names = list(inspect.signature(func).parameters)[1:]
        client = b4client.make_client(module, report)
        if names != CLIENT_METHODS[method]:
            report.product.append('BackupClient.%s takes %s, expected %s' % (method, names, CLIENT_METHODS[method]))
        elif client is not None:
            got = b4client.drive(getattr(client, method), **BASELINE[command])
            if got != _call(command, BASELINE[command]):
                report.product.append('BackupClient.%s(%s) returned %s, not the result of %s' % (method, BASELINE[command], str(got)[:100], command))
    report.finish(name)


def odbcli_check(sub: str, argv: list[str], command: str, name: str) -> None:
    '''O17..O19: odbcli lists the subcommand and prints the result of the command as JSON.

    Args:
        sub: the subcommand name.
        argv: its arguments.
        command: the service command.
        name: the named check.

    Returns:
        None.
    '''
    report = Report()
    main = b4cli.entry(report)
    if main is not None:
        subs = b4cli._subcommands(main)
        if subs is None or sub not in subs:
            report.product.append('odbcli lists the subcommands %s, expected %s among them (10.19.5 CLIENT AND CLI)' % (subs, sub))
        else:
            code, out, err = b4cli.run_cli(main, b4cli.global_args() + [sub] + argv)
            try:
                printed = json.loads(out)
            except ValueError:
                printed = None
            if code != 0 or printed != _call(command, BASELINE[command]):
                report.product.append('odbcli %s %s: exit %s, stdout %s, stderr %s, expected the JSON result of %s' % (sub, argv, code, out[:100], err[:100], command))
    report.finish(name)
