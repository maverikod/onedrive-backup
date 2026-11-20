// Pure helpers of the SPA: result flattening, hash routes, paging, the download link builder and the poller.

import { AuthRequired, RateLimited } from './rpc'

export const PAGE_SIZE = 100
export const POLL_DISCOVERY_MS = 30000
export const POLL_EXPORT_MS = 5000
export const POLL_MIN_MS = 5000
export const POLL_MAX_MS = 120000
export const BACKOFF_CAP_MS = 300000
export const EXPORT_ID = /^[0-9a-f]{32}$/

// ---- result cells: every scalar field of a result keeps its exact raw value in data-raw ----

export interface Cell {
  field: string
  raw: string
  text: string
}

export function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null && !Array.isArray(value)
}

export function formatBytes(raw: string): string {
  const size = Number(raw)
  if (!Number.isFinite(size) || size < 0) return raw
  const units = ['B', 'KiB', 'MiB', 'GiB', 'TiB']
  let value = size
  let unit = 0
  while (value >= 1024 && unit < units.length - 1) {
    value /= 1024
    unit += 1
  }
  return unit === 0 ? `${size} B` : `${value.toFixed(1)} ${units[unit]}`
}

const SIZE_FIELD = /(^|[._])size(_bytes)?$/

export function flatten(value: unknown, prefix = ''): Cell[] {
  const out: Cell[] = []
  if (Array.isArray(value)) {
    value.forEach((item, index) => out.push(...flatten(item, prefix ? `${prefix}.${index}` : String(index))))
  } else if (isRecord(value)) {
    for (const [name, item] of Object.entries(value)) out.push(...flatten(item, prefix ? `${prefix}.${name}` : name))
  } else if (value !== null && value !== undefined) {
    const raw = typeof value === 'string' ? value : typeof value === 'boolean' ? (value ? 'true' : 'false') : String(value)
    out.push({ field: prefix, raw, text: SIZE_FIELD.test(prefix) && /^\d+$/.test(raw) ? formatBytes(raw) : raw })
  }
  return out
}

// ---- hash routes (hash routing, no history fallback) ----

export interface Route {
  name: string
  params: Record<string, string>
  query: URLSearchParams
}

const enc = encodeURIComponent

function route(name: string, params: Record<string, string> = {}, query = new URLSearchParams()): Route {
  return { name, params, query }
}

export function parseHash(hash: string): Route {
  const raw = hash.startsWith('#') ? hash.slice(1) : hash
  if (raw === '' || raw === '/') return route('redirect')
  const cut = raw.indexOf('?')
  const path = cut < 0 ? raw : raw.slice(0, cut)
  const query = new URLSearchParams(cut < 0 ? '' : raw.slice(cut + 1))
  let parts: string[]
  try {
    parts = path.split('/').filter((part, index) => index > 0 || part !== '').map(decodeURIComponent)
  } catch {
    return route('notfound')
  }
  const [first, second, third] = parts
  if (parts.length === 1) {
    if (['snapshots', 'sites', 'discovery', 'help', 'info', 'signed-out'].includes(first)) return route(first, {}, query)
  }
  if (parts.length === 3 && first === 'snapshots' && third === 'files') return route('files', { id: second }, query)
  if (parts.length === 3 && first === 'sites' && third === 'libraries') return route('libraries', { id: second }, query)
  if (parts.length === 2 && first === 'exports') return route('export', { id: second }, query)
  if (parts.length === 2 && first === 'help') return route('help', { cmd: second }, query)
  return route('notfound')
}

export function hrefFiles(snapshotId: string, prefix = '', offset = 0): string {
  const query: string[] = []
  if (prefix) query.push(`prefix=${enc(prefix)}`)
  if (offset > 0) query.push(`offset=${offset}`)
  return `#/snapshots/${enc(snapshotId)}/files${query.length ? '?' + query.join('&') : ''}`
}
export const hrefExport = (exportId: string): string => `#/exports/${enc(exportId)}`
export function hrefSites(search = '', offset = 0): string {
  const query: string[] = []
  if (search) query.push(`q=${enc(search)}`)
  if (offset > 0) query.push(`offset=${offset}`)
  return `#/sites${query.length ? '?' + query.join('&') : ''}`
}
export const hrefLibraries = (siteId: string, offset = 0): string => `#/sites/${enc(siteId)}/libraries${offset > 0 ? '?offset=' + offset : ''}`
export const hrefHelp = (command = ''): string => (command ? `#/help/${enc(command)}` : '#/help')
export const hrefInfo = (page = 1): string => (page > 1 ? `#/info?page=${page}` : '#/info')

// ---- paging ----

/** A non-negative integer query value rounded down to a multiple; anything else is the fallback. */
export function intParam(query: URLSearchParams, name: string, fallback: number, multiple = 1): number {
  const value = Number.parseInt(query.get(name) ?? '', 10)
  return Number.isFinite(value) && value >= 0 ? value - (value % multiple) : fallback
}
export const prevOffset = (offset: number): number => Math.max(0, offset - PAGE_SIZE)
export const nextOffset = (offset: number): number => offset + PAGE_SIZE
/** More pages exist when the total says so; without a total, a full page means there may be one more. */
export function hasNext(offset: number, total: unknown, count: number): boolean {
  return typeof total === 'number' ? offset + PAGE_SIZE < total : count >= PAGE_SIZE
}

// ---- export link and card state ----

/** The plain link of an export: /downloads/<export_id>/<filename>; null when the id is not a 32 character lower-case hex id. */
export function downloadUrl(exportId: string, filename: string): string | null {
  if (!EXPORT_ID.test(exportId) || !filename || filename.includes('/') || filename === '..') return null
  return `/downloads/${exportId}/${enc(filename)}`
}

/** An export answer is final when it carries a non-empty sha256 and an integer size_bytes. */
export function isFinalExport(status: unknown): boolean {
  return isRecord(status) && typeof status.sha256 === 'string' && status.sha256 !== '' && Number.isInteger(status.size_bytes)
}

export function isExpired(status: unknown, now: number = Date.now()): boolean {
  if (!isRecord(status) || typeof status.expires_at !== 'string') return false
  const at = Date.parse(status.expires_at)
  return Number.isFinite(at) && at <= now
}

// ---- poller: read-only, one request in flight, the next one scheduled after the previous finished ----

export interface Poller {
  stop(): void
  kick(): void
}

export const clampInterval = (ms: number): number => Math.min(POLL_MAX_MS, Math.max(POLL_MIN_MS, ms))

/** Exponential backoff with jitter and a cap. */
export function backoffDelay(base: number, failures: number, random: () => number = Math.random): number {
  return Math.min(BACKOFF_CAP_MS, base * 2 ** failures) * (0.5 + random() / 2)
}

/**
 * Run task every interval. The task answers true to go on and false to stop. AuthRequired stops the poller, RateLimited waits the
 * server's Retry-After, any other failure backs off. A hidden tab pauses it; becoming visible or online refreshes once.
 */
export function startPolling(task: () => Promise<boolean>, intervalMs: number, doc: Document = document): Poller {
  const base = clampInterval(intervalMs)
  let timer: ReturnType<typeof setTimeout> | null = null
  let stopped = false
  let inFlight = false
  let failures = 0

  function clear(): void {
    if (timer !== null) clearTimeout(timer)
    timer = null
  }
  function schedule(ms: number): void {
    if (stopped) return
    clear()
    timer = setTimeout(tick, ms)
  }
  function stop(): void {
    stopped = true
    clear()
    doc.removeEventListener('visibilitychange', wake)
    window.removeEventListener('online', wake)
  }
  function wake(): void {
    if (!stopped && !inFlight && !doc.hidden) {
      clear()
      void tick()
    }
  }
  async function tick(): Promise<void> {
    timer = null
    if (stopped || inFlight) return
    if (doc.hidden) {
      schedule(base)
      return
    }
    inFlight = true
    let next = base
    try {
      const keepGoing = await task()
      failures = 0
      if (!keepGoing) {
        stop()
        return
      }
    } catch (exc) {
      if (exc instanceof AuthRequired) {
        stop()
        return
      }
      if (exc instanceof RateLimited) {
        next = Math.max(base, exc.retryAfterMs)
      } else {
        failures += 1
        next = backoffDelay(base, failures)
      }
    } finally {
      inFlight = false
    }
    schedule(next)
  }

  doc.addEventListener('visibilitychange', wake)
  window.addEventListener('online', wake)
  schedule(base)
  return { stop, kick: wake }
}
