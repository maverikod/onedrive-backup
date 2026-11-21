'''Probe P1 record and product comparison of the DUP-KEEP-REV10 live checks (rows BE2 and BE4, matrix TODO 10.17.11 (1) and (4)).

pipeline/probe_p1.json is the data file of probe P1 (taken read-only on the deployed 0.3.20, 2026-11-21): the two collision groups
of library 1, folder ЭКСПОРТ/Экспорт Анна/Акты Полынько/Новая папка/Telegram Desktop, with the exact names (NFC against NFD), Graph item
ids, sizes and quickXorHash values, the rule that the pair obeys (10.17.2 (b)) and the entries the 0.3.20 snapshot holds for them.
'''

from __future__ import annotations

import json
import unicodedata
from pathlib import Path
from typing import Any

DATA = Path(__file__).resolve().with_name('probe_p1.json')


def load() -> dict[str, Any]:
    '''Return the parsed probe record; raise OSError or ValueError when it is missing or malformed.'''
    data = json.loads(DATA.read_text(encoding='utf-8'))
    if not isinstance(data, dict) or not isinstance(data.get('groups'), list):
        raise ValueError('pipeline/probe_p1.json holds no groups')
    return data


def rule_of(names: list[str]) -> str:
    '''Which cause of 10.17.2 makes the names collide: a identical, b NFC, c case folding, d none of them (extension or something else).'''
    if len(set(names)) == 1:
        return 'a'
    composed = {unicodedata.normalize('NFC', name) for name in names}
    if len(composed) == 1:
        return 'b'
    return 'c' if len({name.casefold() for name in composed}) == 1 else 'd'


def extension(name: str) -> str:
    '''The case-folded extension of a name (empty without a dot).'''
    return name.rpartition('.')[2].casefold() if '.' in name else ''


def group_ids(data: dict[str, Any]) -> dict[str, str]:
    '''{item id: name} of every member of every recorded group.'''
    return {member['item_id']: member['name'] for group in data['groups'] for member in group['members']}
