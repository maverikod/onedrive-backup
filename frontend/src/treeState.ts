// The state of the folder tree of the main page: the loaded levels, the open nodes and the calls of backup_folder_children.
// A level is loaded lazily, one call per node; a node is open only after its level answered; every reset starts a new generation so the
// answer of a request the page has superseded (a new filter) is dropped and never rendered.

import { reactive } from 'vue'
import { invoke } from './rpc'
import {
  ROOT_KEY,
  addrKey,
  depth,
  nodeAddress,
  nodeKey,
  parentOf,
  parseNodes,
  treeParams,
  type Address,
  type TreeFilter,
  type TreeNode,
} from './tree'

export interface TreeState {
  levels: Record<string, TreeNode[]>
  totals: Record<string, number>
  open: Record<string, Address>
  busy: Record<string, boolean>
  names: Record<string, string>
  ready: boolean
}

/** Create the tree store; onError receives every failed call (the page shows its banner). */
export function createTree(onError: (exc: unknown) => void) {
  let generation = 0
  let filter: TreeFilter = { sites: [], dates: [], q: '' }
  const state = reactive<TreeState>({ levels: {}, totals: {}, open: {}, busy: {}, names: {}, ready: false })

  /** One backup_folder_children for a level (offset 0: the first page, replacing the level; later: the next page appended). */
  async function load(address: Address, offset = 0): Promise<boolean> {
    const mine = generation
    const key = addrKey(address)
    state.busy[key] = true
    try {
      const data = await invoke('backup_folder_children', treeParams(address, filter, offset))
      if (mine !== generation) return false
      const page = parseNodes(data)
      state.levels[key] = offset > 0 ? [...(state.levels[key] ?? []), ...page.nodes] : page.nodes
      state.totals[key] = page.total
      for (const node of page.nodes) {
        if (node.kind === 'site') state.names['s:' + node.site_id] = node.name
        else if (node.kind === 'library') state.names['l:' + node.drive_id] = node.name
      }
      return true
    } catch (exc) {
      if (mine === generation) onError(exc)
      return false
    } finally {
      if (mine === generation) delete state.busy[key]
    }
  }

  /** Open the node of an address when its parent level shows it with children: load its level, then mark it open. */
  async function reopen(address: Address, mine: number): Promise<void> {
    const key = addrKey(address)
    const node = (state.levels[addrKey(parentOf(address))] ?? []).find((item) => nodeKey(item) === key)
    if (node === undefined || !node.has_children) return
    if ((await load(address)) && mine === generation) state.open[key] = address
  }

  /** Compute the tree again for a filter: the roots, then the open nodes of before, the given chain and the only site, level by level. */
  async function reset(next: TreeFilter, chain: Address[]): Promise<void> {
    const keep = Object.values(state.open).map((address) => ({ ...address }))
    generation += 1
    const mine = generation
    filter = next
    state.levels = {}
    state.totals = {}
    state.open = {}
    state.busy = {}
    state.ready = false
    if (!(await load({}))) return
    state.ready = true
    const wanted = new Map<string, Address>()
    for (const address of [...keep, ...chain]) wanted.set(addrKey(address), address)
    const roots = state.levels[ROOT_KEY] ?? []
    if (roots.length === 1) wanted.set(nodeKey(roots[0]), nodeAddress(roots[0]))
    const levels = [...new Set([...wanted.values()].map(depth))].sort((a, b) => a - b)
    for (const level of levels) {
      await Promise.all([...wanted.values()].filter((address) => depth(address) === level).map((address) => reopen(address, mine)))
      if (mine !== generation) return
    }
  }

  /** Open a node: its level is loaded once (a collapsed node opens again from the cache without a call). */
  async function expand(node: TreeNode): Promise<void> {
    const address = nodeAddress(node)
    const key = addrKey(address)
    if (state.open[key] !== undefined || state.busy[key]) return
    const mine = generation
    if (state.levels[key] === undefined && !(await load(address))) return
    if (mine === generation) state.open[key] = address
  }

  function collapse(node: TreeNode): void {
    delete state.open[nodeKey(node)]
  }

  /** The next page of the children of an open node. */
  async function more(node: TreeNode): Promise<void> {
    const address = nodeAddress(node)
    const key = addrKey(address)
    if (state.busy[key]) return
    await load(address, (state.levels[key] ?? []).length)
  }

  /** The loaded node with a key, or undefined. */
  function find(key: string): TreeNode | undefined {
    for (const level of Object.values(state.levels)) {
      const found = level.find((item) => nodeKey(item) === key)
      if (found !== undefined) return found
    }
    return undefined
  }

  /** Remember the names of the sites of backup_filter_options for the breadcrumb. */
  function seedSites(sites: { site_id: string; name: string }[]): void {
    for (const site of sites) state.names['s:' + site.site_id] = site.name
  }

  return { state, reset, expand, collapse, more, find, seedSites }
}

export type TreeStore = ReturnType<typeof createTree>
