'''Disposable host of the timer-state check: runs COPIES of packaging/prerm and packaging/postinst over a stateful systemctl stub.

The Debian maintainer scripts name /run/systemd/system as the test "systemd is running"; the copies redirect it to a directory
of the temporary tree that exists, so every systemctl call reaches the stub of pipeline.host_stubs, which keeps the enabled and the
active state of each unit in a JSON file (STUB_UNITS). The real host is never read or written; every other host path of the
postinst is redirected as in pipeline.postinstfix.
'''

from __future__ import annotations

import json
from pathlib import Path

from pipeline import archivefs, postinstfix

PRERM = postinstfix.ROOT / 'packaging' / 'prerm'
TIMER = 'onedrive-backup.timer'
API = 'onedrive-backup-api.service'


class Packaging(postinstfix.Postinst):
    '''A temporary host on which prerm and postinst run in dpkg order with systemd present.'''

    def __init__(self) -> None:
        super().__init__()
        (self.tmp / 'no-systemd').mkdir()
        self.units = self.tmp / 'units.json'
        self.extra_env['STUB_UNITS'] = str(self.units)
        self.prerm = self.tmp / 'prerm'
        text = archivefs.rewrite(PRERM.read_text(encoding='utf-8'), self.mapping)
        self.prerm.write_text(text, encoding='utf-8')
        self.survivors = self.survivors + archivefs.leftovers(text)
        self.data.mkdir(mode=0o750)
        self.set_default(None)

    def set_units(self, **units: tuple[bool, bool]) -> None:
        '''Set the (enabled, active) state of units given by short name: timer, api.'''
        names = {'timer': TIMER, 'api': API}
        self.units.write_text(json.dumps({names[key]: {'enabled': flag[0], 'active': flag[1]} for key, flag in units.items()}), encoding='utf-8')

    def unit_state(self, unit: str) -> tuple[bool, bool]:
        '''Return (enabled, active) of a unit as the stub holds it; an unknown unit is (False, False).'''
        data = json.loads(self.units.read_text(encoding='utf-8')) if self.units.exists() else {}
        entry = data.get(unit, {})
        return bool(entry.get('enabled')), bool(entry.get('active'))

    def package_step(self, step: str, *args: str) -> postinstfix.Run:
        '''Run prerm (step prerm) or postinst (step postinst) with the dpkg arguments, for example prerm upgrade 0.3.20.'''
        return self.run(script=self.prerm if step == 'prerm' else self.script, args=args)

    def calls_naming(self, unit: str) -> list[list[str]]:
        '''Recorded systemctl calls that name unit, without the command name.'''
        return [call[1:] for call in self.calls_of_last() if call[0] == 'systemctl' and unit in call]

    def calls_of_last(self) -> list:
        '''The stub calls of the most recent run.'''
        return [json.loads(line) for line in self.log.read_text(encoding='utf-8').splitlines() if line]
