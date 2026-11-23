// Pure rules of the folder tree of the main page (matrix 10.21.2, 10.21.6): the node model, the addresses of its levels, the call parameters,
// the visible items for the keyboard, the keyboard rules and the breadcrumb of the folder scope.

import { isRecord, type Scope } from './lib'

export type NodeKind = 'site' | 'library' | 'folder'

export interface TreeNode {
  kind: NodeKind
  site_id: string
  drive_id: string
  dir: string
  name: string
  file_count: number
  direct_count: number
  has_children: boolean
}

/** The address of one level of the tree: no site is the list of sites, a site its libraries, a library its top folders, a folder its subfolders. */
export interface Address {
  site_id?: string
  drive_id?: string
  dir?: string
}

/** The filters the tree is computed for: the same ticked sites, dates and name part the result list shows (AND with the folder scope). */
export interface TreeFilter {
  sites: string[]
  dates: string[]
  q: string
}

export const ROOT_KEY = 'root'
export const ALL_KEY = 'all'
const SEP = '\u0001'

/** The key of a level (also the key of the node that owns the level). */
export function addrKey(address: Address): string {
  if (address.site_id === undefined) return ROOT_KEY
  return [address.site_id, address.drive_id ?? '', address.dir ?? ''].join(SEP)
}

/** The address of the children of a node. */
export function nodeAddress(node: TreeNode): Address {
  if (node.kind === 'site') return { site_id: node.site_id }
  if (node.kind === 'library') return { site_id: node.site_id, drive_id: node.drive_id }
  return { site_id: node.site_id, drive_id: node.drive_id, dir: node.dir }
}

export const nodeKey = (node: TreeNode): string => addrKey(nodeAddress(node))

/** 0 for the list of sites, 1 for the libraries of a site, 2 for the top folders of a library, 2 + segments below. */
export function depth(address: Address): number {
  if (address.site_id === undefined) return 0
  if (address.drive_id === undefined || address.drive_id === '') return 1
  if (address.dir === undefined || address.dir === '') return 2
  return 2 + address.dir.split('/').length
}

/** The level whose node list holds the node that owns this level. */
export function parentOf(address: Address): Address {
  const level = depth(address)
  if (level <= 1) return {}
  if (level === 2) return { site_id: address.site_id }
  const dir = address.dir ?? ''
  const cut = dir.lastIndexOf('/')
  return cut < 0 ? { site_id: address.site_id, drive_id: address.drive_id } : { site_id: address.site_id, drive_id: address.drive_id, dir: dir.slice(0, cut) }
}

/** The scope a click on a node selects. */
export function scopeOfNode(node: TreeNode): Scope {
  if (node.kind === 'site') return { fs: node.site_id }
  if (node.kind === 'library') return { fs: node.site_id, fd: node.drive_id }
  return { fs: node.site_id, fd: node.drive_id, fp: node.dir }
}

/** The levels that must be open to show the node of a scope: the ancestors of the selected node, never the node itself. */
export function scopeChain(scope: Scope): Address[] {
  const chain: Address[] = []
  if (!scope.fs || !scope.fd) return chain
  chain.push({ site_id: scope.fs })
  if (!scope.fp) return chain
  chain.push({ site_id: scope.fs, drive_id: scope.fd })
  const parts = scope.fp.split('/')
  for (let count = 1; count < parts.length; count += 1) chain.push({ site_id: scope.fs, drive_id: scope.fd, dir: parts.slice(0, count).join('/') })
  return chain
}

/** The parameters of backup_folder_children: the address, the filters (an empty one is omitted) and the offset of a further page (the first page sends none). */
export function treeParams(address: Address, filter: TreeFilter, offset = 0): Record<string, unknown> {
  const name = filter.q.trim()
  return {
    site_id: address.site_id,
    drive_id: address.drive_id,
    dir: address.dir,
    site_ids: filter.sites.length ? [...filter.sites] : undefined,
    dates: filter.dates.length ? [...filter.dates] : undefined,
    name_part: name === '' ? undefined : name,
    offset: offset > 0 ? offset : undefined,
  }
}

/** The nodes and the total of one answer of backup_folder_children; a malformed node is skipped. */
export function parseNodes(data: unknown): { nodes: TreeNode[]; total: number } {
  const list = isRecord(data) && Array.isArray(data.nodes) ? data.nodes : []
  const nodes: TreeNode[] = []
  for (const item of list) {
    if (!isRecord(item)) continue
    const kind = item.kind
    if (kind !== 'site' && kind !== 'library' && kind !== 'folder') continue
    nodes.push({
      kind,
      site_id: String(item.site_id ?? ''),
      drive_id: String(item.drive_id ?? ''),
      dir: String(item.dir ?? ''),
      name: String(item.name ?? ''),
      file_count: Number(item.file_count ?? 0),
      direct_count: Number(item.direct_count ?? 0),
      has_children: item.has_children === true,
    })
  }
  const total = isRecord(data) && typeof data.total === 'number' ? data.total : nodes.length
  return { nodes, total }
}

/** A count with a no-break space as the thousands separator: 12345 is shown as 12 345. */
export const formatCount = (count: number): string => String(count).replace(/\B(?=(\d{3})+(?!\d))/g, ' ')

// ---- keyboard ----

export interface VisibleItem {
  key: string
  parent: string | null
  toggle: boolean
  open: boolean
}

/** The visible items in display order: the node of all files, then every node of an open level below its parent. */
export function flattenVisible(levels: Record<string, TreeNode[]>, open: Record<string, unknown>): VisibleItem[] {
  const out: VisibleItem[] = [{ key: ALL_KEY, parent: null, toggle: false, open: false }]
  const walk = (address: Address, parent: string | null): void => {
    for (const node of levels[addrKey(address)] ?? []) {
      const key = nodeKey(node)
      const shown = node.has_children && open[key] !== undefined
      out.push({ key, parent, toggle: node.has_children, open: shown })
      if (shown) walk(nodeAddress(node), key)
    }
  }
  walk({}, null)
  return out
}

export interface KeyAction {
  type: 'none' | 'focus' | 'expand' | 'collapse' | 'select'
  key?: string
}

const NONE: KeyAction = { type: 'none' }

/** What a key does on the focused item (WAI-ARIA tree): arrows move, open and close, Home and End jump, Enter and Space select. */
export function treeKeyAction(items: VisibleItem[], current: string, key: string): KeyAction {
  const index = items.findIndex((item) => item.key === current)
  if (index < 0) return NONE
  const item = items[index]
  if (key === 'Home') return { type: 'focus', key: items[0].key }
  if (key === 'End') return { type: 'focus', key: items[items.length - 1].key }
  if (key === 'ArrowDown') return index + 1 < items.length ? { type: 'focus', key: items[index + 1].key } : NONE
  if (key === 'ArrowUp') return index > 0 ? { type: 'focus', key: items[index - 1].key } : NONE
  if (key === 'ArrowRight') {
    if (item.toggle && !item.open) return { type: 'expand', key: current }
    const next = items[index + 1]
    return item.open && next !== undefined && next.parent === current ? { type: 'focus', key: next.key } : NONE
  }
  if (key === 'ArrowLeft') {
    if (item.open) return { type: 'collapse', key: current }
    return item.parent !== null ? { type: 'focus', key: item.parent } : NONE
  }
  if (key === 'Enter' || key === ' ') return { type: 'select', key: current }
  return NONE
}

// ---- breadcrumb of the folder scope ----

export interface Crumb {
  label: string
  scope: Scope
}

/** The crumbs site > library > folders of a scope; a name the tree has not shown is the id, a folder crumb is its segment. */
export function crumbsOf(scope: Scope, names: Record<string, string>): Crumb[] {
  if (!scope.fs) return []
  const out: Crumb[] = [{ label: names['s:' + scope.fs] ?? scope.fs, scope: { fs: scope.fs } }]
  if (!scope.fd) return out
  out.push({ label: names['l:' + scope.fd] ?? scope.fd, scope: { fs: scope.fs, fd: scope.fd } })
  const parts = scope.fp ? scope.fp.split('/') : []
  parts.forEach((part, index) => out.push({ label: part, scope: { fs: scope.fs, fd: scope.fd, fp: parts.slice(0, index + 1).join('/') } }))
  return out
}
