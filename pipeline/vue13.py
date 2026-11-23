'''Revision 13 UI-TREE checks (matrix TODO 10.21.6 and 10.21.8, rows V12, V3, V4, V6, block UI-TREE).

vue_folder_tree runs the live Playwright cases L16-L27 and the four stub cases of row V12 (pipeline.vue13cases), each case on its own
page and under its case id, so a page without the folder tree is RED once per case. vue_command_contract, vue_command_calls and
vue_build compose the unchanged revision 12 bodies with the revision 13 assertions: the served manifest lists the 18 commands with the
new cells (V3), '#/' sends backup_folder_children beside the filter and search calls with the parameter keys of 10.21.6 CALLS (V4; the
load and apply cases L1 and L3 of 10.19.4 are replaced by 10.21.6, 10.21.9 (2)), and the Vitest groups foldertree, treekeys,
breadcrumb and the extended filters group exist (V6). READ-ONLY on the service.
'''

from __future__ import annotations

import hashlib
import json
import re
from typing import Callable

from pipeline import b4base, live, vue11, vue12, vuebrowser, vuebuild, vuechecks
from pipeline.checks import CheckFailure
from pipeline.report import Report
from pipeline.vue13base import M13, M14, M19, SCOPE_KEYS, TREE_KEYS, Ref
from pipeline.vue13cases import Cases13
from pipeline.vuebase import lan_try, spa_files, tracked_files

COMMANDS13 = 18
CASES = ('l16_three_regions', 'l17_toggle_site', 'l18_expand_library', 'l19_select_folder', 'l20_reload_restores', 'l21_and_name_filter',
         'l22_recursive_library', 'l23_keyboard', 'l24_tree_all_clears', 'l25_tree_more', 'l26_narrow_stack', 'l27_logout_zero_calls',
         'stub_tree_error_banner', 'stub_stale_tree_answer', 'stub_scope_kept_empty', 'stub_copy_marker_scoped')
V4_CASES = ('load13', 'apply13', 'l18_expand_library', 'l19_select_folder', 'l25_tree_more')
KEPT11 = ('nav_ids', 'site_tick', 'wildcard_rows', 'columns', 'service_tabs', 'old_routes', 'service_toolbar', 'result_pager')
GROUPS13 = ('foldertree', 'treekeys', 'breadcrumb')
FILTER_SCOPE = ('fs', 'fd', 'fp', 'rec')
MANIFEST13 = ((M19, TREE_KEYS), (M13, SCOPE_KEYS), (M14, SCOPE_KEYS))


def compose(name: str, old: Callable[[], None] | None, extra: Callable[[Report], None]) -> None:
    '''Run the unchanged check body and the revision 13 cases and raise one CheckFailure holding both results.

    Args:
        name: the named check.
        old: the body of the check before revision 13, or None.
        extra: the revision 13 cases, filling a report.

    Returns:
        None.
    '''
    lines: list[str] = []
    for body in ([old] if old else []) + [lambda: _finish(name, extra)]:
        try:
            body()
        except CheckFailure as exc:
            lines.append(str(exc))
    if lines:
        raise CheckFailure('\n'.join(lines))


def _finish(name: str, extra: Callable[[Report], None]) -> None:
    '''Fill a report with the extra cases and finish it.

    Args:
        name: the named check.
        extra: the revision 13 cases.

    Returns:
        None.
    '''
    report = Report()
    extra(report)
    report.finish(name + ' (revision 13)')


def _one(root: str, ref: Ref, name: str) -> Callable[[Report, object], None]:
    '''Return a browser case that runs one Cases13 method and keeps a failure of that case inside it.

    Args:
        root: the SPA endpoint URL.
        ref: the shared reference side.
        name: the Cases13 method (a case id of V12 or a V4 case).

    Returns:
        The case function for vuechecks.with_driver.
    '''
    def case(report: Report, drv: object) -> None:
        '''Run the case; an unexpected exception is a harness finding of this case only.

        Args:
            report: the findings collector.
            drv: the headless driver.

        Returns:
            None.
        '''
        try:
            getattr(Cases13(report, drv, root, ref), name)()
        except live.LiveUnreachable as exc:
            report.env.append('%s: not executed, %s' % (name, exc))
        except Exception as exc:
            report.env.append('%s: the headless case failed (harness): %s: %s' % (name, type(exc).__name__, str(exc)[:300]))
    return case


def _driven(report: Report, *names: str) -> None:
    '''Run Cases13 methods in one headless browser against the deployed SPA, one page per case.

    Args:
        report: the findings collector.
        names: the Cases13 methods.

    Returns:
        None.
    '''
    root = vuechecks.deployed(report, 'rev13 SPA endpoint')
    if root is not None:
        ref = Ref(report)
        vuechecks.with_driver(report, 'rev13 browser', root, *[_one(root, ref, name) for name in names])


def _manifest(report: Report) -> None:
    '''V3: the served command manifest lists the 18 commands of 10.21.4 with backup_folder_children and the new cells.

    Args:
        report: the findings collector.

    Returns:
        None.
    '''
    if len(b4base.COMMANDS) != COMMANDS13:
        report.env.append('V3 rev13: the shared list b4base.COMMANDS holds %d commands, the harness expects %d' % (len(b4base.COMMANDS), COMMANDS13))
        return
    root = vuechecks.deployed(report, 'V3 rev13 SPA endpoint')
    got = lan_try(report, 'V3 rev13 GET /command-manifest.json', root, 'GET', '/command-manifest.json') if root else None
    if got is None:
        return
    try:
        manifest = json.loads(got[2])
    except ValueError:
        manifest = None
    used = manifest.get('used') if isinstance(manifest, dict) else None
    unused = manifest.get('not_used') if isinstance(manifest, dict) else None
    if not isinstance(used, dict) or not isinstance(unused, list):
        report.product.append('V3 rev13 /command-manifest.json has no used object and not_used list')
        return
    listed = set(used) | set(unused)
    if listed != set(b4base.COMMANDS):
        report.product.append('V3 rev13 /command-manifest.json lists %d commands, expected the %d of 10.21.4 (missing %s, unexpected %s)'
                              % (len(listed), COMMANDS13, sorted(set(b4base.COMMANDS) - listed), sorted(listed - set(b4base.COMMANDS))))
    for command, params in MANIFEST13:
        cell = used.get(command)
        missing = [name for name in params if not isinstance(cell, dict) or name not in cell]
        if missing:
            report.product.append('V3 rev13 /command-manifest.json: the used set lacks %s with the parameters %s' % (command, missing))


def _calls(report: Report) -> None:
    '''V4 on revision 13: the unchanged cases of revisions 11 and 12 without L1 and L3 (replaced by 10.21.6), then the revision 13 cases.

    Args:
        report: the findings collector.

    Returns:
        None.
    '''
    vuechecks.removed_ui(report, ('U5', 'U6', 'U7', 'U8', 'U10'))
    vuechecks._actions_cases(report)
    root = vuechecks.deployed(report, 'V4 SPA endpoint')
    if root is None:
        return
    spa_files(report, 'V4 SPA sources')
    vuechecks.with_driver(report, 'V4 browser', root, vuebrowser.table_cases, vuebrowser.page_equals_result, *[vue11._case(root, name) for name in KEPT11])
    vue12._driven(report, 'open_section')
    _driven(report, *V4_CASES)


def _block(text: str, name: str) -> str:
    '''Return the text of one top-level describe block of a Vitest file (up to the next describe), or ''.

    Args:
        text: the test file.
        name: the group name.

    Returns:
        The block text.
    '''
    found = re.search(r'describe\(\s*[\'"`]%s[\'"`]' % re.escape(name), text)
    if found is None:
        return ''
    rest = text[found.end():]
    after = re.search(r'\ndescribe\(', rest)
    return rest[:after.start()] if after else rest


def _groups(report: Report) -> None:
    '''V6: the Vitest groups foldertree, treekeys, breadcrumb exist and the group filters carries the scope keys fs, fd, fp, rec.

    Args:
        report: the findings collector.

    Returns:
        None.
    '''
    found: set[str] = set()
    filters = ''
    for item in tracked_files() or []:
        if item.startswith('frontend/') and '.test.' in item:
            try:
                text = open(vuechecks.ROOT / item, encoding='utf-8').read()
            except OSError:
                continue
            found |= set(vuebuild.DESCRIBE.findall(text))
            filters += _block(text, 'filters')
    missing = [name for name in GROUPS13 if name not in found]
    if missing:
        report.product.append('V6 rev13 the Vitest describe groups %s do not exist in the tracked frontend tests (found %s)' % (missing, sorted(found)))
    absent = [key for key in FILTER_SCOPE if not re.search(r'\b%s\b' % key, filters)]
    if not filters or absent:
        report.product.append('V6 rev13 the Vitest group filters is not extended: no case names the scope hash keys %s (scope round trip, omitted-key rule, inconsistent combinations dropped, rec flag)' % absent)
    report.info.append('V6 rev13 sha256 of the group list: %s' % hashlib.sha256(','.join(sorted(found)).encode()).hexdigest()[:12])


def vue_folder_tree() -> None:
    '''V12: the live Playwright cases L16-L27 and the four stub cases of the folder tree on '#/'.

    Returns:
        None.
    '''
    report = Report()
    if live.service_state() != 'S1':
        report.state.append('V12 the folder tree cases need an S1 service (indexed snapshots)')
    else:
        _driven(report, *CASES)
    report.finish('vue_folder_tree')


def vue_command_contract() -> None:
    '''V3 on revision 13: the revision 12 body and the manifest of 18 commands.

    Returns:
        None.
    '''
    compose('vue_command_contract', vue12.vue_command_contract, _manifest)


def vue_command_calls() -> None:
    '''V4 on revision 13: the calls of the main page of 10.21.6.

    Returns:
        None.
    '''
    compose('vue_command_calls', None, _calls)


def vue_build() -> None:
    '''V6 on revision 13: the revision 12 body and the Vitest groups of 10.21.6.

    Returns:
        None.
    '''
    compose('vue_build', vue12.vue_build, _groups)
