<script setup lang="ts">
// One node of the folder tree (site, library or folder) with its open children, the 'more' button and the loading mark. The element is the
// focusable treeitem; the label, the count and the toggle are plain parts of its row.
import { computed } from 'vue'
import type { Scope } from '../lib'
import { TREE_PAGE, formatCount, nodeAddress, nodeKey, scopeOfNode, type TreeNode } from '../tree'
import { addrKey } from '../tree'
import type { TreeStore } from '../treeState'

const props = defineProps<{ node: TreeNode; level: number; tree: TreeStore; scope: Scope; focusKey: string }>()
const emit = defineEmits<{ select: [scope: Scope] }>()

const key = computed(() => nodeKey(props.node))
const level = computed(() => props.tree.state.levels[addrKey(nodeAddress(props.node))] ?? [])
const isOpen = computed(() => props.node.has_children && props.tree.state.open[key.value] !== undefined)
const rest = computed(() => (props.tree.state.totals[key.value] ?? 0) - level.value.length)
const busy = computed(() => props.tree.state.busy[key.value] === true)
const selected = computed(() => {
  const now = props.scope
  const node = props.node
  if (node.kind === 'site') return now.fs === node.site_id && !now.fd
  if (node.kind === 'library') return now.fs === node.site_id && now.fd === node.drive_id && !now.fp
  return now.fs === node.site_id && now.fd === node.drive_id && now.fp === node.dir
})

function toggle(): void {
  if (isOpen.value) props.tree.collapse(props.node)
  else void props.tree.expand(props.node)
}
</script>

<template>
  <li
    data-testid="tree-node"
    role="treeitem"
    class="tree-node"
    :class="{ selected }"
    :data-kind="node.kind"
    :data-site-id="node.site_id"
    :data-drive-id="node.drive_id"
    :data-dir="node.dir"
    :data-raw="String(node.file_count)"
    :data-node-key="key"
    :aria-level="props.level"
    :aria-expanded="node.has_children ? String(isOpen) : undefined"
    :aria-selected="String(selected)"
    :tabindex="props.focusKey === key ? 0 : -1"
  >
    <div class="tree-row" @click="emit('select', scopeOfNode(node))">
      <span v-if="node.has_children" data-testid="tree-toggle" role="button" class="tree-toggle" :aria-label="isOpen ? 'Свернуть' : 'Развернуть'" @click.stop="toggle">{{ isOpen ? '▾' : '▸' }}</span>
      <span v-else class="tree-spacer"></span>
      <span data-testid="tree-label" class="tree-label">{{ node.name }}</span>
      <span data-testid="tree-count" class="tree-count" :data-raw="String(node.file_count)">{{ formatCount(node.file_count) }}</span>
      <span v-if="busy" data-testid="tree-loading" class="tree-loading">…</span>
    </div>
    <ul v-if="isOpen" role="group" class="tree-children">
      <FolderTreeNode v-for="child in level" :key="nodeKey(child)" :node="child" :level="props.level + 1" :tree="tree" :scope="scope" :focus-key="focusKey" @select="emit('select', $event)" />
      <li v-if="rest > 0" role="none" class="tree-more-row">
        <button type="button" data-testid="tree-more" class="tree-more" :disabled="busy" @click="tree.more(node)">Ещё {{ Math.min(TREE_PAGE, rest) }}</button>
      </li>
    </ul>
  </li>
</template>

<style scoped>
.tree-node {
  list-style: none;
  outline: none;
}
.tree-node:focus > .tree-row {
  outline: 2px solid #0969da;
  outline-offset: -2px;
}
.tree-row {
  display: flex;
  align-items: baseline;
  gap: 0.35rem;
  padding: 0.1rem 0.25rem;
  cursor: pointer;
  white-space: nowrap;
}
.tree-node.selected > .tree-row {
  background: #ddf4ff;
  font-weight: 600;
}
.tree-toggle,
.tree-spacer {
  display: inline-block;
  width: 1rem;
  text-align: center;
  flex: none;
}
.tree-label {
  overflow: hidden;
  text-overflow: ellipsis;
}
.tree-count {
  margin-left: auto;
  color: #57606a;
  font-size: 0.85rem;
  flex: none;
}
.tree-children {
  margin: 0;
  padding: 0 0 0 1rem;
}
.tree-more-row {
  list-style: none;
  padding: 0.1rem 0.25rem;
}
</style>
