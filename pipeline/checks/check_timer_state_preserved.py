'''timer_state_preserved: the daily timer keeps its state over a package upgrade (TODO 70425f95, row PL13, block TIMER-PRESERVE).

Mode: script fixture over COPIES of packaging/prerm and packaging/postinst with every absolute host path redirected into a
temporary tree and a stateful systemctl stub (pipeline.timerfix); nothing of the real host is read or written, no container and no
service is touched. The scripts run in dpkg order. T1 upgrade (prerm upgrade <new>, then postinst configure <old>) of a host on
which onedrive-backup.timer is enabled and active: the timer is enabled and active afterwards. T2 upgrade of a host whose timer is
disabled leaves it disabled and inactive (an upgrade never enables it). T3 remove (prerm remove) of an enabled and active timer
disables and stops it. T4 a fresh install (postinst configure, no previous version, no unit state) leaves the timer disabled and
inactive and never calls enable or start for it. A failing prerm or postinst is itself RED.
'''

from __future__ import annotations

from pipeline import timerfix
from pipeline.report import Report

PRERM = 'packaging/prerm'


def _line(needle: str) -> str:
    '''Return packaging/prerm:<line> of the first line that holds needle (the cause of a RED), or the file name alone.'''
    for number, text in enumerate((timerfix.PRERM).read_text(encoding='utf-8').splitlines(), 1):
        if needle in text:
            return '%s:%d (%s)' % (PRERM, number, text.strip())
    return PRERM


def _ran(report: Report, label: str, result) -> bool:
    '''Record a failing maintainer script run as a finding; return True when it exited 0.'''
    if result.rc != 0:
        report.product.append('%s: exit %d, stderr %r' % (label, result.rc, result.err.strip()[:200]))
    return result.rc == 0


def _upgrade(report: Report) -> None:
    for label, before in (('T1 upgrade of an enabled and active timer', (True, True)), ('T2 upgrade of a disabled timer', (False, False))):
        with timerfix.Packaging() as host:
            if host.survivors:
                report.env.append('%s: the script copies still name the host paths %s after the rewrite; not run' % (label, host.survivors))
                return
            host.set_units(timer=before, api=(True, True))
            stopped = host.package_step('prerm', 'upgrade', '0.3.20')
            after_prerm = host.unit_state(timerfix.TIMER)
            configured = host.package_step('postinst', 'configure', '0.3.19')
            ok = _ran(report, label + ' prerm upgrade', stopped) & _ran(report, label + ' postinst configure', configured)
            now = host.unit_state(timerfix.TIMER)
            if ok and now != before:
                report.product.append('%s: after prerm upgrade (timer enabled %s, active %s) and postinst configure the timer is enabled %s, active %s, '
                                      'expected enabled %s, active %s; cause %s' % (label, after_prerm[0], after_prerm[1], now[0], now[1],
                                                                                    before[0], before[1], _line('disable --now')))


def _remove(report: Report) -> None:
    with timerfix.Packaging() as host:
        if host.survivors:
            report.env.append('T3 remove: the script copies still name the host paths %s after the rewrite; not run' % host.survivors)
            return
        host.set_units(timer=(True, True), api=(True, True))
        if _ran(report, 'T3 prerm remove', host.package_step('prerm', 'remove')):
            now = host.unit_state(timerfix.TIMER)
            if now != (False, False):
                report.product.append('T3 remove of an enabled and active timer leaves it enabled %s, active %s, expected disabled and inactive' % now)


def _fresh(report: Report) -> None:
    with timerfix.Packaging() as host:
        if host.survivors:
            report.env.append('T4 fresh install: the script copies still name the host paths %s after the rewrite; not run' % host.survivors)
            return
        if _ran(report, 'T4 postinst configure of a fresh install', host.package_step('postinst', 'configure')):
            now = host.unit_state(timerfix.TIMER)
            if now != (False, False):
                report.product.append('T4 a fresh install leaves the timer enabled %s, active %s, expected disabled and inactive' % now)
            started = [call for call in host.calls_naming(timerfix.TIMER) if call and call[0] in ('enable', 'start', 'restart')]
            if started:
                report.product.append('T4 a fresh install calls systemctl %s for the timer' % started)


def run() -> None:
    '''Raise CheckFailure when an upgrade drops the timer state, a remove keeps the timer, or a fresh install enables it.'''
    report = Report()
    _upgrade(report)
    _remove(report)
    _fresh(report)
    report.finish('timer_state_preserved')
