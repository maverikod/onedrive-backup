<script setup lang="ts">
// Renders a command result as it is: summary cells for the scalar fields and one table row per list item.
// Every cell carries data-field (the field name, dotted for nested fields) and data-raw (the exact raw value).
// Nothing is invented: no data renders nothing, an empty list renders an empty state, never fixtures.
import { computed } from 'vue'
import { flatten, isRecord, type Cell } from '../lib'

const props = defineProps<{
  data: unknown
  rowTestId?: string
  linkTestId?: string
  linkField?: string
  href?: (item: Record<string, unknown>) => string | null
}>()

const LIST_KEYS = ['items', 'nodes', 'entries']

const listKey = computed<string | null>(() => {
  if (!isRecord(props.data)) return null
  return LIST_KEYS.find((name) => Array.isArray((props.data as Record<string, unknown>)[name])) ?? null
})
const items = computed<Record<string, unknown>[] | null>(() => {
  if (listKey.value === null) return null
  return ((props.data as Record<string, unknown>)[listKey.value] as unknown[]).filter(isRecord)
})
const summary = computed<Cell[]>(() => {
  if (!isRecord(props.data)) return flatten(props.data)
  const rest: Record<string, unknown> = { ...props.data }
  if (listKey.value !== null) delete rest[listKey.value]
  return flatten(rest)
})
const rows = computed(() => (items.value ?? []).map((item) => ({ item, cells: flatten(item) })))
const columns = computed<string[]>(() => {
  const seen: string[] = []
  for (const row of rows.value) for (const cell of row.cells) if (!seen.includes(cell.field)) seen.push(cell.field)
  return seen
})

function cellOf(cells: Cell[], field: string): Cell | undefined {
  return cells.find((cell) => cell.field === field)
}
function linkOf(item: Record<string, unknown>, field: string): string | null {
  return props.href && props.linkTestId && field === props.linkField ? props.href(item) : null
}
</script>

<template>
  <div v-if="data !== null && data !== undefined" class="data-view">
    <table v-if="summary.length" class="summary">
      <tbody>
        <tr v-for="cell in summary" :key="cell.field">
          <th>{{ cell.field }}</th>
          <td :data-field="cell.field" :data-raw="cell.raw">{{ cell.text }}</td>
        </tr>
      </tbody>
    </table>
    <template v-if="items">
      <p v-if="items.length === 0" data-testid="empty">Nothing to show.</p>
      <table v-else class="rows">
        <thead>
          <tr>
            <th v-for="column in columns" :key="column">{{ column }}</th>
            <th v-if="$slots.actions"></th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="(row, index) in rows" :key="index" :data-testid="rowTestId">
            <td v-for="column in columns" :key="column" :data-field="column" :data-raw="cellOf(row.cells, column)?.raw">
              <a v-if="linkOf(row.item, column)" :data-testid="linkTestId" :href="linkOf(row.item, column) as string">{{ cellOf(row.cells, column)?.text }}</a>
              <template v-else>{{ cellOf(row.cells, column)?.text }}</template>
            </td>
            <td v-if="$slots.actions"><slot name="actions" :item="row.item" /></td>
          </tr>
        </tbody>
      </table>
    </template>
  </div>
</template>
