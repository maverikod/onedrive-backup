'''Revision 14 help and info text contract (matrix TODO 10.22.9 TM9, TM10, 10.22.5 items 1, 5, 8, 10, 11, 13, 14; rows M1 help and M2 info; block MODEL-REV14).

The cases are executed against the live help and info answers: the usage examples and the 404 hint of backup_prepare_download, the new parameter
names, the 'LOCAL calendar days' text of every dates parameter, the dry-run sentence of backup_schedule_set, the display_name of
backup_sites_list, the documented return keys of backup_download_begin, backup_download_status and backup_discovery_status (set inclusion of the
keys of a live answer), the 20 commands of help {}, the start_here / tool_info.description entry, the description of info ('table of contents'),
the appended last info page 'Recipes for a model' and the frozen titles of pages 2..45 (rev14titles). Tester assumptions: the help text of a
changed command names `cmdname` (direct call) and `MCP Proxy` (the proxy's `command` argument); the recipes page has at most 16384 bytes.
The cases are routed from cmdcases._execute (check cmd_help, cmd_info) and all of them run in the check help_text_contract.
'''

from __future__ import annotations

import re
from collections.abc import Callable, Iterator
from typing import Any

from pipeline import b4base, cmdcases, live
from pipeline.report import Report
from pipeline.rev14titles import TITLES_0327

RECIPES = 'Recipes for a model'
CHANGED = ('backup_snapshots', 'backup_list_files', 'backup_prepare_download', 'backup_download_status', 'backup_filter_options',
           'backup_search_files', 'backup_suggest_names', 'backup_folder_children')
NEW_PREPARE = ('file_id', 'site_id', 'drive_id', 'dir', 'name', 'copy_index', 'inline_max_bytes')
DATES_DOCS = {'backup_search_files': ('dates_mode', 'collapse', 'order_by', 'fields'), 'backup_suggest_names': ('dates_mode',),
              'backup_folder_children': ('dates_mode', 'collapse')}
KEY_DOCS = ('backup_download_begin', 'backup_download_status', 'backup_discovery_status')
RECIPE_NAMES = ('backup_search_files', 'backup_prepare_download', 'backup_download_chunk', 'backup_delete_export')
RECIPE_WORDS = ('snapshot', 'run', 'backup date', 'backup type')
NAMING = ('site_ids', 'site_id', 'prefix', 'file_path', 'dir')
MAX_PAGE_BYTES = 16384


def _strings(value: Any) -> Iterator[str]:
    '''Yield every string value of a nested structure.

    Args:
        value: a string, dict, list or anything else.

    Returns:
        An iterator of the strings found.
    '''
    if isinstance(value, str):
        yield value
    elif isinstance(value, dict):
        for item in value.values():
            yield from _strings(item)
    elif isinstance(value, list):
        for item in value:
            yield from _strings(item)


def _text(value: Any) -> str:
    '''Join every string value of a structure.

    Args:
        value: the structure.

    Returns:
        The strings joined by one space.
    '''
    return ' '.join(_strings(value))


def _ask(report: Report, desc: str, command: str, params: dict) -> Any:
    '''Send one command; a product finding and None unless it answers a success dict.

    Args:
        report: the findings collector.
        desc: the case description.
        command: the command name.
        params: its parameters.

    Returns:
        The success data, or None after a finding.
    '''
    kind, code, message, data = live.request(command, params)
    if kind != 'success' or not isinstance(data, dict):
        report.product.append('%s: %s %s answered %s, expected success data' % (desc, command, params, cmdcases._brief(kind, code, message, data)))
        return None
    return data


def _meta(report: Report, desc: str, cmdname: str) -> dict:
    '''Read the help metadata of one command.

    Args:
        report: the findings collector.
        desc: the case description.
        cmdname: the command name.

    Returns:
        The metadata dict, empty after a finding.
    '''
    data = _ask(report, desc, 'help', {'cmdname': cmdname})
    meta = data.get('metadata') if data is not None else None
    return meta if isinstance(meta, dict) else {}


def _documented(meta: dict) -> set[str]:
    '''Return the keys the help documents for the success answer.

    Args:
        meta: the help metadata.

    Returns:
        The documented keys, empty when there is no data block.
    '''
    data = ((meta.get('return_value') or {}).get('success') or {}).get('data')
    return set(data) if isinstance(data, dict) else set()


def help_lists_20(report: Report, desc: str) -> None:
    '''TM9: help {} lists exactly the 20 commands of the inventory.

    Args:
        report: the findings collector.
        desc: the case description.

    Returns:
        None.
    '''
    data = _ask(report, desc, 'help', {})
    if data is None:
        return
    names = sorted(data['commands']) if isinstance(data.get('commands'), dict) else []
    wanted = sorted(b4base.COMMANDS)
    if names != wanted or len(wanted) != 20:
        report.product.append('%s: help {} lists %d commands, expected the %d of the inventory; missing %s, unexpected %s'
                              % (desc, len(names), len(wanted), sorted(set(wanted) - set(names)), sorted(set(names) - set(wanted))))


def start_here(report: Report, desc: str) -> None:
    '''TM9: help {} carries start_here (fallback tool_info.description) naming info and the recipes page; every changed help names cmdname and MCP Proxy.

    Args:
        report: the findings collector.
        desc: the case description.

    Returns:
        None.
    '''
    data = _ask(report, desc, 'help', {})
    if data is None:
        return
    entry = data.get('start_here')
    where = 'start_here' if entry is not None else 'tool_info.description (the fallback of 10.22.13 (8))'
    text = _text(entry) if entry is not None else _text((data.get('tool_info') or {}).get('description'))
    if not (re.search('(^|[^a-z_])info([^a-z_]|$)', text) and RECIPES.lower() in text.lower()):
        report.product.append('%s: %s reads %r, expected it to name the command info and the page %r' % (desc, where, text[:100], RECIPES))
    lacking = [name for name in CHANGED if not all(word in _text(_meta(report, desc, name)) for word in ('cmdname', 'MCP Proxy'))]
    if lacking:
        report.product.append('%s: the help of %s names neither cmdname (direct call) nor MCP Proxy (the proxy command argument) together' % (desc, lacking))


def prepare_examples(report: Report, desc: str) -> None:
    '''TM9: examples with a sharepoint/ path and a file_id, no Documents/example.txt, the 404 hint names backup_search_files, the new parameters.

    Args:
        report: the findings collector.
        desc: the case description.

    Returns:
        None.
    '''
    meta = _meta(report, desc, 'backup_prepare_download')
    commands: list[dict[str, Any]] = [item['command'] for item in meta.get('usage_examples') or [] if isinstance(item, dict) and isinstance(item.get('command'), dict)]
    paths = [command.get('file_path') for command in commands]
    if not any(isinstance(path, str) and path.startswith('sharepoint/') for path in paths):
        report.product.append('%s: no usage example has a file_path starting sharepoint/ (example paths %s)' % (desc, paths))
    if not any('file_id' in command for command in commands):
        report.product.append('%s: no usage example addresses the file by file_id' % desc)
    if 'Documents/example.txt' in paths:
        report.product.append('%s: the example file_path Documents/example.txt is still shown (it is no path of a backup)' % desc)
    solution = str(((meta.get('error_cases') or {}).get('404') or {}).get('solution', ''))
    if 'backup_search_files' not in solution:
        report.product.append('%s: the 404 solution reads %r, expected it to name backup_search_files' % (desc, solution))
    absent = [name for name in NEW_PREPARE if name not in (meta.get('parameters') or {})]
    if absent:
        report.product.append('%s: the help parameters %s lack %s' % (desc, sorted(meta.get('parameters') or {}), absent))


def dates_text(report: Report, desc: str) -> None:
    '''TM9: every dates parameter text says LOCAL calendar days, timezone and UTC; the new parameters are documented.

    Args:
        report: the findings collector.
        desc: the case description.

    Returns:
        None.
    '''
    for name, wanted in DATES_DOCS.items():
        parameters = _meta(report, desc, name).get('parameters') or {}
        text = _text(parameters.get('dates'))
        lacking = [word for word in ('LOCAL calendar days', 'timezone', 'UTC') if word not in text]
        if lacking:
            report.product.append('%s: the dates text of %s reads %r, it lacks %s' % (desc, name, text[:120], lacking))
        absent = [item for item in wanted if item not in parameters]
        if absent:
            report.product.append('%s: the help of %s does not document %s' % (desc, name, absent))


def schedule_set_dry_run(report: Report, desc: str) -> None:
    '''TM9: the help of backup_schedule_set says a dry run never changes the stored revision.

    Args:
        report: the findings collector.
        desc: the case description.

    Returns:
        None.
    '''
    text = _text(_meta(report, desc, 'backup_schedule_set')).lower()
    lacking = [word for word in (('dry run', 'dry_run'), ('never change',), ('stored revision',)) if not any(item in text for item in word)]
    if lacking:
        report.product.append('%s: the help of backup_schedule_set does not say that a dry run never changes the stored revision (lacks %s)' % (desc, lacking))


def sites_list_display_name(report: Report, desc: str) -> None:
    '''TM10: the help of backup_sites_list names display_name as the live answer does.

    Args:
        report: the findings collector.
        desc: the case description.

    Returns:
        None.
    '''
    text = _text(_meta(report, desc, 'backup_sites_list').get('return_value'))
    data = _ask(report, desc, 'backup_sites_list', {'limit': 1})
    items = data.get('items') if data is not None else None
    keys = sorted(items[0]) if isinstance(items, list) and items and isinstance(items[0], dict) else []
    if 'display_name' not in text:
        report.product.append('%s: the help return_value reads %r, expected it to name display_name (the live item keys are %s)' % (desc, text[:150], keys))


def _live_answers(report: Report, desc: str) -> dict[str, Any]:
    '''Read live answers of the three commands, staging and deleting one small export.

    Args:
        report: the findings collector.
        desc: the case description.

    Returns:
        The answers keyed by command name.
    '''
    answers: dict[str, Any] = {}
    data = _ask(report, desc, 'backup_discovery_status', {})
    if data is not None:
        answers['backup_discovery_status'] = data
    staged = cmdcases._prepare_small(report, desc)
    if staged is None:
        return answers
    export_id = staged[2].get('export_id')
    try:
        for command in ('backup_download_status', 'backup_download_begin'):
            data = _ask(report, desc, command, {'export_id': export_id})
            if data is not None:
                answers[command] = data
    finally:
        kind, code, message, body = live.request('backup_delete_export', {'export_id': export_id})
        if kind != 'success':
            report.product.append('%s: backup_delete_export of the staged export %s answered %s' % (desc, export_id, cmdcases._brief(kind, code, message, body)))
    return answers


def documented_keys(report: Report, desc: str) -> None:
    '''TM10: every key of a live answer of download_begin, download_status and discovery_status is documented in the help return_value.

    Args:
        report: the findings collector.
        desc: the case description.

    Returns:
        None.
    '''
    answers = _live_answers(report, desc)
    for command in KEY_DOCS:
        if command not in answers:
            continue
        documented = _documented(_meta(report, desc, command))
        undocumented = sorted(set(answers[command]) - documented)
        if undocumented:
            report.product.append('%s: the live answer of %s has the keys %s, the help documents %s; undocumented %s'
                                  % (desc, command, sorted(answers[command]), sorted(documented), undocumented))


def info_toc(report: Report, desc: str) -> None:
    '''TM9: the description of info says table of contents, page 1 lists the last page 'Recipes for a model' and marks the operator pages.

    Args:
        report: the findings collector.
        desc: the case description.

    Returns:
        None.
    '''
    listing = _ask(report, desc, 'help', {})
    listed = str(((listing or {}).get('commands') or {}).get('info', ''))
    meta = _meta(report, desc, 'info')
    described = ' '.join([listed, str(meta.get('summary', '')), str(meta.get('detailed_description', ''))]).lower()
    if 'table of contents' not in listed.lower():
        report.product.append('%s: help {} describes info as %r, expected it to say table of contents' % (desc, listed))
    if 'full contents' in described:
        report.product.append('%s: the description of info still says full contents (%r)' % (desc, listed))
    first = _ask(report, desc, 'info', {})
    if first is None:
        return
    content = str(first.get('content', ''))
    if RECIPES not in content:
        report.product.append('%s: page 1 does not list the page %r (%d pages)' % (desc, RECIPES, first.get('total_pages') or 0))
    if 'operator' not in content.lower():
        report.product.append('%s: page 1 marks no installation/ops page as operator' % desc)


def _last_page(report: Report, desc: str) -> dict | None:
    '''Read the last info page and require its title.

    Args:
        report: the findings collector.
        desc: the case description.

    Returns:
        The last page answer, or None after a finding.
    '''
    first = _ask(report, desc, 'info', {})
    total = first.get('total_pages') if first is not None else None
    if type(total) is not int:
        return None
    last = _ask(report, desc, 'info', {'page': total})
    if last is not None and last.get('title') != RECIPES:
        report.product.append('%s: the last page %d of %d is titled %r, expected %r (appended at the END)' % (desc, total, total, last.get('title'), RECIPES))
        return None
    return last


def info_recipes(report: Report, desc: str) -> None:
    '''TM9: the last page is English and names the commands, the words and the naming table.

    Args:
        report: the findings collector.
        desc: the case description.

    Returns:
        None.
    '''
    last = _last_page(report, desc)
    if last is None:
        return
    content = str(last.get('content', ''))
    lowered = content.lower()
    letters = len(re.findall('[A-Za-zЀ-ӿ]', content))
    if len(re.findall('[Ѐ-ӿ]', content)) > 0.02 * max(letters, 1):
        report.product.append('%s: the recipes page is not English (Cyrillic letters in %d letters)' % (desc, letters))
    lacking = [name for name in RECIPE_NAMES + NAMING if name not in content]
    lacking += [word for word in RECIPE_WORDS if not re.search('(^|[^a-z])%s([^a-z]|$)' % word, lowered)]
    if lacking:
        report.product.append('%s: the recipes page lacks %s' % (desc, lacking))
    if len(content.encode('utf-8')) > MAX_PAGE_BYTES:
        report.product.append('%s: the recipes page has %d bytes, the limit of a page is %d' % (desc, len(content.encode('utf-8')), MAX_PAGE_BYTES))


def info_pages(report: Report, desc: str) -> None:
    '''TM9: pages 2..45 keep their 0.3.27 titles and numbers, the recipes page is appended.

    Args:
        report: the findings collector.
        desc: the case description.

    Returns:
        None.
    '''
    first = _ask(report, desc, 'info', {})
    total = first.get('total_pages') if first is not None else None
    if type(total) is not int:
        return
    if total < len(TITLES_0327) + 2:
        report.product.append('%s: the manual has %d pages, expected at least %d (the 45 of 0.3.27 plus the appended recipes page)' % (desc, total, len(TITLES_0327) + 2))
    moved = {}
    for page, title in TITLES_0327.items():
        answer = _ask(report, desc, 'info', {'page': page}) if page <= total else {}
        if (answer or {}).get('title') != title:
            moved[page] = (answer or {}).get('title')
    if moved:
        report.product.append('%s: pages whose title is not the 0.3.27 title: %s' % (desc, moved))


def run_recipe(report: Report, desc: str) -> None:
    '''TR1: the recipes page explains refused / errors / ok and the recipe why the last run failed.

    Args:
        report: the findings collector.
        desc: the case description.

    Returns:
        None.
    '''
    last = _last_page(report, desc)
    if last is None:
        return
    content = str(last.get('content', ''))
    lacking = [word for word in ('backup_schedule_status', 'reason', 'backup_run_log', 'refused', 'errors', 'tail') if word not in content]
    if lacking:
        report.product.append('%s: the recipes page lacks %s of the recipe why did the last run fail' % (desc, lacking))


CASES: dict[str, tuple[str, Callable[[Report, str], None]]] = {
    'tm9_help_lists_20': ('M1', help_lists_20), 'tm9_start_here': ('M1', start_here), 'tm9_prepare_examples': ('M1', prepare_examples),
    'tm9_dates_text': ('M1', dates_text), 'tm9_schedule_set_dry_run': ('M1', schedule_set_dry_run),
    'tm10_sites_list_display_name': ('M1', sites_list_display_name), 'tm10_documented_keys': ('M1', documented_keys),
    'tm9_info_toc': ('M2', info_toc), 'tm9_recipes_page': ('M2', info_recipes), 'tm9_pages_kept': ('M2', info_pages),
    'tr_info_run_recipe': ('M2', run_recipe),
}


def execute(report: Report, row_id: str, cid: str, desc: str) -> None:
    '''Execute one revision 14 case of the rows M1 and M2 (routed from cmdcases._execute).

    Args:
        report: the findings collector.
        row_id: the matrix row id.
        cid: the case id.
        desc: the case description.

    Returns:
        None.
    '''
    entry = CASES.get(cid)
    if entry is None or entry[0] != row_id:
        report.product.append('%s: no revision 14 executor for the case %s of row %s' % (desc, cid, row_id))
        return
    try:
        entry[1](report, desc)
    except live.LiveUnreachable as exc:
        report.env.append('%s: not executed, production service unreachable: %s' % (desc, exc))


def help_text_contract(name: str) -> None:
    '''Run every revision 14 case of M1 and M2 and finish the report (check help_text_contract).

    Args:
        name: the name of the named check.

    Returns:
        None.
    '''
    report = Report()
    for cid, (row_id, _) in CASES.items():
        before = len(report.product) + len(report.state) + len(report.env)
        execute(report, row_id, cid, '%s %s' % (row_id, cid))
        report.info.append('%s %s: %s' % (row_id, cid, 'GREEN' if len(report.product) + len(report.state) + len(report.env) == before else 'RED'))
    report.finish(name)
