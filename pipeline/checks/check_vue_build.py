'''vue_build: UI-VUE named check, revision 11 adds the Vitest groups filters, autocomplete, datelabel and service-sections (logic in pipeline.vue11, rows V6, V9).'''

from __future__ import annotations

from pipeline import vue13


def run() -> None:
    '''Raise CheckFailure when the check is RED (revision 13 adds the Vitest groups foldertree, treekeys, breadcrumb and the extended filters, rows V6, V12).

    Returns:
        None.
    '''
    vue13.vue_build()
