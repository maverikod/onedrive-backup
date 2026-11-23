'''Revision 13 live executor (matrix TODO 10.21, block TREE-REV13): row M19 backup_folder_children and the scope cases of M13 and M14.

The cases of 10.21.7 (ids tc*) are sent through the project client from the checkout source (BackupClient.raw_call, the bounded
validation invocation: the 0.3.25 client has no method and no parameter for them) and judged against their result contract
(`expect`: rpc:<violation>, cmd:<code>:<token> or ok:<validator>). The cases of revision 11 of M13 and M14 keep their executor
pipeline.rev11 unchanged (RT7). Every case ends with one [INFO] line naming its verdict. Findings are PRODUCT, STATE or ENVIRONMENT.
'''

from __future__ import annotations

import hashlib
import json
from datetime import datetime
from typing import Any, Callable
from zoneinfo import ZoneInfo

from pipeline import b4client, cmdcases, live, matrix, rev11
from pipeline.report import Report

DENGI = 'ДЕНЬГИ'
DOCS = 'Документи'
SITE_NAME = 'Бухгалтерия'
TREE_DATE = '2026-11-21'
DIR_WIDE = 'Все сотрудники/Документы сотрудников/Документы'
DIR_TG = 'ЭКСПОРТ/Экспорт Анна/Акты Полынько/Новая папка/Telegram Desktop'
DUP_NAME = 'Счет_фактура_по_коммунальным_платежам_май_2022_общий_31_37.xls'
UNKNOWN_SITE = 'unknown.sharepoint.com,00000000-0000-0000-0000-000000000000,00000000-0000-0000-0000-000000000001'
SCHEDULE_REVISION = '72f24d4214216c75eeb0e45a3b323e50045d25a5a0cbc68c1f7758cbe386da87'
EXPORT_COMMANDS = ('backup_prepare_download', 'backup_download_begin', 'backup_delete_export')
COMPANIONS = (('dir', 'drive_id'), ('recursive', 'drive_id'), ('drive_id', 'site_id'))
Reply = tuple[str, Any, str, Any]


def digest(text: str) -> str:
    '''Return the sha256 hex of a site or drive id, the key segment of the mirror and of the snapshot tags.

    Args:
        text: the id.

    Returns:
        The 64-hex key.
    '''
    return hashlib.sha256(text.encode('utf-8')).hexdigest()


def local_day(stamp: str) -> str:
    '''Return the backup date of a UTC time stamp in the service time zone.

    Args:
        stamp: an ISO time ending with Z.

    Returns:
        The date YYYY-MM-DD.
    '''
    return datetime.fromisoformat(str(stamp).replace('Z', '+00:00')).astimezone(ZoneInfo(rev11.TZ)).date().isoformat()


class Tree(rev11.Context):
    '''Runtime state of the revision 13 cases: the client, the site, its libraries and the reference listing of F4.

    Attributes:
        report: the findings collector.
        client: the project client or None after a finding.
        sent: every command sent through the client, in order.
        site_name: the shown name of the site.
        libraries: display name by drive id.
        listing_id: the snapshot of ДЕНЬГИ on TREE_DATE, or ''.
        files: the (dir, name) of every file of that snapshot.
        before: the observable service state before the first case (TC15).
    '''

    def __init__(self, report: Report) -> None:
        '''Read the client, the site, its libraries, the reference listing and the state once.'''
        super().__init__()
        self.report = report
        self.sent: list[str] = []
        module = b4client.load_client(report)
        self.client = b4client.make_client(module, report) if module is not None else None
        sites = self.data('backup_sites_list', {'limit': 1000}).get('items', [])
        self.site_name = next((str(s.get('display_name') or s.get('web_url') or s.get('site_id')) for s in sites if s.get('site_id') == self.site), '')
        libs = self.data('backup_libraries_list', {'site_id': self.site, 'limit': 1000}).get('items', []) if self.site else []
        self.libraries = {str(i.get('drive_id')): str(i.get('display_name') or i.get('web_url') or i.get('drive_id')) for i in libs}
        self.listing_id, self.files = self._listing()
        self.folders = sorted({d.split('/')[0] for d, _ in self.files if d}, key=lambda name: (rev11.key(name), name))
        akt = self.data('backup_search_files', {'name_part': 'акт', 'limit': 500}).get('items', [])
        self.akt_dir = next((str(i['dir']) for i in akt if rev11.key(str(i.get('library_name'))) == rev11.key(DOCS) and i.get('dir')), 'folder-none')
        self.table = {'$DRIVE_DENGI': self.drive(DENGI), '$DRIVE_DOCS': self.drive(DOCS), '$DIR_WIDE': DIR_WIDE, '$DIR_TG': DIR_TG,
                      '$DIR_DENGI_FOLDER': self.folders[0] if self.folders else 'folder-none', '$DIR_NEAKTIVNYE': self.folder('неактивн'),
                      '$DIR_ARKHIV': self.folder('рхив'), '$DUP_NAME': DUP_NAME, '$UNKNOWN_SITE': UNKNOWN_SITE, '$DIR_WITH_AKT': self.akt_dir,
                      '$DIR_65': '/'.join(['a'] * 65), '$DIR_1025': '/'.join(['a' * 200] * 5) + '/' + 'a' * 20, '$SEG_256': 'a' * 256}
        self.before = self.state()

    def send(self, command: str, params: dict) -> Reply:
        '''Send one parameter map unchanged through BackupClient.raw_call and classify the outcome like pipeline.live.

        Args:
            command: the service command.
            params: the parameter map.

        Returns:
            (kind, code, message, data); kind is success, command_error or rpc_error.
        '''
        self.sent.append(command)
        if self.client is None:
            return 'malformed', None, 'the project client could not be built', {}
        value, exc = b4client.drive(self.client.raw_call, command, params)
        if exc is None:
            return 'success', None, '', value
        code = b4client.error_code(exc)
        if not isinstance(code, int):
            raise live.LiveUnreachable('%s through the client failed: %s: %s' % (command, type(exc).__name__, exc))
        data = getattr(exc, 'data', None)
        return 'rpc_error' if code < 0 else 'command_error', code, str(exc), data if isinstance(data, dict) else {}

    def data(self, command: str, params: dict) -> dict:
        '''Return the data of a successful call, or an empty map.

        Args:
            command: the service command.
            params: the parameter map.

        Returns:
            The data map.
        '''
        kind, _, _, data = self.send(command, params)
        return data if kind == 'success' and isinstance(data, dict) else {}

    def drive(self, name: str) -> str:
        '''Return the drive id of the library shown as name, located through backup_libraries_list.

        Args:
            name: the library name.

        Returns:
            The drive id, or 'drive-none'.
        '''
        return next((drive for drive, shown in self.libraries.items() if rev11.key(shown) == rev11.key(name)), 'drive-none')

    def folder(self, part: str) -> str:
        '''Return the first top folder of the reference listing whose key contains part.

        Args:
            part: a key fragment.

        Returns:
            The folder name, or 'folder-none'.
        '''
        return next((name for name in self.folders if part in rev11.key(name)), 'folder-none')

    def _listing(self) -> tuple[str, list[tuple[str, str]]]:
        '''Read the snapshot of ДЕНЬГИ taken on TREE_DATE completely with one backup_list_files call (F4).

        Returns:
            (snapshot id, [(dir, name)] of its files); ('', []) after a STATE finding.
        '''
        drive = self.drive(DENGI)
        found = [s for s in self.snapshots if 'drive-' + digest(drive) in s.get('tags', []) and local_day(s.get('time', '')) == TREE_DATE]
        if len(found) != 1:
            self.report.state.append('F4: expected one snapshot of %s on %s, found %d' % (DENGI, TREE_DATE, len(found)))
            return '', []
        data = self.data('backup_list_files', {'snapshot_id': found[0]['id'], 'limit': 5000})
        prefix = 'sharepoint/%s/%s/' % (digest(self.site or ''), digest(drive))
        items = data.get('items', [])
        if not items or data.get('total') != len(items):
            self.report.state.append('F4: backup_list_files of %s returned %d of %s nodes in one call' % (found[0]['id'][:8], len(items), data.get('total')))
        files = [str(i['path'])[len(prefix):] for i in items if i.get('type') == 'file' and str(i.get('path')).startswith(prefix)]
        return str(found[0]['id']), [(p.rsplit('/', 1)[0] if '/' in p else '', p.rsplit('/', 1)[-1]) for p in files]

    def resolve(self, value: Any) -> Any:
        '''Replace the revision 13 placeholders, then those of revision 11.

        Args:
            value: a parameter value, list or map.

        Returns:
            The value with the placeholders replaced.
        '''
        if isinstance(value, str) and value in self.table:
            return self.table[value]
        return super().resolve(value)

    def state(self) -> dict:
        '''Return the observable state TC15 compares: snapshots, index counts, rows per backup date, schedule revision.

        Returns:
            The state map.
        '''
        index = self.data('backup_filter_options', {}).get('index')
        rows = {day: self.data('backup_search_files', {'dates': [day], 'limit': 1}).get('total') for day in self.days}
        snaps = [i.get('id') for i in self.data('backup_snapshots', {'limit': 1000}).get('items', [])]
        return {'snapshots': snaps, 'index': index, 'rows': rows, 'schedule': self.data('backup_schedule_get', {}).get('revision')}


class Case(rev11.Case):
    '''One executed case with a successful reply and the revision 13 state.

    Attributes:
        tree: the revision 13 state.
    '''

    def __init__(self, report: Report, desc: str, data: dict, tree: Tree, params: dict) -> None:
        '''Keep the case parts.'''
        super().__init__(report, desc, data, tree, params)
        self.tree = tree

    def need(self, command: str, params: dict) -> dict | None:
        '''Return the data of an auxiliary call of the case, or None after a PRODUCT finding.

        Args:
            command: the service command.
            params: the parameter map.

        Returns:
            The data map or None.
        '''
        reply = self.tree.send(command, params)
        if reply[0] == 'success' and isinstance(reply[3], dict):
            return reply[3]
        self.bad('the auxiliary call %s(%s) failed: %s' % (command, json.dumps(params, ensure_ascii=False)[:160], cmdcases._brief(*reply)))
        return None

    def total(self, params: dict) -> int | None:
        '''Return the backup_search_files total for params, or None after a finding.

        Args:
            params: the search parameters.

        Returns:
            The total or None.
        '''
        data = self.need('backup_search_files', dict(params, limit=1))
        return data.get('total') if data is not None else None


Validators = dict[str, Callable[[Case], None]]


def _judge_error(report: Report, desc: str, reply: Reply, expect: str, unknown: list[str], params: dict) -> None:
    '''Judge an error case: the adapter ErrorResult (rpc) or the command error code and token (cmd), no result data.

    Args:
        report: the findings collector.
        desc: the case description.
        reply: the classified reply.
        expect: rpc:<violation> or cmd:<code>:<token>.
        unknown: the supplied names without a cell in the row.
        params: the parameters sent.

    Returns:
        None.
    '''
    kind, code, message, data = reply
    mode, _, rest = expect.partition(':')
    if mode == 'rpc':
        ok = kind == 'rpc_error' and code == -32602 and data.get('violation') == rest
        ok = ok and (rest != 'unknown' or all(name in data.get('invalid_parameters', []) for name in unknown))
        ok = ok and (rest not in ('type', 'value') or ('expected' in data and 'got' in data))
        if not ok:
            report.product.append('%s: expected adapter error -32602 violation=%s%s, got %s' % (desc, rest, ' with expected and got' if rest in ('type', 'value') else ' naming %s' % unknown, cmdcases._brief(*reply)))
        return
    want, _, token = rest.partition(':')
    missing = sorted({need for have, need in COMPANIONS if have in params and need not in params})
    if not (kind == 'command_error' and code == int(want) and token in message):
        report.product.append('%s: expected command error %s %s, got %s' % (desc, want, token, cmdcases._brief(*reply)))
    elif token == 'INVALID_FOLDER_SCOPE' and not all(name in json.dumps(data) for name in missing):
        report.product.append('%s: INVALID_FOLDER_SCOPE error.data %s does not list the fields %s (RT1/RT2)' % (desc, json.dumps(data)[:160], missing))
    if 'items' in data or 'nodes' in data:
        report.product.append('%s: the error carries result items' % desc)


def _judge(tree: Tree, report: Report, desc: str, row: dict, params: dict, expect: str, validators: Validators) -> None:
    '''Send one revision 13 case through the client and judge the reply against its expectation.

    Args:
        tree: the revision 13 state.
        report: the findings collector.
        desc: the case description.
        row: the matrix row.
        params: the parameter map to send.
        expect: the expectation of the result contract.
        validators: the ok: validators of the row.

    Returns:
        None.
    '''
    reply = tree.send(row['command'], params)
    mode, _, rest = expect.partition(':')
    if mode in ('rpc', 'cmd'):
        _judge_error(report, desc, reply, expect, [name for name in params if name not in row['params']], params)
    elif reply[0] != 'success' or not isinstance(reply[3], dict):
        report.product.append('%s: expected success, got %s' % (desc, cmdcases._brief(*reply)))
    elif rest not in validators:
        report.product.append('%s: harness: no executable validator %s for the expectation %s' % (desc, rest, expect))
    else:
        validators[rest](Case(report, desc, reply[3], tree, params))


def run_row(row_id: str, name: str, validators: Validators) -> None:
    '''Execute every case of the command row row_id (M13, M14 or M19) and raise CheckFailure on a finding.

    Args:
        row_id: the matrix row.
        name: the named check.
        validators: the ok: validators of the revision 13 cases (pipeline.rev13scope or pipeline.rev13tree).

    Returns:
        None.
    '''
    data = matrix.load()
    row = next(item for item in data['rows'] if item['id'] == row_id)
    contracts = data['result_contracts'][row_id]['cases']
    report = Report()
    try:
        state = live.service_state()
        tree = Tree(report)
        if state != 'S1':
            report.state.append('%s: the cases need an S1 service, production answers %s' % (row_id, state))
        for case in row['cases'] if state == 'S1' else []:
            expect = contracts.get(case['id'], {}).get('expect')
            params = tree.resolve(case['params'])
            desc = '%s %s %s(%s)' % (row_id, case['id'], row['command'], json.dumps(params, ensure_ascii=False)[:300])
            before = len(report.product) + len(report.state)
            if expect is None:
                report.product.append('%s: no result contract with an expectation in pipeline/matrix.yaml' % desc)
            elif str(case['id']).startswith('tc'):
                _judge(tree, report, desc, row, params, expect, validators)
            else:
                rev11._judge(report, desc, row['command'], params, expect, tree)
            report.info.append('%s %s: %s' % (row_id, case['id'], 'GREEN' if len(report.product) + len(report.state) == before else 'RED'))
        report.info.append('%d cases of row %s executed on %d live snapshots, %d client calls' % (len(row['cases']), row_id, len(tree.snapshots), len(tree.sent)))
    except live.LiveUnreachable as exc:
        report.env.append('%s: not executed, production service unreachable: %s' % (row_id, exc))
    report.finish(name)
