'''Revision 14 live executor (matrix TODO 10.22, blocks DATES-REV14 and MODEL-REV14): the appended cases of M3-M6, M12-M14, M19, M21.

The cases of 10.22.9 (ids td*, tm*, rm*) are sent through the project client from the checkout source (BackupClient.raw_call, the
bounded validation invocation: the 0.3.28 client has no parameter for them) and judged against their result contract (`expect`:
rpc:<violation>, cmd:<code>[:<token>] or ok:<validator>); a command error must also satisfy the error.data predicate of its case
(RM4, RM6, TD3, TD15). The earlier cases keep their executors (pipeline.cmdcases, pipeline.rev11, pipeline.rev13) with two rules:
(1) 10.22.10: the success cases listed in reconciliations_10_22.rev14_dates_default send explicit dates [the newest backup date],
and so does every auxiliary search, suggestion and tree call they make, so they keep their 0.3.27 meaning under the new default;
(2) RM7: the keys revision 14 adds are removed from the answers the earlier validators judge (they assert the 0.3.27 shape, the
added keys are asserted by the revision 14 cases). Every export a case stages is deleted at the end and its status is then 404.
Findings are PRODUCT, STATE or ENVIRONMENT (pipeline.report).
'''

from __future__ import annotations

import contextlib
import hashlib
import json
import time
from typing import Any, Callable, Iterator

from pipeline import cmdcases, live, matrix, rev11, rev13
from pipeline.report import Report

PREFIXES = ('td', 'tm', 'rm')
DATE_COMMANDS = ('backup_search_files', 'backup_suggest_names', 'backup_folder_children')
SEARCH_ADDED = ('file_id', 'ext', 'snapshot_time_local', 'snapshot_date', 'backup_type', 'trigger', 'run_id', 'snapshot_count',
                'first_date', 'last_date', 'version_count')
SNAPSHOT_ADDED = ('site_id', 'site_name', 'library_name', 'drive_id', 'date', 'time_local', 'backup_type', 'trigger', 'run_id',
                  'type_source')
DATE_ITEM_ADDED = ('backup_types', 'triggers', 'run_count', 'library_count', 'last_snapshot_time')
ADDED: dict[str, tuple[tuple[str, ...], str, tuple[str, ...]]] = {
    'backup_search_files': (('date_scope', 'warnings'), 'items', SEARCH_ADDED),
    'backup_suggest_names': (('warnings',), 'items', ()),
    'backup_folder_children': (('date_scope', 'warnings'), 'nodes', ()),
    'backup_filter_options': (('latest', 'warnings'), 'dates', DATE_ITEM_ADDED),
    'backup_list_files': (('warnings',), 'items', ('file_id',)),
    'backup_snapshots': ((), 'items', SNAPSHOT_ADDED),
}
FIELD_KEYS = ['site_id', 'site_name', 'library_name', 'drive_id', 'name', 'ext', 'dir', 'size', 'mtime', 'snapshot_id', 'snapshot_time',
              'snapshot_time_local', 'snapshot_date', 'file_path', 'file_id', 'is_copy', 'copy_index', 'backup_type', 'trigger', 'run_id',
              'snapshot_count', 'first_date', 'last_date', 'version_count']
UNKNOWN_EXPORT = 'Unknown export identifier'
Reply = tuple[str, Any, str, Any]


def file_id(snapshot_id: str, file_path: str) -> str:
    '''Return the file id of 10.22.4.1 (RM3): <first 8 hex of the snapshot id>.<first 24 hex of sha256(snapshot id + LF + path)>.

    Args:
        snapshot_id: the 64-hex snapshot id.
        file_path: the file_path of a search row.

    Returns:
        The 33-character id.
    '''
    return '%s.%s' % (snapshot_id[:8], hashlib.sha256(('%s\n%s' % (snapshot_id, file_path)).encode('utf-8')).hexdigest()[:24])


def strip(command: str, data: Any) -> Any:
    '''Remove the keys revision 14 adds to the answer of command (RM7), so an earlier validator sees the 0.3.27 shape.

    Args:
        command: the service command.
        data: the success data.

    Returns:
        A copy without the added keys, or data unchanged for another command or shape.
    '''
    if command not in ADDED or not isinstance(data, dict):
        return data
    top, name, keys = ADDED[command]
    out = {key: value for key, value in data.items() if key not in top}
    if keys and isinstance(out.get(name), list):
        out[name] = [{k: v for k, v in item.items() if k not in keys} if isinstance(item, dict) else item for item in out[name]]
    return out


def scoped(command: str, params: dict, scope: dict) -> dict:
    '''Add the date scope of a rev14_dates_default case to a search, suggestion or tree call that names no date scope itself.

    Args:
        command: the service command.
        params: the parameter map.
        scope: {'dates': [...]} or {}.

    Returns:
        The parameter map to send.
    '''
    if scope and command in DATE_COMMANDS and not ({'dates', 'dates_mode'} & set(params)):
        return dict(params, **scope)
    return params


class Tree14(rev13.Tree):
    '''Runtime state of the revision 14 cases: the revision 13 state, lazy samples, the exports staged and the legacy mode.

    Attributes:
        scope: the date scope added to the calls of a rev14_dates_default case.
        legacy: True while an earlier case runs (answers are stripped of the added keys).
        exports: the export ids staged by this run, deleted at the end.
        lazy: placeholder name -> function computing its value on first use.
        extra: the values of the revision 14 placeholders (static, and lazy ones once computed).
        seconds: the duration of the last call in seconds.
    '''

    def __init__(self, report: Report) -> None:
        '''Read the revision 13 state, then add the static revision 14 placeholders.'''
        self.scope: dict = {}
        self.legacy = False
        self.exports: list[str] = []
        self.lazy: dict[str, Callable[[], Any]] = {}
        self.seconds = 0.0
        super().__init__(report)
        self.extra: dict[str, Any] = {'$FIELDS_ALL': list(FIELD_KEYS), '$FIELDS_31': list(FIELD_KEYS) + ['f%d' % i for i in range(31 - len(FIELD_KEYS))],
                                      '$SNAPSHOT_DENGI': self.listing_id or 'snapshot-none'}

    def send(self, command: str, params: dict) -> Reply:
        '''Send one call through the client with the case scope, record staged exports and strip answers in legacy mode.

        Args:
            command: the service command.
            params: the parameter map.

        Returns:
            (kind, code, message, data) as pipeline.rev13.Tree.send.
        '''
        params = scoped(command, params, self.scope)
        start = time.monotonic()
        kind, code, message, data = super().send(command, params)
        self.seconds = time.monotonic() - start
        if kind == 'success' and command == 'backup_prepare_download' and isinstance(data, dict) and data.get('export_id'):
            self.exports.append(str(data['export_id']))
        return kind, code, message, strip(command, data) if self.legacy and kind == 'success' else data

    def resolve(self, value: Any) -> Any:
        '''Replace a lazy placeholder (computed once), then the revision 13 and 11 placeholders.

        Args:
            value: a parameter value, list or map.

        Returns:
            The value with the placeholders replaced.
        '''
        if isinstance(value, str) and (value in self.extra or value in self.lazy):
            if value not in self.extra:
                self.extra[value] = self.lazy[value]()
            return self.extra[value]
        return super().resolve(value)

    def cleanup(self) -> None:
        '''Delete every export this run staged; its status must then answer 404 (none may remain).'''
        for export in dict.fromkeys(self.exports):
            self.send('backup_delete_export', {'export_id': export})
            kind, code, message, _ = self.send('backup_download_status', {'export_id': export})
            if not (kind == 'command_error' and code == 404):
                self.report.product.append('cleanup: export %s staged by this check is still present after backup_delete_export: %s %s %s'
                                           % (export, kind, code, message[:80]))
        self.report.info.append('cleanup: %d export(s) staged by this check, all deleted' % len(set(self.exports)))


class Case14(rev13.Case):
    '''One executed revision 14 case with a successful reply.

    Attributes:
        cid: the case id.
    '''

    def __init__(self, report: Report, desc: str, data: dict, tree: Tree14, params: dict, cid: str) -> None:
        '''Keep the case parts.'''
        super().__init__(report, desc, data, tree, params)
        self.tree14 = tree
        self.cid = cid


Validators = dict[str, Callable[[Case14], None]]
ErrorChecks = dict[str, Callable[[Reply, Tree14], str]]


def edata(reply: Reply) -> dict:
    '''Return error.data of a classified reply, or an empty map.

    Args:
        reply: (kind, code, message, data).

    Returns:
        The data map.
    '''
    return reply[3] if isinstance(reply[3], dict) else {}


def judge(tree: Tree14, report: Report, desc: str, row: dict, cid: str, params: dict, expect: str, validators: Validators,
          errors: ErrorChecks) -> None:
    '''Send one revision 14 case and judge the reply: the adapter or command error and its error.data, or the ok: validator.

    Args:
        tree: the revision 14 state.
        report: the findings collector.
        desc: the case description.
        row: the matrix row.
        cid: the case id.
        params: the parameter map to send.
        expect: the expectation of the result contract.
        validators: the ok: validators of the row.
        errors: the error.data predicates by case id.

    Returns:
        None.
    '''
    reply = tree.send(row['command'], params)
    mode, _, rest = expect.partition(':')
    before = len(report.product)
    if mode in ('rpc', 'cmd'):
        rev13._judge_error(report, desc, reply, expect, [name for name in params if name not in row['params']], params)
        problem = errors[cid](reply, tree) if cid in errors and len(report.product) == before else ''
        if problem:
            report.product.append('%s: %s' % (desc, problem))
    elif reply[0] != 'success' or not isinstance(reply[3], dict):
        report.product.append('%s: expected success, got %s' % (desc, cmdcases._brief(*reply)))
    elif rest not in validators:
        report.env.append('%s: harness: no executable validator %s for the expectation %s' % (desc, rest, expect))
    else:
        validators[rest](Case14(report, desc, reply[3], tree, params, cid))


@contextlib.contextmanager
def legacy(tree: Tree14, scope: dict) -> Iterator[None]:
    '''Run an earlier case: answers stripped of the added keys, and the date scope added to the calls of pipeline.rev11 and the tree.

    Args:
        tree: the revision 14 state.
        scope: the date scope of a rev14_dates_default case or {}.

    Yields:
        None.
    '''
    original = rev11._call

    def call(command: str, params: dict) -> dict:
        '''pipeline.rev11._call with the case scope and the stripped answer.

        Args:
            command: the service command.
            params: its parameters.

        Returns:
            The stripped data map.
        '''
        return strip(command, original(command, scoped(command, params, scope)))

    tree.scope, tree.legacy = scope, True
    setattr(rev11, '_call', call)
    try:
        yield
    finally:
        setattr(rev11, '_call', original)
        tree.scope, tree.legacy = {}, False


def _legacy11(tree: Tree14, report: Report, desc: str, command: str, params: dict, expect: str) -> None:
    '''Execute an earlier case of pipeline.rev11 (M12-M14): errors as rev11, a success judged on the stripped answer.

    Args:
        tree: the revision 14 state.
        report: the findings collector.
        desc: the case description.
        command: the service command.
        params: the parameter map.
        expect: the expectation of the result contract.

    Returns:
        None.
    '''
    mode, _, rest = expect.partition(':')
    if mode in ('rpc', 'cmd'):
        rev11._judge(report, desc, command, params, expect, tree)
        return
    kind, code, message, data = live.request(command, params)
    if kind != 'success' or not isinstance(data, dict):
        report.product.append('%s: expected success, got %s' % (desc, cmdcases._brief(kind, code, message, data)))
    else:
        rev11.VALIDATORS[rest](rev11.Case(report, desc, strip(command, data), tree, params))


def run_row(row_id: str, name: str, validators: Validators, errors: ErrorChecks, old: dict | None = None,
            setup: Callable[[Tree14], Any] | None = None, only: Callable[[str], bool] | None = None, all_new: bool = False) -> None:
    '''Execute every case of a filter row (M12, M13, M14, M19) or the new row M21 and raise CheckFailure on a finding.

    Args:
        row_id: the matrix row.
        name: the named check.
        validators: the ok: validators of the revision 14 cases.
        errors: the error.data predicates of the revision 14 cases.
        old: the ok: validators of the revision 13 cases (ids tc*), or None.
        setup: registers the lazy placeholders of the row, or None.
        only: selects the case ids this check executes, or None for all.
        all_new: True for a row that revision 14 adds (M21): every case is a revision 14 case.

    Returns:
        None.
    '''
    data = matrix.load()
    row = next(item for item in data['rows'] if item['id'] == row_id)
    contracts = data['result_contracts'][row_id]['cases']
    defaults = data['identity']['reconciliations_10_22']['rev14_dates_default']['cases'].get(row_id, [])
    report = Report()
    tree: Tree14 | None = None
    try:
        state = live.service_state()
        tree = Tree14(report)
        if setup is not None:
            setup(tree)
        if state != 'S1':
            report.state.append('%s: the cases need an S1 service, production answers %s' % (row_id, state))
        cases = [case for case in row['cases'] if only is None or only(str(case['id']))] if state == 'S1' else []
        for case in cases:
            cid = str(case['id'])
            expect = contracts.get(cid, {}).get('expect')
            scope = {'dates': [tree.days[-1]]} if cid in defaults and tree.days else {}
            params = scoped(row['command'], tree.resolve(case['params'] or {}), scope)
            desc = '%s %s %s(%s)' % (row_id, cid, row['command'], json.dumps(params, ensure_ascii=False)[:300])
            before = len(report.product) + len(report.state) + len(report.env)
            if expect is None:
                report.product.append('%s: no result contract with an expectation in pipeline/matrix.yaml' % desc)
            elif all_new or cid.startswith(PREFIXES):
                judge(tree, report, desc, row, cid, params, expect, validators, errors)
            else:
                with legacy(tree, scope):
                    if cid.startswith('tc'):
                        rev13._judge(tree, report, desc, row, params, expect, old or {})
                    else:
                        _legacy11(tree, report, desc, row['command'], params, expect)
            changed = len(report.product) + len(report.state) + len(report.env) != before
            report.info.append('%s %s: %s%s' % (row_id, cid, 'RED' if changed else 'GREEN', ' (dates %s, 10.22.10)' % scope['dates'] if scope else ''))
        report.info.append('%d cases of row %s executed on %d live snapshots, %d client calls' % (len(cases), row_id, len(tree.snapshots), len(tree.sent)))
    except live.LiveUnreachable as exc:
        report.env.append('%s: not executed, production service unreachable: %s' % (row_id, exc))
    finally:
        if tree is not None:
            tree.cleanup()
    report.finish(name)
