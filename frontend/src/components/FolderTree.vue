<script setup lang="ts">
// The left region of the main page: the tree of the backed-up files (all files, sites, libraries, folders) with the keyboard of a WAI-ARIA tree.
// A click or Enter selects a node (the page searches inside it); the toggle or the right arrow opens a node. The tree holds no search of its own.
import { computed, ref } from 'vue'
import type { Scope } from '../lib'
import { ALL_KEY, ROOT_KEY, flattenVisible, nodeKey, scopeOfNode, treeKeyAction } from '../tree'
import type { TreeStore } from '../treeState'
import FolderTreeNode from './FolderTreeNode.vue'

const props = defineProps<{ tree: TreeStore; scope: Scope }>()
const emit = defineEmits<{ select: [scope: Scope] }>()

const root = ref<HTMLElement | null>(null)
const focusKey = ref(ALL_KEY)
const roots = computed(() => props.tree.state.levels[ROOT_KEY] ?? [])
const noScope = computed(() => !props.scope.fs)

function focusItem(key: string): void {
  const items = root.value !== null ? Array.from(root.value.querySelectorAll<HTMLElement>('[data-node-key]')) : []
  const found = items.find((item) => item.dataset.nodeKey === key)
  if (found !== undefined) found.focus()
}

function onFocusIn(event: FocusEvent): void {
  const key = (event.target as HTMLElement).dataset?.nodeKey
  if (key !== undefined) focusKey.value = key
}

async function onKey(event: KeyboardEvent): Promise<void> {
  const current = (event.target as HTMLElement).dataset?.nodeKey
  if (current === undefined) return
  const action = treeKeyAction(flattenVisible(props.tree.state.levels, props.tree.state.open), current, event.key)
  if (action.type === 'none' || action.key === undefined) return
  event.preventDefault()
  const node = props.tree.find(action.key)
  if (action.type === 'focus') focusItem(action.key)
  else if (action.type === 'select') emit('select', node !== undefined ? scopeOfNode(node) : {})
  else if (node !== undefined && action.type === 'expand') await props.tree.expand(node)
  else if (node !== undefined && action.type === 'collapse') props.tree.collapse(node)
}
</script>

<template>
  <div ref="root" data-testid="folder-tree" role="tree" aria-label="Каталоги" class="folder-tree" @keydown="onKey" @focusin="onFocusIn">
    <div
      data-testid="tree-all"
      role="treeitem"
      class="tree-all"
      :class="{ selected: noScope }"
      :data-node-key="ALL_KEY"
      aria-level="1"
      :aria-selected="String(noScope)"
      :tabindex="focusKey === ALL_KEY ? 0 : -1"
      @click="emit('select', {})"
    >
      Все файлы
    </div>
    <ul role="group" class="tree-root">
      <FolderTreeNode v-for="node in roots" :key="nodeKey(node)" :node="node" :level="1" :tree="tree" :scope="scope" :focus-key="focusKey" @select="emit('select', $event)" />
    </ul>
    <p v-if="tree.state.busy[ROOT_KEY]" data-testid="tree-loading" class="tree-note">Загрузка…</p>
    <p v-if="tree.state.ready && roots.length === 0" data-testid="tree-empty" class="tree-note">Нет папок с подходящими файлами</p>
  </div>
</template>

<style scoped>
.folder-tree {
  box-sizing: border-box;
  min-height: 0;
  overflow-y: auto;
  overflow-x: auto;
  padding: 0.5rem;
  background: #fff;
  border: 1px solid #d0d7de;
}
.tree-all {
  padding: 0.1rem 0.25rem;
  cursor: pointer;
  outline: none;
}
.tree-all:focus {
  outline: 2px solid #0969da;
  outline-offset: -2px;
}
.tree-all.selected {
  background: #ddf4ff;
  font-weight: 600;
}
.tree-root {
  margin: 0;
  padding: 0;
}
.tree-note {
  margin: 0.5rem 0.25rem;
  color: #57606a;
  font-size: 0.9rem;
}
@media (max-width: 899px) {
  .folder-tree {
    max-height: 40vh;
  }
}
</style>
