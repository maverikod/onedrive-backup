import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { BACKOFF_CAP_MS, POLL_DISCOVERY_MS, POLL_EXPORT_MS, backoffDelay, clampInterval, isExpired, isFinalExport, startPolling } from '../src/lib'
import { AuthRequired, NetworkError, RateLimited } from '../src/rpc'

beforeEach(() => {
  vi.useFakeTimers()
})
afterEach(() => {
  vi.useRealTimers()
})

describe('polling', () => {
  it('runs one request per interval, the next scheduled after the previous finished', async () => {
    const task = vi.fn(async () => true)
    const poller = startPolling(task, POLL_DISCOVERY_MS)
    await vi.advanceTimersByTimeAsync(POLL_DISCOVERY_MS - 1)
    expect(task).toHaveBeenCalledTimes(0)
    await vi.advanceTimersByTimeAsync(1)
    expect(task).toHaveBeenCalledTimes(1)
    await vi.advanceTimersByTimeAsync(POLL_DISCOVERY_MS)
    expect(task).toHaveBeenCalledTimes(2)
    poller.stop()
  })

  it('keeps one request in flight and schedules the next only after it finished', async () => {
    let release: (value: boolean) => void = () => undefined
    const task = vi.fn(() => new Promise<boolean>((resolve) => (release = resolve)))
    const poller = startPolling(task, 10000)
    await vi.advanceTimersByTimeAsync(90000)
    expect(task).toHaveBeenCalledTimes(1)
    release(true)
    await vi.advanceTimersByTimeAsync(10000)
    expect(task).toHaveBeenCalledTimes(2)
    poller.stop()
  })

  it('stops on a 401 and stays stopped', async () => {
    const task = vi.fn(async () => {
      throw new AuthRequired()
    })
    startPolling(task, POLL_EXPORT_MS)
    await vi.advanceTimersByTimeAsync(600000)
    expect(task).toHaveBeenCalledTimes(1)
  })

  it('stops when the task says it is done (a final export, a 404 or 410)', async () => {
    const task = vi.fn(async () => false)
    startPolling(task, POLL_EXPORT_MS)
    await vi.advanceTimersByTimeAsync(600000)
    expect(task).toHaveBeenCalledTimes(1)
  })

  it('honours Retry-After of a 429', async () => {
    const task = vi.fn(async () => {
      if (task.mock.calls.length === 1) throw new RateLimited(60000)
      return true
    })
    const poller = startPolling(task, 10000)
    await vi.advanceTimersByTimeAsync(10000)
    expect(task).toHaveBeenCalledTimes(1)
    await vi.advanceTimersByTimeAsync(60000 - 1)
    expect(task).toHaveBeenCalledTimes(1)
    await vi.advanceTimersByTimeAsync(1)
    expect(task).toHaveBeenCalledTimes(2)
    poller.stop()
  })

  it('backs off with jitter and a cap after network errors', async () => {
    expect(backoffDelay(5000, 1, () => 1)).toBe(10000)
    expect(backoffDelay(5000, 1, () => 0)).toBe(5000)
    expect(backoffDelay(5000, 30, () => 1)).toBe(BACKOFF_CAP_MS)
    const task = vi.fn(async () => {
      throw new NetworkError('down')
    })
    const poller = startPolling(task, 10000)
    await vi.advanceTimersByTimeAsync(10000)
    expect(task).toHaveBeenCalledTimes(1)
    await vi.advanceTimersByTimeAsync(5000)
    expect(task).toHaveBeenCalledTimes(1)
    poller.stop()
  })

  it('pauses while the tab is hidden and refreshes once when it is visible again', async () => {
    let hidden = true
    const doc = new EventTarget() as unknown as Document
    Object.defineProperty(doc, 'hidden', { get: () => hidden })
    const task = vi.fn(async () => true)
    const poller = startPolling(task, 10000, doc)
    await vi.advanceTimersByTimeAsync(60000)
    expect(task).toHaveBeenCalledTimes(0)
    hidden = false
    doc.dispatchEvent(new Event('visibilitychange'))
    await vi.advanceTimersByTimeAsync(0)
    expect(task).toHaveBeenCalledTimes(1)
    poller.stop()
  })

  it('stop() cancels the timer: a logout or a route change sends nothing more', async () => {
    const task = vi.fn(async () => true)
    const poller = startPolling(task, 10000)
    poller.stop()
    await vi.advanceTimersByTimeAsync(120000)
    expect(task).toHaveBeenCalledTimes(0)
  })

  it('clamps the interval constants to 5 s .. 120 s', () => {
    expect(clampInterval(1)).toBe(5000)
    expect(clampInterval(10 ** 9)).toBe(120000)
    expect(clampInterval(POLL_DISCOVERY_MS)).toBe(30000)
  })

  it('knows a final export (sha256 and integer size_bytes) and an expired one', () => {
    expect(isFinalExport({ sha256: 'ab', size_bytes: 3 })).toBe(true)
    expect(isFinalExport({ sha256: '', size_bytes: 3 })).toBe(false)
    expect(isFinalExport({ size_bytes: 3 })).toBe(false)
    expect(isExpired({ expires_at: '2020-01-01T00:00:00Z' }, Date.parse('2021-01-01T00:00:00Z'))).toBe(true)
    expect(isExpired({ expires_at: '2022-01-01T00:00:00Z' }, Date.parse('2021-01-01T00:00:00Z'))).toBe(false)
  })
})
