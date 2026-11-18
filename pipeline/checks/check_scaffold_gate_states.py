'''scaffold_gate_states: scaffold state S0 or ready state S1 follows host directory, secrets and mount (PL3, R16).

Mode: script fixture plus catalog fixture. Start: with a correct plain host data directory the container
is started with ONEDRIVE_SCAFFOLD_MODE=0 when the secrets exist and with ONEDRIVE_SCAFFOLD_MODE=1 when
rclone.conf or restic-password is missing; in both cases the host data directory is the one bound at /data
(never a scaffold directory). Catalog gate: scaffold, an unmounted /data, a missing repository and an
open password file each refuse with 503 and a message that names the cause, the four messages differ,
and a healthy storage answers.
'''

from __future__ import annotations

from pathlib import Path

from pipeline import fixtures
from pipeline.report import Report

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / 'packaging' / 'docker-run.sh'
GATES = (('scaffold flag', {'scaffold': True}), ('storage not mounted', {'mount_plain_dir': True}),
         ('repository missing', {'repository': False}), ('password file too open', {'password_mode': 0o644}))


def _run_option(call: list[str], name: str) -> str | None:
    for index, item in enumerate(call):
        if item == '--env' and index + 1 < len(call) and call[index + 1].startswith(name + '='):
            return call[index + 1].split('=', 1)[1]
    return None


def _data_source(call: list[str]) -> str | None:
    for item in call:
        if item.startswith('type=bind,src=') and item.endswith(',dst=/data'):
            return item[len('type=bind,src='):-len(',dst=/data')]
    return None


def _start_case(report: Report, label: str, host: fixtures.Host, expected_mode: str) -> None:
    result = host.run(SCRIPT, 'start')
    runs = result.docker('run')
    if result.rc != 0 or not runs:
        report.product.append('start (%s): exit %d, container started %s, stderr: %s'
                              % (label, result.rc, bool(runs), result.err.strip()))
        return
    mode = _run_option(runs[0], 'ONEDRIVE_SCAFFOLD_MODE')
    if mode != expected_mode:
        report.product.append('start (%s): ONEDRIVE_SCAFFOLD_MODE=%s, expected %s' % (label, mode, expected_mode))
    if _data_source(runs[0]) != str(host.data):
        report.product.append('start (%s): /data is bound from %s, expected the host data directory %s'
                              % (label, _data_source(runs[0]), host.data))


def run() -> None:
    '''Raise CheckFailure when the state of the gate does not follow its inputs.'''
    report = Report()
    with fixtures.host() as host:
        _start_case(report, 'all inputs present', host, '0')
    for missing in ('restic-password', 'rclone.conf'):
        with fixtures.host() as host:
            (host.secrets / missing).unlink()
            _start_case(report, 'secret %s missing' % missing, host, '1')
    messages: dict[str, str] = {}
    for label, options in GATES:
        with fixtures.catalog_fixture(**options) as fx:
            status, value = fx.call(fx.catalog.snapshots, 10)
            messages[label] = str(value)
            if status != 503:
                report.product.append('gate %s: answered %s (%s), expected 503' % (label, status, value))
    if len(set(messages.values())) < len(messages):
        report.product.append('gates of different causes answer with the same message: %s' % messages)
    with fixtures.catalog_fixture() as fx:
        status, value = fx.call(fx.catalog.snapshots, 10)
        if status != 'ok':
            report.product.append('healthy storage must answer: %s %s' % (status, value))
    report.finish('scaffold_gate_states')
