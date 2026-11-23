import { beforeEach, describe, expect, it, vi } from 'vitest'
import { buildParams } from '../src/commands'
import { hasFilter, hrefMain, parseFilter, parseHash, scopeOf, searchValues, withScope, type Filter } from '../src/lib'
import { invoke } from '../src/rpc'
import {
  ALL_KEY,
  ROOT_KEY,
  addrKey,
  crumbsOf,
  flattenVisible,
  formatCount,
  nodeKey,
  parseNodes,
  scopeChain,
  scopeOfNode,
  treeKeyAction,
  treeParams,
  type TreeNode,
} from '../src/tree'
import { createTree } from '../src/treeState'

vi.mock('../src/rpc', async (original) => ({ ...(await original<typeof import('../src/rpc')>()), invoke: vi.fn() }))

const DAY = '2026-11-21'
const base: Filter = { sites: [], dates: [DAY], q: '', offset: 0 }
const SITE: TreeNode = { kind: 'site', site_id: 's', drive_id: '', dir: '', name: 'Site', file_count: 5, direct_count: 0, has_children: true }
const LIB: TreeNode = { kind: 'library', site_id: 's', drive_id: 'd', dir: '', name: 'Lib', file_count: 5, direct_count: 1, has_children: true }
const LIB2: TreeNode = { ...LIB, drive_id: 'e', name: 'Lib two', has_children: false }
const FOLDER: TreeNode = { kind: 'folder', site_id: 's', drive_id: 'd', dir: 'a', name: 'a', file_count: 4, direct_count: 4, has_children: false }

describe('filters', () => {
  it('round-trips the scope keys fs, fd, fp and rec through the hash', () => {
    const filter: Filter = { ...base, fs: 's 1', fd: 'b!x', fp: 'ДЕНЬГИ Неактивные/2024', rec: true, offset: 100 }
    const hash = hrefMain(filter)
    expect(hash).toContain('date=2026-11-21&fs=s%201&fd=b!x&fp=')
    expect(hash).toContain('&rec=1&offset=100')
    expect(parseFilter(parseHash(hash).query)).toEqual(filter)
    expect(hasFilter(parseHash('#/?fs=s').query)).toBe(true)
  })
  it('writes no scope key without a scope and leaves the old hash unchanged', () => {
    expect(hrefMain(base)).toBe('#/?date=2026-11-21')
    expect(parseFilter(parseHash('#/?date=2026-11-21').query)).toEqual(base)
  })
  it('drops a combination that does not fit: fd without fs, fp without fd, rec without fd', () => {
    expect(parseFilter(new URLSearchParams('fd=d&fp=a&rec=1'))).toEqual({ sites: [], dates: [], q: '', offset: 0 })
    expect(parseFilter(new URLSearchParams('fs=s&fp=a&rec=1'))).toEqual({ sites: [], dates: [], q: '', offset: 0, fs: 's' })
    expect(parseFilter(new URLSearchParams('fs=s&fd=d&rec=2'))).toEqual({ sites: [], dates: [], q: '', offset: 0, fs: 's', fd: 'd' })
  })
  it('sends the scope as site_id, drive_id, dir and recursive and omits it without a scope', () => {
    expect(searchValues({ ...base, fs: 's', fd: 'd', fp: 'a', rec: true })).toEqual({ dates: [DAY], limit: 100, site_id: 's', drive_id: 'd', dir: 'a', recursive: true })
    expect(buildParams('backup_search_files', searchValues({ ...base, fs: 's', fd: 'd' }))).toEqual({ dates: [DAY], limit: 100, site_id: 's', drive_id: 'd' })
    expect(buildParams('backup_search_files', searchValues(base))).toEqual({ dates: [DAY], limit: 100 })
  })
  it('keeps the filters and the rec flag only with a library when the scope changes', () => {
    const now: Filter = { ...base, sites: ['s'], q: 'x*', offset: 200, fs: 's', fd: 'd', fp: 'a', rec: true }
    expect(withScope(now, { fs: 's', fd: 'e' })).toEqual({ sites: ['s'], dates: [DAY], q: 'x*', offset: 0, fs: 's', fd: 'e', rec: true })
    expect(withScope(now, { fs: 's' })).toEqual({ sites: ['s'], dates: [DAY], q: 'x*', offset: 0, fs: 's' })
    expect(withScope(now, {})).toEqual({ sites: ['s'], dates: [DAY], q: 'x*', offset: 0 })
    expect(scopeOf(now)).toEqual({ fs: 's', fd: 'd', fp: 'a' })
  })
})

describe('foldertree', () => {
  beforeEach(() => {
    vi.mocked(invoke).mockReset()
  })
  const answer = (nodes: TreeNode[]) => ({ nodes, total: nodes.length })

  it('builds the parameters of every level: the address, the filters and no offset on the first page', () => {
    const filter = { sites: [], dates: [DAY], q: '  ' }
    expect(treeParams({}, filter)).toEqual({ dates: [DAY] })
    expect(treeParams({ site_id: 's', drive_id: 'd' }, filter)).toEqual({ site_id: 's', drive_id: 'd', dates: [DAY] })
    expect(treeParams({ site_id: 's', drive_id: 'd', dir: 'a/b' }, { sites: ['s'], dates: [], q: ' *.xls ' }, 200)).toEqual({ site_id: 's', drive_id: 'd', dir: 'a/b', site_ids: ['s'], name_part: '*.xls', offset: 200 })
    expect(buildParams('backup_folder_children', treeParams({ site_id: 's' }, filter))).toEqual({ site_id: 's', dates: [DAY] })
  })
  it('reads the nodes and the total of an answer and skips a malformed node', () => {
    const page = parseNodes({ nodes: [LIB, 7, { kind: 'file' }], total: 9 })
    expect(page.total).toBe(9)
    expect(page.nodes).toEqual([LIB])
    expect(parseNodes(null)).toEqual({ nodes: [], total: 0 })
  })
  it('writes a count with a space as the thousands separator', () => {
    expect(formatCount(999)).toBe('999')
    expect(formatCount(1000)).toBe('1 000')
    expect(formatCount(345840)).toBe('345 840')
  })
  it('keeps one key per level and the node that owns it', () => {
    expect(addrKey({})).toBe(ROOT_KEY)
    expect(nodeKey(LIB)).toBe(addrKey({ site_id: 's', drive_id: 'd' }))
    expect(nodeKey(FOLDER)).not.toBe(nodeKey(LIB))
    expect(scopeOfNode(FOLDER)).toEqual({ fs: 's', fd: 'd', fp: 'a' })
  })
  it('loads the roots, opens the only site and sends the filters of the page', async () => {
    vi.mocked(invoke).mockImplementation(async (_command, values) => (values?.site_id ? answer([LIB, LIB2]) : answer([SITE])))
    const tree = createTree(() => undefined)
    await tree.reset({ sites: [], dates: [DAY], q: '' }, [])
    expect(vi.mocked(invoke).mock.calls.map((call) => call[1])).toEqual([{ dates: [DAY] }, { site_id: 's', dates: [DAY] }])
    expect(Object.keys(tree.state.open)).toEqual([nodeKey(SITE)])
    expect(tree.state.names['s:s']).toBe('Site')
    expect(tree.state.names['l:e']).toBe('Lib two')
  })
  it('opens the chain of a folder scope, level by level, and never the selected node itself', async () => {
    vi.mocked(invoke).mockImplementation(async (_command, values) => {
      if (values?.dir) return answer([])
      if (values?.drive_id) return answer([FOLDER])
      return values?.site_id ? answer([LIB, LIB2]) : answer([SITE])
    })
    const tree = createTree(() => undefined)
    await tree.reset({ sites: [], dates: [DAY], q: '' }, scopeChain({ fs: 's', fd: 'd', fp: 'a' }))
    const calls = vi.mocked(invoke).mock.calls.map((call) => call[1])
    expect(calls).toEqual([{ dates: [DAY] }, { site_id: 's', dates: [DAY] }, { site_id: 's', drive_id: 'd', dates: [DAY] }])
    expect(tree.state.open[nodeKey(LIB)]).toBeDefined()
    expect(tree.state.open[nodeKey(FOLDER)]).toBeUndefined()
  })
  it('opens a collapsed node again from the cache without a call', async () => {
    vi.mocked(invoke).mockImplementation(async (_command, values) => (values?.site_id ? answer([LIB]) : answer([SITE])))
    const tree = createTree(() => undefined)
    await tree.reset({ sites: [], dates: [DAY], q: '' }, [])
    tree.collapse(SITE)
    expect(tree.state.open[nodeKey(SITE)]).toBeUndefined()
    await tree.expand(SITE)
    expect(tree.state.open[nodeKey(SITE)]).toBeDefined()
    expect(vi.mocked(invoke)).toHaveBeenCalledTimes(2)
  })
  it('keeps a node closed when its level fails and reports the error', async () => {
    const errors: unknown[] = []
    vi.mocked(invoke).mockImplementation(async (_command, values) => {
      if (values?.drive_id) throw new Error('boom')
      return values?.site_id ? answer([LIB, LIB2]) : answer([SITE])
    })
    const tree = createTree((exc) => errors.push(exc))
    await tree.reset({ sites: [], dates: [DAY], q: '' }, [])
    await tree.expand(LIB)
    expect(errors).toHaveLength(1)
    expect(tree.state.open[nodeKey(LIB)]).toBeUndefined()
    expect(tree.state.levels[nodeKey(LIB)]).toBeUndefined()
  })
  it('drops the answer of a request that a new reset superseded', async () => {
    let release: (value: unknown) => void = () => undefined
    vi.mocked(invoke).mockImplementationOnce(() => new Promise((resolve) => (release = resolve)))
    vi.mocked(invoke).mockImplementation(async (_command, values) => (values?.site_id ? answer([]) : answer([{ ...SITE, name: 'new' }])))
    const tree = createTree(() => undefined)
    const first = tree.reset({ sites: [], dates: [DAY], q: '' }, [])
    await tree.reset({ sites: [], dates: [DAY], q: 'x' }, [])
    release(answer([{ ...SITE, name: 'old' }]))
    await first
    expect((tree.state.levels[ROOT_KEY] ?? []).map((node) => node.name)).toEqual(['new'])
  })
  it('asks the next page of a level with the offset of the nodes shown', async () => {
    vi.mocked(invoke).mockImplementation(async (_command, values) => (values?.offset ? { nodes: [LIB2], total: 2 } : { nodes: [LIB], total: 2 }))
    const tree = createTree(() => undefined)
    await tree.expand(SITE)
    await tree.more(SITE)
    expect(vi.mocked(invoke).mock.calls.map((call) => call[1])).toEqual([{ site_id: 's' }, { site_id: 's', offset: 1 }])
    expect(tree.state.levels[nodeKey(SITE)].map((node) => node.name)).toEqual(['Lib', 'Lib two'])
  })
})

describe('treekeys', () => {
  const levels = { [ROOT_KEY]: [SITE], [nodeKey(SITE)]: [LIB, LIB2], [nodeKey(LIB)]: [FOLDER] }
  const items = flattenVisible(levels, { [nodeKey(SITE)]: {} })
  const keys = items.map((item) => item.key)

  it('lists the visible items: all files, the site and its libraries', () => {
    expect(keys).toEqual([ALL_KEY, nodeKey(SITE), nodeKey(LIB), nodeKey(LIB2)])
    expect(flattenVisible(levels, { [nodeKey(SITE)]: {}, [nodeKey(LIB)]: {} }).map((item) => item.key)).toContain(nodeKey(FOLDER))
  })
  it('moves with the arrows, Home and End', () => {
    expect(treeKeyAction(items, nodeKey(SITE), 'ArrowDown')).toEqual({ type: 'focus', key: nodeKey(LIB) })
    expect(treeKeyAction(items, nodeKey(LIB), 'ArrowUp')).toEqual({ type: 'focus', key: nodeKey(SITE) })
    expect(treeKeyAction(items, nodeKey(SITE), 'Home')).toEqual({ type: 'focus', key: ALL_KEY })
    expect(treeKeyAction(items, nodeKey(SITE), 'End')).toEqual({ type: 'focus', key: nodeKey(LIB2) })
    expect(treeKeyAction(items, ALL_KEY, 'ArrowUp')).toEqual({ type: 'none' })
    expect(treeKeyAction(items, nodeKey(LIB2), 'ArrowDown')).toEqual({ type: 'none' })
  })
  it('opens with ArrowRight, goes to the first child, closes and goes to the parent with ArrowLeft', () => {
    expect(treeKeyAction(items, nodeKey(LIB), 'ArrowRight')).toEqual({ type: 'expand', key: nodeKey(LIB) })
    expect(treeKeyAction(items, nodeKey(SITE), 'ArrowRight')).toEqual({ type: 'focus', key: nodeKey(LIB) })
    expect(treeKeyAction(items, nodeKey(LIB2), 'ArrowRight')).toEqual({ type: 'none' })
    expect(treeKeyAction(items, nodeKey(SITE), 'ArrowLeft')).toEqual({ type: 'collapse', key: nodeKey(SITE) })
    expect(treeKeyAction(items, nodeKey(LIB), 'ArrowLeft')).toEqual({ type: 'focus', key: nodeKey(SITE) })
    expect(treeKeyAction(items, ALL_KEY, 'ArrowLeft')).toEqual({ type: 'none' })
  })
  it('selects with Enter and Space and ignores every other key', () => {
    expect(treeKeyAction(items, nodeKey(LIB), 'Enter')).toEqual({ type: 'select', key: nodeKey(LIB) })
    expect(treeKeyAction(items, nodeKey(LIB), ' ')).toEqual({ type: 'select', key: nodeKey(LIB) })
    expect(treeKeyAction(items, nodeKey(LIB), 'Tab')).toEqual({ type: 'none' })
    expect(treeKeyAction(items, 'missing', 'Enter')).toEqual({ type: 'none' })
  })
})

describe('breadcrumb', () => {
  const names = { 's:s': 'Site', 'l:d': 'Lib' }
  it('shows site, library and one crumb per folder segment, each crumb selecting its own scope', () => {
    expect(crumbsOf({ fs: 's', fd: 'd', fp: 'a/b' }, names)).toEqual([
      { label: 'Site', scope: { fs: 's' } },
      { label: 'Lib', scope: { fs: 's', fd: 'd' } },
      { label: 'a', scope: { fs: 's', fd: 'd', fp: 'a' } },
      { label: 'b', scope: { fs: 's', fd: 'd', fp: 'a/b' } },
    ])
  })
  it('has no crumb without a scope and falls back to the id for a name the tree has not shown', () => {
    expect(crumbsOf({}, names)).toEqual([])
    expect(crumbsOf({ fs: 'x', fd: 'y' }, {}).map((crumb) => crumb.label)).toEqual(['x', 'y'])
  })
  it('lists the ancestors a scope needs open, never the selected node', () => {
    expect(scopeChain({})).toEqual([])
    expect(scopeChain({ fs: 's' })).toEqual([])
    expect(scopeChain({ fs: 's', fd: 'd' })).toEqual([{ site_id: 's' }])
    expect(scopeChain({ fs: 's', fd: 'd', fp: 'a' })).toEqual([{ site_id: 's' }, { site_id: 's', drive_id: 'd' }])
    expect(scopeChain({ fs: 's', fd: 'd', fp: 'a/b' })).toEqual([{ site_id: 's' }, { site_id: 's', drive_id: 'd' }, { site_id: 's', drive_id: 'd', dir: 'a' }])
  })
})
