import { mount } from '@vue/test-utils'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { buildParams } from '../src/commands'
import {
  SECTIONS,
  SECTION_COMMANDS,
  copyMarker,
  escapeName,
  formatSnapshot,
  hasFilter,
  hrefHelp,
  hrefInfo,
  hrefMain,
  hrefSites,
  parseFilter,
  parseHash,
  searchValues,
  suggestible,
} from '../src/lib'
import MainPage from '../src/pages/MainPage.vue'
import { forgetAndAbort } from '../src/rpc'

describe('filters', () => {
  it('round-trips the filter state through the hash with repeated keys', () => {
    const filter = { sites: ['a,b', 'c d'], dates: ['2026-11-21', '2026-11-19'], q: 'акт*.pdf', offset: 200 }
    const hash = hrefMain(filter)
    expect(hash).toBe('#/?site=a%2Cb&site=c%20d&date=2026-11-21&date=2026-11-19&q=%D0%B0%D0%BA%D1%82*.pdf&offset=200')
    const route = parseHash(hash)
    expect(route.name).toBe('main')
    expect(parseFilter(route.query)).toEqual(filter)
  })
  it('opens the default view only when the hash carries no filter key', () => {
    expect(hasFilter(parseHash('#/').query)).toBe(false)
    expect(hasFilter(parseHash('#/?date=2026-11-21').query)).toBe(true)
    expect(hrefMain({ sites: [], dates: [], q: '', offset: 0 })).toBe('#/')
  })
  it('omits an empty group, an empty name and a zero offset from the search parameters', () => {
    expect(searchValues({ sites: [], dates: [], q: '  ', offset: 0 })).toEqual({
      site_ids: undefined,
      dates: undefined,
      name_part: undefined,
      limit: 100,
      offset: undefined,
    })
    expect(buildParams('backup_search_files', searchValues({ sites: [], dates: ['2026-11-21'], q: '', offset: 0 }))).toEqual({
      dates: ['2026-11-21'],
      limit: 100,
    })
    expect(buildParams('backup_search_files', searchValues({ sites: ['s'], dates: [], q: ' акт* ', offset: 100 }))).toEqual({
      site_ids: ['s'],
      name_part: 'акт*',
      limit: 100,
      offset: 100,
    })
  })
})

describe('datelabel', () => {
  it('shows the snapshot time in the time zone of the service, not in UTC', () => {
    expect(formatSnapshot('2026-11-21T12:47:52.123456Z', 'Europe/Kyiv')).toBe('2026-11-21 14:47')
    expect(formatSnapshot('2026-11-21T23:30:00Z', 'Europe/Kyiv')).toBe('2026-11-22 01:30')
    expect(formatSnapshot('2026-07-01T21:30:00Z', 'Europe/Kyiv')).toBe('2026-07-02 00:30')
    expect(formatSnapshot('not a time')).toBe('not a time')
  })
  it('shows a stored duplicate copy as the original name with a numbered marker', () => {
    expect(copyMarker(0)).toBe('')
    expect(copyMarker(1)).toBe('(копия)')
    expect(copyMarker(2)).toBe('(копия 2)')
    expect(copyMarker(3)).toBe('(копия 3)')
  })
})

describe('service-sections', () => {
  it('has six sections and every section sends exactly its own command', () => {
    expect([...SECTIONS]).toEqual(['snapshots', 'sites', 'discovery', 'help', 'info', 'schedule'])
    expect(SECTION_COMMANDS).toEqual({
      snapshots: 'backup_snapshots',
      sites: 'backup_sites_list',
      discovery: 'backup_discovery_status',
      help: 'help',
      info: 'info',
      schedule: 'backup_schedule_get',
    })
  })
  it('routes the service page and its sections, and refuses every other section and every old route', () => {
    expect(parseHash('#/service')).toMatchObject({ name: 'service', params: { section: 'snapshots' } })
    for (const section of SECTIONS) expect(parseHash('#/service?section=' + section)).toMatchObject({ name: 'service', params: { section } })
    expect(parseHash('#/service?section=other').name).toBe('notfound')
    expect(parseHash('#/snapshots').name).toBe('notfound')
    expect(parseHash(hrefSites('akt', 100))).toMatchObject({ name: 'service', params: { section: 'sites' } })
    expect(parseHash(hrefSites('akt', 100)).query.get('q')).toBe('akt')
    expect(parseHash(hrefHelp('info')).query.get('cmd')).toBe('info')
    expect(parseHash(hrefInfo(3)).query.get('page')).toBe('3')
  })
})

function ok(data: unknown): Response {
  return new Response(JSON.stringify({ jsonrpc: '2.0', result: { success: true, data }, id: 1 }), { status: 200, headers: { 'Content-Type': 'application/json' } })
}

describe('autocomplete', () => {
  const index = { complete: true, snapshots_total: 3, snapshots_indexed: 3 }
  let calls: { method: string; params: Record<string, unknown> }[] = []

  beforeEach(() => {
    vi.useFakeTimers()
    calls = []
    vi.stubGlobal(
      'fetch',
      vi.fn(async (_url: string, init: RequestInit) => {
        const body = JSON.parse(init.body as string)
        calls.push({ method: body.method, params: body.params })
        if (body.method === 'backup_filter_options') {
          return ok({ sites: [{ site_id: 's1', name: 'Site', snapshot_count: 3, last_snapshot_time: '' }], dates: [{ date: '2026-11-21', snapshot_count: 3 }], timezone: 'Europe/Kyiv', index })
        }
        if (body.method === 'backup_suggest_names') return ok({ items: [{ name: 'a*b.pdf' }, { name: 'second.pdf' }], text: body.params.text, truncated: false })
        return ok({ items: [], total: 0, offset: 0, limit: 100, timezone: 'Europe/Kyiv', index })
      }),
    )
  })
  afterEach(() => {
    forgetAndAbort()
    vi.useRealTimers()
    vi.unstubAllGlobals()
  })

  it('asks only from two characters other than stars', () => {
    expect(suggestible('a')).toBe(false)
    expect(suggestible('a*')).toBe(false)
    expect(suggestible('*')).toBe(false)
    expect(suggestible('ab')).toBe(true)
    expect(suggestible('a*b')).toBe(true)
  })
  it('escapes a literal star and a backslash of a picked name', () => {
    expect(escapeName('a*b.pdf')).toBe('a\\*b.pdf')
    expect(escapeName('a\\b')).toBe('a\\\\b')
    expect(escapeName('plain')).toBe('plain')
  })
  it('waits 250 ms, sends one request of the form state, and a pick fills the field and applies once', async () => {
    const wrapper = mount(MainPage, { props: { route: parseHash('#/') } })
    await vi.advanceTimersByTimeAsync(0)
    expect(calls.map((call) => call.method)).toEqual(['backup_filter_options', 'backup_search_files'])
    expect(calls[1].params).toEqual({ dates: ['2026-11-21'], limit: 100 })
    const input = wrapper.get('[data-testid=name-input]')
    await input.setValue('ak')
    await vi.advanceTimersByTimeAsync(249)
    expect(calls).toHaveLength(2)
    await vi.advanceTimersByTimeAsync(1)
    expect(calls).toHaveLength(3)
    expect(calls[2]).toEqual({ method: 'backup_suggest_names', params: { text: 'ak', dates: ['2026-11-21'], limit: 10 } })
    await vi.advanceTimersByTimeAsync(0)
    expect(wrapper.findAll('[data-testid=name-suggest-item]')).toHaveLength(2)
    await input.trigger('keydown', { key: 'ArrowDown' })
    await input.trigger('keydown', { key: 'Enter' })
    await vi.advanceTimersByTimeAsync(0)
    expect((input.element as HTMLInputElement).value).toBe('a\\*b.pdf')
    expect(calls).toHaveLength(4)
    expect(calls[3].method).toBe('backup_search_files')
    expect(calls[3].params.name_part).toBe('a\\*b.pdf')
    expect(wrapper.find('[data-testid=name-suggest]').exists()).toBe(false)
    wrapper.unmount()
  })
  it('closes the list on Escape without a call and sends nothing for one character', async () => {
    const wrapper = mount(MainPage, { props: { route: parseHash('#/') } })
    await vi.advanceTimersByTimeAsync(0)
    const input = wrapper.get('[data-testid=name-input]')
    await input.setValue('a')
    await vi.advanceTimersByTimeAsync(1000)
    expect(calls.filter((call) => call.method === 'backup_suggest_names')).toHaveLength(0)
    await input.setValue('ab')
    await vi.advanceTimersByTimeAsync(300)
    expect(wrapper.find('[data-testid=name-suggest]').exists()).toBe(true)
    const before = calls.length
    await input.trigger('keydown', { key: 'Escape' })
    expect(wrapper.find('[data-testid=name-suggest]').exists()).toBe(false)
    expect(calls).toHaveLength(before)
    wrapper.unmount()
  })
  it('sends no suggestion call after the page is gone', async () => {
    const wrapper = mount(MainPage, { props: { route: parseHash('#/') } })
    await vi.advanceTimersByTimeAsync(0)
    await wrapper.get('[data-testid=name-input]').setValue('ab')
    wrapper.unmount()
    await vi.advanceTimersByTimeAsync(120000)
    expect(calls.filter((call) => call.method === 'backup_suggest_names')).toHaveLength(0)
  })
})
