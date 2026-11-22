<script setup lang="ts">
// Page toolbar of the result list: first, previous, "page N of M", next, last. One click emits `go` with the offset of the wanted page.
import { computed } from 'vue'
import { PAGE_SIZE, hasNext, nextOffset, prevOffset } from '../lib'

const props = defineProps<{ offset: number; total: number; count: number }>()
const emit = defineEmits<{ go: [offset: number] }>()

const pages = computed(() => Math.max(1, Math.ceil(props.total / PAGE_SIZE)))
const page = computed(() => Math.floor(props.offset / PAGE_SIZE) + 1)
const more = computed(() => hasNext(props.offset, props.total, props.count))
const lastOffset = computed(() => (pages.value - 1) * PAGE_SIZE)
</script>

<template>
  <div data-testid="result-pager" class="result-pager" role="group" aria-label="Страницы">
    <button type="button" data-testid="page-first" :disabled="props.offset === 0" @click="emit('go', 0)">В начало</button>
    <button type="button" data-testid="page-prev" :disabled="props.offset === 0" @click="emit('go', prevOffset(props.offset))">Назад</button>
    <span data-testid="page-info" class="page-info">Страница {{ page }} из {{ pages }}</span>
    <button type="button" data-testid="page-next" :disabled="!more" @click="emit('go', nextOffset(props.offset))">Вперёд</button>
    <button type="button" data-testid="page-last" :disabled="!more" @click="emit('go', lastOffset)">В конец</button>
  </div>
</template>

<style scoped>
.result-pager {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 0.5rem;
  margin: 0.5rem 0;
}
.result-pager button,
.result-pager .page-info {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  box-sizing: border-box;
  min-width: 2.5rem;
  min-height: 28px;
  padding: 0.25rem 0.9rem;
  border: 1px solid #8c959f;
  border-radius: 4px;
  background: #f6f8fa;
  color: #1f2328;
  font: inherit;
}
.result-pager button {
  cursor: pointer;
}
.result-pager button:hover:not(:disabled) {
  background: #eaeef2;
}
.result-pager button:disabled {
  color: #8c959f;
  cursor: default;
}
.result-pager .page-info {
  background: #fff;
}
</style>
