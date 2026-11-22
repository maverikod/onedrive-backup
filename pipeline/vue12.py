'''Revision 12 browser and static cases of the UI-VUE checks (matrix TODO 10.20.7 and 10.20.10, block SCHEDULE-REV12, row V11).

The schedule section '#/service?section=schedule' of the service page is driven through the headless driver of pipeline.vuebrowser. Every
locator is counted before it is used, so an SPA that lacks a test id is a PRODUCT finding and never a timeout. The named checks vue_*
compose the unchanged cases of pipeline.vue11 with these. SAFETY (10.20.7): the two cases that save a schedule (L14, L15) write only a
valid far-future schedule, never while a backup runs or is due within 15 minutes, and restore the original text in a finally.
'''

from __future__ import annotations

import hashlib
import json
from typing import Any, Callable

from pipeline import live, sched12_live, sched12_rows, vue11, vuebuild, vuechecks
from pipeline.checks import CheckFailure
from pipeline.report import Report
from pipeline.vuebase import lan_try, tracked_files
from pipeline.vuebrowser import SETTLE_MS, Session
from pipeline.vueroutes import pairs, tid

ROUTE = '#/service?section=schedule'
IDS = ('svc-tab-schedule', 'svc-schedule', 'schedule-text', 'schedule-check', 'schedule-save', 'schedule-reset', 'schedule-default', 'schedule-help',
       'schedule-state', 'schedule-thread', 'schedule-next-runs')
GROUPS12 = ('schedule-editor', 'schedule-problems', 'schedule-conflict', 'schedule-status', 'schedule-time')
COMMANDS12 = (('backup_schedule_get', ('next_count',)), ('backup_schedule_set', ('text', 'expected_revision', 'dry_run', 'next_count', 'actor')),
              ('backup_schedule_status', ('history_limit',)))
POLL_MS = 15000
STATUS_MARK_JS = (
    '(() => { const f = window.fetch; window.__statusDone = [];'
    ' window.fetch = function (...a) { const b = a[1] && typeof a[1].body === "string" ? a[1].body : "";'
    ' const p = f.apply(this, a); if (b.indexOf("backup_schedule_status") >= 0) {'
    ' p.then(() => window.__statusDone.push(Date.now()), () => undefined); } return p; }; })();'
)
vue11.ACTIONS.update({'backup_schedule_get': ((), ('next_count',), {}), 'backup_schedule_set': (('text',), ('expected_revision', 'dry_run', 'next_count', 'actor'), {}),
                      'backup_schedule_status': ((), ('history_limit',), {})})


def compose(name: str, old: Callable[[], None] | None, extra: Callable[[Report], None]) -> None:
    '''Run the unchanged check body and the revision 12 cases and raise one CheckFailure holding both results.

    Args:
        name: the named check.
        old: the body of the check before revision 12, or None.
        extra: the revision 12 cases, filling a report.

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
        extra: the revision 12 cases.

    Returns:
        None.
    '''
    report = Report()
    extra(report)
    report.finish(name + ' (revision 12)')


class Cases12(vue11.Cases):
    '''The revision 12 browser cases of one run (L10-L15 of 10.20.7).'''

    def present(self, label: str, page: Any, wait: bool = True) -> bool:
        '''Wait for the schedule section and PRODUCT finding unless every test id of the editor exists.

        Args:
            label: the case label.
            page: the page.
            wait: wait for the section element first.

        Returns:
            True when the ids exist.
        '''
        if wait:
            page.wait_for_timeout(SETTLE_MS)
        return self.have(label, page, IDS)

    def guard(self, label: str) -> tuple[str, str] | None:
        '''Return the original text and revision when a real write is allowed now (the safety rule), else a STATE finding.

        Args:
            label: the case label.

        Returns:
            The (text, revision) pair, or None.
        '''
        before = sched12_rows.call('backup_schedule_get', {})
        text, revision = before.get('text'), before.get('revision')
        if not isinstance(text, str) or not isinstance(revision, str) or before.get('valid') is not True:
            self.report.state.append('%s: no readable valid stored schedule (backup_schedule_get answered %s): the write case is not run' % (label, str(before)[:80]))
            return None
        if sched12_live._busy(sched12_rows.call('backup_schedule_status', {})):
            self.report.state.append('%s: a backup runs or is due within 15 minutes: the write case is not run (safety rule of 10.20.7)' % label)
            return None
        return text, revision

    def restore(self, text: str, revision: str) -> None:
        '''Restore the original text through the command and record an ENVIRONMENT finding when it is not back.

        Args:
            text: the original text.
            revision: the revision the stored text has now.

        Returns:
            None.
        '''
        stored = sched12_rows.call('backup_schedule_get', {}).get('revision')
        if stored != sched12_rows.digest(text):
            sched12_rows.call('backup_schedule_set', {'text': text, 'expected_revision': revision, 'actor': 'pipeline'})
        if sched12_rows.call('backup_schedule_get', {}).get('revision') != sched12_rows.digest(text):
            self.report.env.append('RESTORE FAILED: the original schedule is not back; restore the text by hand')

    def open_section(self) -> None:
        '''L10: opening the section sends exactly one backup_schedule_get {} and one backup_schedule_status {}.

        Returns:
            None.
        '''
        sess = Session(self.drv)
        try:
            sess.go(ROUTE)
            if self.present('V11 L10', sess.page):
                sent = sorted(pairs(sess), key=lambda item: item[0])
                if sent != [('backup_schedule_get', {}), ('backup_schedule_status', {})]:
                    self.bad('V11 L10 open: the page sent %s, expected exactly [backup_schedule_get {}, backup_schedule_status {}]' % pairs(sess))
        finally:
            sess.close()

    def check_one(self) -> None:
        '''L11 and L12: a check sends one dry run with the exact key set and changes no file; an invalid text shows its problem and disables save.

        Returns:
            None.
        '''
        sess = Session(self.drv)
        try:
            sess.go(ROUTE)
            page = sess.page
            if not self.present('V11 L11', page):
                return
            before = sched12_rows.call('backup_schedule_get', {}).get('revision')
            text = tid(page, 'schedule-text').input_value() + '# one more comment\n'
            tid(page, 'schedule-text').fill(text)
            start = len(sess.calls)
            tid(page, 'schedule-check').click()
            page.wait_for_timeout(SETTLE_MS)
            sent = pairs(sess, start)
            if sent != [('backup_schedule_set', {'text': text, 'dry_run': True, 'actor': 'spa'})] or sched12_rows.call('backup_schedule_get', {}).get('revision') != before:
                self.bad('V11 L11 check: the click sent %s and the revision is %s, expected one backup_schedule_set {text, dry_run true, actor spa} and the revision %s unchanged' % (sent, str(sched12_rows.call('backup_schedule_get', {}).get('revision'))[:12], str(before)[:12]))
            tid(page, 'schedule-text').fill('61 2 * * *')
            tid(page, 'schedule-check').click()
            page.wait_for_timeout(SETTLE_MS)
            items = page.locator('[data-testid=schedule-problem][data-code=CRON_RANGE]')
            if items.count() != 1 or items.first.get_attribute('data-line') != '1' or not tid(page, 'schedule-save').is_disabled():
                self.bad('V11 L12 61 2 * * *: %d schedule-problem with data-code CRON_RANGE (data-line %s), save disabled %s, expected one at line 1 and save disabled' % (items.count(), items.first.get_attribute('data-line') if items.count() else None, tid(page, 'schedule-save').is_disabled()))
        finally:
            sess.close()

    def poll(self) -> None:
        '''L13: no status call before 15 s, exactly one after, none after leaving the section and none after the logout.

        Returns:
            None.
        '''
        sess = Session(self.drv, clock=True)
        try:
            sess.page.add_init_script(STATUS_MARK_JS)
            sess.go(ROUTE)
            page = sess.page
            if not self.present('V11 L13', page):
                return
            marks = page.evaluate('window.__statusDone')
            if not marks:
                self.bad('V11 L13 poll: the page received no backup_schedule_status answer, the 15 s poll cannot be timed')
                return
            page.clock.pause_at(page.evaluate('Date.now()') + 500)
            since = page.evaluate('Date.now()') - marks[-1]
            start = len(sess.calls)
            page.clock.fast_forward(max(POLL_MS - 1000 - since, 1))
            page.wait_for_timeout(SETTLE_MS)
            early = [m for m, _ in pairs(sess, start)]
            page.clock.fast_forward(2000)
            page.wait_for_timeout(SETTLE_MS)
            late = [m for m, _ in pairs(sess, start)]
            if early or late != ['backup_schedule_status']:
                self.bad('V11 L13 poll: calls before 15 s %s and after %s, expected none and exactly one backup_schedule_status' % (early, late))
            tid(page, 'svc-tab-info').click()
            page.wait_for_timeout(SETTLE_MS)
            left = len(sess.calls)
            page.clock.fast_forward(60000)
            page.wait_for_timeout(SETTLE_MS)
            if [m for m, _ in pairs(sess, left) if m.startswith('backup_schedule')]:
                self.bad('V11 L13: a schedule command is still sent after the section was left: %s' % pairs(sess, left))
            page.clock.resume()
            sess.go(ROUTE)
            page.wait_for_timeout(SETTLE_MS)
            if tid(page, 'logout').count() == 1:
                tid(page, 'logout').click()
                page.wait_for_timeout(SETTLE_MS)
                after = len(sess.calls)
                page.clock.fast_forward(120000)
                page.wait_for_timeout(SETTLE_MS)
                if len(sess.calls) != after:
                    self.bad('V11 L13 logout: %s sent after the logout, expected zero calls' % pairs(sess, after))
        finally:
            sess.close()

    def save(self) -> None:
        '''L14: a far-future schedule written through the UI sends the exact key set and shows the note; the original is restored.

        Returns:
            None.
        '''
        kept = self.guard('V11 L14')
        if kept is None:
            return
        sess = Session(self.drv)
        new = sched12_rows.far_future(str(sched12_rows.call('backup_schedule_get', {}).get('timezone') or 'Europe/Kyiv'))
        try:
            sess.go(ROUTE)
            page = sess.page
            if not self.present('V11 L14', page):
                return
            loaded = tid(page, 'schedule-text').get_attribute('data-raw')
            tid(page, 'schedule-text').fill(new)
            tid(page, 'schedule-check').click()
            page.wait_for_timeout(SETTLE_MS)
            start = len(sess.calls)
            tid(page, 'schedule-save').click()
            page.wait_for_timeout(SETTLE_MS)
            sent = pairs(sess, start)
            saved = tid(page, 'schedule-saved')
            if sent != [('backup_schedule_set', {'text': new, 'expected_revision': loaded, 'actor': 'spa'})] or saved.count() != 1 or saved.first.get_attribute('data-raw') != sched12_rows.digest(new):
                self.bad('V11 L14 save: the click sent %s and schedule-saved is %d, expected one backup_schedule_set {text, expected_revision %s, actor spa} and the note with the new revision' % (sent, saved.count(), str(loaded)[:12]))
        finally:
            sess.close()
            self.restore(kept[0], sched12_rows.digest(new))

    def conflict(self) -> None:
        '''L15: a change made through the command after the editor loaded gives the conflict banner and is not overwritten; the original is restored.

        Returns:
            None.
        '''
        kept = self.guard('V11 L15')
        if kept is None:
            return
        zone = str(sched12_rows.call('backup_schedule_get', {}).get('timezone') or 'Europe/Kyiv')
        other, mine = sched12_rows.far_future(zone), sched12_rows.far_future(zone).replace('0 4 ', '0 5 ')
        sess = Session(self.drv)
        try:
            sess.go(ROUTE)
            page = sess.page
            if not self.present('V11 L15', page):
                return
            sched12_rows.call('backup_schedule_set', {'text': other, 'expected_revision': kept[1], 'actor': 'pipeline'})
            tid(page, 'schedule-text').fill(mine)
            tid(page, 'schedule-check').click()
            page.wait_for_timeout(SETTLE_MS)
            tid(page, 'schedule-save').click()
            page.wait_for_timeout(SETTLE_MS)
            if tid(page, 'schedule-conflict').count() != 1 or tid(page, 'schedule-text').input_value() != mine or sched12_rows.call('backup_schedule_get', {}).get('text') != other:
                self.bad('V11 L15 conflict: schedule-conflict %d, the editor keeps the typed text %s, the stored text is still the other writer %s; expected the banner, the text kept and nothing overwritten' % (tid(page, 'schedule-conflict').count(), tid(page, 'schedule-text').input_value() == mine, sched12_rows.call('backup_schedule_get', {}).get('text') == other))
        finally:
            sess.close()
            self.restore(kept[0], sched12_rows.digest(other))


def _driven(report: Report, *names: str) -> None:
    '''Run Cases12 methods in the headless browser against the deployed SPA.

    Args:
        report: the findings collector.
        names: the Cases12 methods.

    Returns:
        None.
    '''
    root = vuechecks.deployed(report, 'rev12 SPA endpoint')
    if root is not None:
        vuechecks.with_driver(report, 'rev12 browser', root, *[(lambda rep, drv, item=name: getattr(Cases12(rep, drv, root), item)()) for name in names])


def _manifest(report: Report) -> None:
    '''V3: the served command manifest lists the three schedule commands with their parameters.

    Args:
        report: the findings collector.

    Returns:
        None.
    '''
    root = vuechecks.deployed(report, 'V3 rev12 SPA endpoint')
    got = lan_try(report, 'V3 GET /command-manifest.json', root, 'GET', '/command-manifest.json') if root else None
    if got is None:
        return
    try:
        text = json.dumps(json.loads(got[2]).get('used'))
    except (ValueError, AttributeError):
        text = ''
    for command, params in COMMANDS12:
        if command not in text or any('"%s"' % item not in text for item in params):
            report.product.append('V3 /command-manifest.json: the used set lacks %s with its parameters %s' % (command, list(params)))


def _tab(report: Report) -> None:
    '''V1: the service page has the tab svc-tab-schedule that links to the schedule section.

    Args:
        report: the findings collector.

    Returns:
        None.
    '''
    root = vuechecks.deployed(report, 'V1 rev12 SPA endpoint')
    if root is None:
        return

    def body(rep: Report, drv: Any) -> None:
        '''Open the service page and read the tab.

        Args:
            rep: the findings collector.
            drv: the headless driver.

        Returns:
            None.
        '''
        sess = Session(drv)
        try:
            sess.go('#/service')
            tab = tid(sess.page, 'svc-tab-schedule')
            if tab.count() != 1 or tab.first.get_attribute('href') != ROUTE:
                rep.product.append('V1 #/service: %d svc-tab-schedule with href %s, expected one linking to %s' % (tab.count(), tab.first.get_attribute('href') if tab.count() else None, ROUTE))
        finally:
            sess.close()
    vuechecks.with_driver(report, 'V1 rev12 browser', root, body)


def _groups(report: Report) -> None:
    '''V6: the Vitest groups of 10.20.7 exist in the tracked frontend tests.

    Args:
        report: the findings collector.

    Returns:
        None.
    '''
    found: set[str] = set()
    for item in tracked_files() or []:
        if item.startswith('frontend/') and '.test.' in item:
            try:
                found |= set(vuebuild.DESCRIBE.findall(open(vuechecks.ROOT / item, encoding='utf-8').read()))
            except OSError:
                continue
    missing = [name for name in GROUPS12 if name not in found]
    if missing:
        report.product.append('V6 the Vitest describe groups %s do not exist in the tracked frontend tests (found %s)' % (missing, sorted(found)))
    report.info.append('V6 rev12 sha256 of the group list: %s' % hashlib.sha256(','.join(sorted(found)).encode()).hexdigest()[:12])


def vue_command_contract() -> None:
    '''V3 on revision 12: the live help lists the 17 commands and the manifest lists the three new ones.

    Returns:
        None.
    '''
    compose('vue_command_contract', vue11.vue_command_contract, _manifest)


def vue_command_calls() -> None:
    '''V4 on revision 12: the schedule route sends exactly get and status.

    Returns:
        None.
    '''
    compose('vue_command_calls', vue11.vue_command_calls, lambda report: _driven(report, 'open_section'))


def vue_polling() -> None:
    '''V7 on revision 12: the schedule status poll lives in the visible section only.

    Returns:
        None.
    '''
    compose('vue_polling', vue11.vue_polling, lambda report: _driven(report, 'poll'))


def vue_build() -> None:
    '''V6 on revision 12: the Vitest groups of the schedule section exist.

    Returns:
        None.
    '''
    compose('vue_build', vue11.vue_build, _groups)


def vue_static_serve() -> None:
    '''V1 on revision 12: the service page carries the schedule tab.

    Returns:
        None.
    '''
    compose('vue_static_serve', vue11.vue_static_serve, _tab)


def vue_schedule() -> None:
    '''V11: the live Playwright cases L10 to L15 of the schedule section (the two writing cases follow the safety rule).

    Returns:
        None.
    '''
    report = Report()
    if live.service_state() != 'S1':
        report.state.append('V11 the schedule section cases need an S1 service')
    else:
        _driven(report, 'open_section', 'check_one', 'poll', 'save', 'conflict')
    report.finish('vue_schedule')
