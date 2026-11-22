import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { POLL_SCHEDULE_MS, SECTIONS, parseHash, startPolling } from '../src/lib'
import { buildParams } from '../src/commands'
import {
  DEFAULT_TEXT, STATE_LABELS, canSave, changedElsewhere, checkValues, conflictOf, hasError, isDirty, lineOffset, localTime, orderProblems,
  problemText, saveValues, stateLabel,
} from '../src/schedule'

const states = ['starting', 'waiting', 'running', 'paused', 'idle', 'file_invalid', 'storage_unavailable', 'scaffold', 'not_leader', 'stopped']

describe('schedule-editor', () => {
  it('tracks the dirty state against the loaded text', () => {
    expect(isDirty('a\n', 'a\n')).toBe(false)
    expect(isDirty('a\n# x\n', 'a\n')).toBe(true)
  })
  it('sends a check as a dry run with exactly text, dry_run and actor', () => {
    expect(buildParams('backup_schedule_set', checkValues('30 2 * * *\n'))).toEqual({ text: '30 2 * * *\n', dry_run: true, actor: 'spa' })
  })
  it('sends a save with expected_revision and no dry_run key', () => {
    const sent = buildParams('backup_schedule_set', saveValues('30 2 * * *\n', 'a'.repeat(64)))
    expect(Object.keys(sent).sort()).toEqual(['actor', 'expected_revision', 'text'])
  })
  it('allows a save only for a changed text whose last check had no error', () => {
    expect(canSave('b', 'a', 'b', [])).toBe(true)
    expect(canSave('b', 'a', null, [])).toBe(false)
    expect(canSave('b', 'a', 'x', [])).toBe(false)
    expect(canSave('a', 'a', 'a', [])).toBe(false)
    expect(canSave('b', 'a', 'b', orderProblems([{ line: 1, code: 'CRON_RANGE', severity: 'error', message: 'm' }]))).toBe(false)
  })
  it('knows the default text of the service', () => {
    expect(DEFAULT_TEXT.endsWith('30 2 * * *\n')).toBe(true)
    expect(parseHash('#/service?section=schedule').params.section).toBe('schedule')
    expect(SECTIONS).toContain('schedule')
  })
})

describe('schedule-problems', () => {
  const raw = [
    { line: 3, column: 1, code: 'DOM_DOW_OR', severity: 'warning', message: 'w' },
    { line: 2, column: 4, code: 'CRON_RANGE', severity: 'error', message: 'e2' },
    { line: 1, column: 1, code: 'TZ_UNKNOWN', severity: 'error', message: 'e1' },
  ]
  it('puts the errors before the warnings and orders each group by line', () => {
    expect(orderProblems(raw).map((item) => item.code)).toEqual(['TZ_UNKNOWN', 'CRON_RANGE', 'DOM_DOW_OR'])
    expect(hasError(orderProblems(raw))).toBe(true)
    expect(hasError(orderProblems([raw[0]]))).toBe(false)
  })
  it('shows a problem as line:column code message', () => {
    expect(problemText(orderProblems(raw)[1])).toBe('2:4 CRON_RANGE e2')
    expect(problemText({ line: null, column: null, code: 'NO_ENTRIES', severity: 'warning', message: 'm' })).toBe('-:- NO_ENTRIES m')
  })
  it('moves the caret to the start of the line of a problem', () => {
    expect(lineOffset('ab\ncd\nef\n', 1)).toBe(0)
    expect(lineOffset('ab\ncd\nef\n', 3)).toBe(6)
  })
  it('ignores an answer that holds no list of problems', () => {
    expect(orderProblems(undefined)).toEqual([])
    expect(orderProblems('x')).toEqual([])
  })
})

describe('schedule-conflict', () => {
  it('reads the revision and the text of the server from a 409 answer', () => {
    expect(conflictOf(409, { current_revision: 'r', current_text: 't' })).toEqual({ revision: 'r', text: 't' })
  })
  it('is no conflict for another code or an answer without a revision', () => {
    expect(conflictOf(400, { current_revision: 'r' })).toBeNull()
    expect(conflictOf(409, {})).toBeNull()
    expect(conflictOf(409, null)).toBeNull()
  })
})

describe('schedule-status', () => {
  beforeEach(() => {
    vi.useFakeTimers()
  })
  afterEach(() => {
    vi.useRealTimers()
  })
  it('has a label for each of the ten states', () => {
    for (const state of states) expect(STATE_LABELS[state]).toBeTruthy()
    expect(Object.keys(STATE_LABELS).sort()).toEqual([...states].sort())
    expect(stateLabel('unknown')).toBe('unknown')
  })
  it('polls the status every 15 seconds, one request at a time, and stops on stop', async () => {
    const task = vi.fn(async () => true)
    const poller = startPolling(task, POLL_SCHEDULE_MS)
    await vi.advanceTimersByTimeAsync(POLL_SCHEDULE_MS - 1)
    expect(task).toHaveBeenCalledTimes(0)
    await vi.advanceTimersByTimeAsync(1)
    expect(task).toHaveBeenCalledTimes(1)
    poller.stop()
    await vi.advanceTimersByTimeAsync(120000)
    expect(task).toHaveBeenCalledTimes(1)
  })
  it('shows the changed-elsewhere banner only for a foreign revision', () => {
    expect(changedElsewhere('b', 'a', null)).toBe(true)
    expect(changedElsewhere('a', 'a', null)).toBe(false)
    expect(changedElsewhere('', 'a', null)).toBe(false)
    expect(changedElsewhere('old', 'new', 'old')).toBe(false)
    expect(changedElsewhere('b', null, null)).toBe(false)
  })
  it('sends the schedule commands with the keys of their table only', () => {
    expect(buildParams('backup_schedule_get', {})).toEqual({})
    expect(buildParams('backup_schedule_status', { history_limit: undefined })).toEqual({})
    expect(() => buildParams('backup_schedule_set', {})).toThrow()
  })
})

describe('schedule-time', () => {
  it('formats an instant in the zone of the answer', () => {
    expect(localTime('2026-11-25T00:30:00Z', 'Europe/Kyiv')).toBe('2026-11-25 02:30 (Europe/Kyiv)')
    expect(localTime('2026-07-25T23:30:00Z', 'Europe/Kyiv')).toBe('2026-07-26 02:30 (Europe/Kyiv)')
  })
  it('shows the repeated hour of the autumn change twice', () => {
    expect(localTime('2026-10-25T00:30:00Z', 'Europe/Kyiv')).toBe('2026-10-25 03:30 (Europe/Kyiv)')
    expect(localTime('2026-10-25T01:30:00Z', 'Europe/Kyiv')).toBe('2026-10-25 03:30 (Europe/Kyiv)')
  })
  it('keeps a text that is no date', () => {
    expect(localTime('soon', 'UTC')).toBe('soon (UTC)')
  })
})
