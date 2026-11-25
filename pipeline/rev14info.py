'''Revision 14 info manual cases (matrix TODO 10.22.9 TM9, 10.22.5 item 10, TR1; row M2 info; block MODEL-REV14): the second half of rev14docs.

Cases tm9_info_toc (the description of info says table of contents, page 1 lists the last page 'Recipes for a model' and marks the operator pages),
tm9_recipes_page (the last page is English and names the commands, the words and the naming table), tm9_pages_kept (pages 2..45 keep their 0.3.27
titles, rev14titles, and the manual has at least 46 pages) and tr_info_run_recipe (the recipe why did the last run fail). The helpers and the
constants are those of rev14docs; the cases are routed by rev14docs.execute.
'''

from __future__ import annotations

import re
from collections.abc import Callable

from pipeline.report import Report
from pipeline.rev14docs import MAX_PAGE_BYTES, NAMING, RECIPE_NAMES, RECIPE_WORDS, RECIPES, _ask, _meta
from pipeline.rev14titles import TITLES_0327


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


INFO_CASES: dict[str, tuple[str, Callable[[Report, str], None]]] = {
    'tm9_info_toc': ('M2', info_toc), 'tm9_recipes_page': ('M2', info_recipes), 'tm9_pages_kept': ('M2', info_pages), 'tr_info_run_recipe': ('M2', run_recipe),
}
