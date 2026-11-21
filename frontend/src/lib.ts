// Pure helpers of the SPA: result flattening, hash routes, filter state, autocomplete rules, paging, the download link builder and the poller.

import { AuthRequired, RateLimited } from './rpc'

export const PAGE_SIZE = 100
export const POLL_DISCOVERY_MS = 30000
export const POLL_EXPORT_MS = 5000
export const POLL_MIN_MS = 5000
export const POLL_MAX_MS = 120000
export const BACKOFF_CAP_MS = 300000
export const EXPORT_ID = /^[0-9a-f]{32}$/
export const SUGGEST_MIN = 2
export const SUGGEST_DELAY_MS = 250
export const SUGGEST_LIMIT = 10

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

// ---- hash routes (hash routing, no history fallback): '#/' is the filter page, '#/service' the service page ----

export interface Route {
  name: string
  params: Record<string, string>
  query: URLSearchParams
}

export const SECTIONS = ['snapshots', 'sites', 'discovery', 'help', 'info'] as const
export type Section = (typeof SECTIONS)[number]
/** The only command(s) a section of the service page sends: sections load lazily, one at a time. */
export const SECTION_COMMANDS: Record<Section, string> = {
  snapshots: 'backup_snapshots',
  sites: 'backup_sites_list',
  discovery: 'backup_discovery_status',
  help: 'help',
  info: 'info',
}

const enc = encodeURIComponent

function route(name: string, params: Record<string, string> = {}, query = new URLSearchParams()): Route {
  return { name, params, query }
}

export function parseHash(hash: string): Route {
  const raw = hash.startsWith('#') ? hash.slice(1) : hash
  const cut = raw.indexOf('?')
  const path = cut < 0 ? raw : raw.slice(0, cut)
  const query = new URLSearchParams(cut < 0 ? '' : raw.slice(cut + 1))
  let parts: string[]
  try {
    parts = path.split('/').filter((part) => part !== '').map(decodeURIComponent)
  } catch {
    return route('notfound')
  }
  const [first, second, third, fourth] = parts
  if (parts.length === 0) return route('main', {}, query)
  if (parts.length === 1 && first === 'signed-out') return route('signed-out', {}, query)
  if (parts.length === 1 && first === 'service') {
    const section = query.get('section') ?? 'snapshots'
    return (SECTIONS as readonly string[]).includes(section) ? route('service', { section }, query) : route('notfound')
  }
  if (parts.length === 4 && first === 'service' && second === 'snapshots' && fourth === 'files') return route('files', { id: third }, query)
  if (parts.length === 4 && first === 'service' && second === 'sites' && fourth === 'libraries') return route('libraries', { id: third }, query)
  if (parts.length === 2 && first === 'exports') return route('export', { id: second }, query)
  return route('notfound')
}

export function hrefFiles(snapshotId: string, prefix = '', offset = 0): string {
  const query: string[] = []
  if (prefix) query.push(`prefix=${enc(prefix)}`)
  if (offset > 0) query.push(`offset=${offset}`)
  return `#/service/snapshots/${enc(snapshotId)}/files${query.length ? '?' + query.join('&') : ''}`
}
export const hrefExport = (exportId: string): string => `#/exports/${enc(exportId)}`
export function hrefSites(search = '', offset = 0): string {
  const query = ['section=sites']
  if (search) query.push(`q=${enc(search)}`)
  if (offset > 0) query.push(`offset=${offset}`)
  return `#/service?${query.join('&')}`
}
export const hrefLibraries = (siteId: string, offset = 0): string => `#/service/sites/${enc(siteId)}/libraries${offset > 0 ? '?offset=' + offset : ''}`
export const hrefHelp = (command = ''): string => (command ? `#/service?section=help&cmd=${enc(command)}` : '#/service?section=help')
export const hrefInfo = (page = 1): string => (page > 1 ? `#/service?section=info&page=${page}` : '#/service?section=info')
export const hrefSection = (section: Section): string => `#/service?section=${section}`

// ---- the filter state of the main page lives in the hash: #/?site=..&site=..&date=..&q=..&offset=.. ----

export interface Filter {
  sites: string[]
  dates: string[]
  q: string
  offset: number
}

const FILTER_KEYS = ['site', 'date', 'q', 'offset']

/** True when the hash query carries any filter key; a bare '#/' opens the default (newest date) view. */
export const hasFilter = (query: URLSearchParams): boolean => FILTER_KEYS.some((name) => query.has(name))

export function parseFilter(query: URLSearchParams): Filter {
  return { sites: query.getAll('site'), dates: query.getAll('date'), q: (query.get('q') ?? '').slice(0, 128), offset: intParam(query, 'offset', 0, PAGE_SIZE) }
}

export function hrefMain(filter: Filter): string {
  const parts: string[] = []
  for (const site of filter.sites) parts.push(`site=${enc(site)}`)
  for (const date of filter.dates) parts.push(`date=${enc(date)}`)
  if (filter.q !== '') parts.push(`q=${enc(filter.q)}`)
  if (filter.offset > 0) parts.push(`offset=${filter.offset}`)
  return parts.length ? `#/?${parts.join('&')}` : '#/'
}

/** The parameters of backup_search_files: an empty group or an empty name is omitted, never sent as null or empty. */
export function searchValues(filter: Filter): Record<string, unknown> {
  const name = filter.q.trim()
  return {
    site_ids: filter.sites.length ? filter.sites : undefined,
    dates: filter.dates.length ? filter.dates : undefined,
    name_part: name === '' ? undefined : name,
    limit: PAGE_SIZE,
    offset: filter.offset > 0 ? filter.offset : undefined,
  }
}

// ---- autocomplete of the name field ----

/** A suggestion is asked for only when the text holds at least two characters other than stars. */
export const suggestible = (text: string): boolean => text.trim().replace(/\*/g, '').length >= SUGGEST_MIN

/** A picked name goes into the field with a literal star and a backslash escaped. */
export const escapeName = (name: string): string => name.replace(/\\/g, '\\\\').replace(/\*/g, '\\*')

// ---- dates and the stored copy marker ----

/** The snapshot time as YYYY-MM-DD HH:MM in the time zone of the service (the server names it, Europe/Kyiv by default). */
export function formatSnapshot(iso: string, zone = 'Europe/Kyiv'): string {
  const at = new Date(iso)
  if (Number.isNaN(at.getTime())) return iso
  const parts = new Intl.DateTimeFormat('en-GB', {
    timeZone: zone,
    year: 'numeric',
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
    hourCycle: 'h23',
  }).formatToParts(at)
  const part = (type: string): string => parts.find((item) => item.type === type)?.value ?? ''
  return `${part('year')}-${part('month')}-${part('day')} ${part('hour')}:${part('minute')}`
}

/** A rev 10 stored duplicate copy is shown as the original name followed by this marker. */
export function copyMarker(index: number): string {
  if (!Number.isInteger(index) || index <= 0) return ''
  return index === 1 ? '(копия)' : `(копия ${index})`
}

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
