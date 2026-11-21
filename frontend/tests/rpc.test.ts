import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { COMMANDS, NOT_USED, buildParams } from '../src/commands'
import { downloadUrl, hrefExport, hrefFiles, parseHash } from '../src/lib'
import { Aborted, AuthRequired, auth, call, forgetAndAbort, invoke, setKey } from '../src/rpc'

function reply(status: number, body: unknown): Response {
  return new Response(JSON.stringify(body), { status, headers: { 'Content-Type': 'application/json' } })
}
const ok = (data: unknown): Response => reply(200, { jsonrpc: '2.0', result: { success: true, data }, id: 1 })
function headersOf(fetcher: ReturnType<typeof vi.fn>, index = 0): Record<string, string> {
  return (fetcher.mock.calls[index][1] as RequestInit).headers as Record<string, string>
}

beforeEach(() => {
  forgetAndAbort()
  auth.epoch = 0
})
afterEach(() => {
  vi.unstubAllGlobals()
})

describe('auth', () => {
  it('sends no key while the service answers without 401', async () => {
    const fetcher = vi.fn(async () => ok({}))
    vi.stubGlobal('fetch', fetcher)
    await call('help', {})
    expect(headersOf(fetcher)['X-API-Key']).toBeUndefined()
    expect(auth.needKey).toBe(false)
  })

  it('asks for the key after a 401 and then sends it only as X-API-Key on /api/jsonrpc', async () => {
    const fetcher = vi.fn(async () => reply(401, { detail: 'Unauthorized' }))
    vi.stubGlobal('fetch', fetcher)
    await expect(call('help', {})).rejects.toBeInstanceOf(AuthRequired)
    expect(auth.needKey).toBe(true)
    fetcher.mockImplementation(async () => ok({ fine: true }))
    setKey('typed-key')
    expect(auth.needKey).toBe(false)
    await expect(call('help', {})).resolves.toEqual({ fine: true })
    expect(fetcher.mock.calls[1][0]).toBe('/api/jsonrpc')
    expect(headersOf(fetcher, 1)['X-API-Key']).toBe('typed-key')
  })

  it('keeps the key in memory only: no cookie, no web storage, no URL', () => {
    setKey('memory-only-key')
    expect(window.localStorage.length).toBe(0)
    expect(window.sessionStorage.length).toBe(0)
    expect(document.cookie).toBe('')
    expect(window.location.href).not.toContain('memory-only-key')
  })

  it('forgets a key the service rejects and asks again', async () => {
    vi.stubGlobal('fetch', vi.fn(async () => reply(401, {})))
    setKey('wrong')
    await expect(call('help', {})).rejects.toBeInstanceOf(AuthRequired)
    expect(auth.hasKey).toBe(false)
    expect(auth.needKey).toBe(true)
  })
})

describe('commands', () => {
  it('has one table of the thirteen commands the SPA calls and one it does not', () => {
    expect(Object.keys(COMMANDS)).toHaveLength(13)
    expect(NOT_USED).toEqual(['backup_download_begin'])
  })

  it('sends exactly the keys of the table and never a null for an omitted optional', async () => {
    expect(buildParams('backup_sites_list', { limit: 100, offset: 0, query: undefined })).toEqual({ limit: 100, offset: 0 })
    expect(buildParams('backup_prepare_download', { snapshot_id: 's', file_path: null })).toEqual({ snapshot_id: 's' })
    expect(buildParams('backup_list_files', { snapshot_id: 's', prefix: '', offset: 0, limit: 100 })).toEqual({ snapshot_id: 's', prefix: '', offset: 0, limit: 100 })
    const fetcher = vi.fn(async () => ok({}))
    vi.stubGlobal('fetch', fetcher)
    await invoke('help', { cmdname: undefined })
    expect(JSON.parse((fetcher.mock.calls[0][1] as RequestInit).body as string)).toMatchObject({ method: 'help', params: {} })
  })

  it('refuses an unknown command, an unknown parameter and a missing required one', () => {
    expect(() => buildParams('nosuch', {})).toThrow()
    expect(() => buildParams('backup_snapshots', { page: 1 })).toThrow()
    expect(() => buildParams('backup_download_status', {})).toThrow()
  })
})

describe('download', () => {
  const id = '0123456789abcdef0123456789abcdef'
  it('builds the plain link only for a uuid4 hex export id', () => {
    expect(downloadUrl(id, 'a b.txt')).toBe(`/downloads/${id}/a%20b.txt`)
    expect(downloadUrl('not-an-id', 'a.txt')).toBeNull()
    expect(downloadUrl(id.toUpperCase(), 'a.txt')).toBeNull()
    expect(downloadUrl(id, '../x')).toBeNull()
    expect(downloadUrl(id, '')).toBeNull()
  })
})

describe('routes', () => {
  it('parses every hash route of the route table', () => {
    expect(parseHash('').name).toBe('main')
    expect(parseHash('#/').name).toBe('main')
    expect(parseHash('#/service').name).toBe('service')
    expect(parseHash('#/service/snapshots/abc/files?prefix=a%2Fb&offset=100')).toMatchObject({ name: 'files', params: { id: 'abc' } })
    expect(parseHash('#/service/snapshots/abc/files?prefix=a%2Fb').query.get('prefix')).toBe('a/b')
    expect(parseHash('#/exports/xyz')).toMatchObject({ name: 'export', params: { id: 'xyz' } })
    expect(parseHash('#/service/sites/a%2Cb/libraries')).toMatchObject({ name: 'libraries', params: { id: 'a,b' } })
    expect(parseHash('#/signed-out').name).toBe('signed-out')
    expect(parseHash('#/nowhere').name).toBe('notfound')
  })
  it('treats every route of the old table as an unknown route', () => {
    for (const old of ['#/snapshots', '#/sites', '#/discovery', '#/help', '#/help/backup_snapshots', '#/info', '#/snapshots/abcdef12/files', '#/sites/site-1/libraries']) {
      expect(parseHash(old).name).toBe('notfound')
    }
  })
  it('builds hashes that parse back', () => {
    expect(parseHash(hrefFiles('a b', 'dir/x', 200)).params.id).toBe('a b')
    expect(parseHash(hrefExport('e1')).params.id).toBe('e1')
  })
})

describe('logout', () => {
  it('aborts a request in flight, forgets the key and discards the late answer', async () => {
    const hang = vi.fn(
      (_url: string, init: RequestInit) =>
        new Promise<Response>((_resolve, reject) => {
          init.signal?.addEventListener('abort', () => reject(new DOMException('aborted', 'AbortError')))
        }),
    )
    vi.stubGlobal('fetch', hang)
    setKey('k')
    const pending = call('help', {})
    forgetAndAbort()
    await expect(pending).rejects.toBeInstanceOf(Aborted)
    expect(auth.hasKey).toBe(false)
    expect(auth.needKey).toBe(false)
  })
  it('aborts one request alone when its own signal fires', async () => {
    const hang = vi.fn(
      (_url: string, init: RequestInit) =>
        new Promise<Response>((_resolve, reject) => {
          init.signal?.addEventListener('abort', () => reject(new DOMException('aborted', 'AbortError')))
        }),
    )
    vi.stubGlobal('fetch', hang)
    const one = new AbortController()
    const pending = call('help', {}, one.signal)
    one.abort()
    await expect(pending).rejects.toBeInstanceOf(Aborted)
  })
})
