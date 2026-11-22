// Adapter command API client of the SPA: POST /api/jsonrpc on the same origin, nothing else.
// The key (X-API-Key) exists only after a 401 answer and lives in this module's memory: never a cookie, web storage or URL.

import { reactive } from 'vue'
import { buildParams } from './commands'

export const auth = reactive({ needKey: false, hasKey: false, epoch: 0 })

export class RpcError extends Error {
  code: number | string
  data: unknown
  constructor(code: number | string, message: string, data: unknown = null) {
    super(message)
    this.name = 'RpcError'
    this.code = code
    this.data = data
  }
}
export class AuthRequired extends Error {
  constructor() {
    super('authentication required')
    this.name = 'AuthRequired'
  }
}
export class RateLimited extends Error {
  retryAfterMs: number
  constructor(retryAfterMs: number) {
    super('rate limited')
    this.name = 'RateLimited'
    this.retryAfterMs = retryAfterMs
  }
}
export class NetworkError extends Error {
  constructor(message: string) {
    super(message)
    this.name = 'NetworkError'
  }
}
export class Aborted extends Error {
  constructor() {
    super('aborted')
    this.name = 'Aborted'
  }
}

let key: string | null = null
let controller = new AbortController()
let counter = 0

/** Hold the key typed after a 401 (memory only) and ask every page to load again. */
export function setKey(value: string): void {
  key = value.length > 0 ? value : null
  auth.hasKey = key !== null
  if (key !== null) {
    auth.needKey = false
    auth.epoch += 1
  }
}

/** Logout: forget the key, abort every request in flight and discard what they would have answered. */
export function forgetAndAbort(): void {
  key = null
  auth.hasKey = false
  auth.needKey = false
  controller.abort()
  controller = new AbortController()
}

export function authHeaders(): Record<string, string> {
  return key === null ? {} : { 'X-API-Key': key }
}

function rejected(): AuthRequired {
  key = null
  auth.hasKey = false
  auth.needKey = true
  return new AuthRequired()
}

function retryAfter(response: Response): number {
  const seconds = Number.parseInt(response.headers.get('Retry-After') ?? '', 10)
  return Number.isFinite(seconds) && seconds > 0 ? seconds * 1000 : 0
}

/**
 * One JSON-RPC command; resolves with the result data or throws RpcError, AuthRequired, RateLimited, NetworkError or Aborted.
 * The optional signal aborts this one request (a newer keystroke of the autocomplete); a logout aborts every request.
 * A command error keeps its details (error.data) in RpcError.data.
 */
export async function call(command: string, params: Record<string, unknown> = {}, extra?: AbortSignal): Promise<unknown> {
  const own = new AbortController()
  const stop = (): void => own.abort()
  controller.signal.addEventListener('abort', stop)
  extra?.addEventListener('abort', stop)
  if (controller.signal.aborted || extra?.aborted) own.abort()
  let response: Response
  try {
    response = await fetch('/api/jsonrpc', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', ...authHeaders() },
      body: JSON.stringify({ jsonrpc: '2.0', method: command, params, id: ++counter }),
      credentials: 'omit',
      cache: 'no-store',
      signal: own.signal,
    })
  } catch (exc) {
    if ((exc as Error).name === 'AbortError') throw new Aborted()
    throw new NetworkError((exc as Error).message)
  } finally {
    controller.signal.removeEventListener('abort', stop)
    extra?.removeEventListener('abort', stop)
  }
  if (response.status === 401 || response.status === 403) throw rejected()
  if (response.status === 429) throw new RateLimited(retryAfter(response))
  let body: any = null
  try {
    body = await response.json()
  } catch (exc) {
    if ((exc as Error).name === 'AbortError') throw new Aborted()
  }
  if (body && body.error) throw new RpcError(body.error.code ?? response.status, String(body.error.message ?? ''), body.error.data ?? null)
  const result = body ? body.result : null
  if (result && result.success === false) {
    const failure = result.error ?? {}
    throw new RpcError(failure.code ?? response.status, String(failure.message ?? ''), failure.data ?? null)
  }
  if (!response.ok || !result) throw new RpcError(response.status, `HTTP ${response.status}`)
  return result.data
}

/** A command of the table with its parameters checked against it. */
export function invoke(command: string, values: Record<string, unknown> = {}, signal?: AbortSignal): Promise<unknown> {
  return call(command, buildParams(command, values), signal)
}

/** Download a link with the held key (fetch with X-API-Key and save the blob); used only after a 401. */
export async function downloadWithKey(url: string, filename: string): Promise<void> {
  const response = await fetch(url, { headers: authHeaders(), credentials: 'omit', signal: controller.signal })
  if (response.status === 401 || response.status === 403) throw rejected()
  if (!response.ok) throw new RpcError(response.status, `HTTP ${response.status}`)
  const blob = await response.blob()
  const href = URL.createObjectURL(blob)
  const anchor = document.createElement('a')
  anchor.href = href
  anchor.download = filename
  document.body.appendChild(anchor)
  anchor.click()
  anchor.remove()
  URL.revokeObjectURL(href)
}
