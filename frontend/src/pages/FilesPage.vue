<script setup lang="ts">
// A2 files of one snapshot (prefix and offset live in the hash) with the export start controls of A3.
import { ref } from 'vue'
import { useCommand, type Banner } from '../command'
import DataView from '../components/DataView.vue'
import ErrorBanner from '../components/ErrorBanner.vue'
import { PAGE_SIZE, hasNext, hrefExport, hrefFiles, intParam, isRecord, nextOffset, prevOffset, type Route } from '../lib'
import { Aborted, AuthRequired, RpcError, invoke } from '../rpc'

const props = defineProps<{ route: Route }>()

const snapshotId = props.route.params.id ?? ''
const prefix = props.route.query.get('prefix') ?? ''
const offset = intParam(props.route.query, 'offset', 0, PAGE_SIZE)

const { data, banner, settled } = useCommand(() =>
  invoke('backup_list_files', { snapshot_id: snapshotId, prefix, offset, limit: PAGE_SIZE }),
)

const busy = ref(false)
const failed = ref<Banner | null>(null)

function href(item: Record<string, unknown>): string | null {
  return (item.type === 'dir' || item.type === 'directory') && typeof item.path === 'string' ? hrefFiles(snapshotId, item.path) : null
}
function count(): number {
  const list = isRecord(data.value) ? (data.value.items ?? data.value.nodes) : null
  return Array.isArray(list) ? list.length : 0
}
function go(target: number): void {
  window.location.hash = hrefFiles(snapshotId, prefix, target)
}

/** Export the whole snapshot (no file path) or one file: exactly one backup_prepare_download, the button is disabled until the answer. */
async function start(filePath?: string): Promise<void> {
  if (busy.value) return
  busy.value = true
  failed.value = null
  try {
    const result = await invoke('backup_prepare_download', { snapshot_id: snapshotId, file_path: filePath })
    const id = isRecord(result) ? result.export_id : undefined
    if (typeof id === 'string' && id !== '') window.location.hash = hrefExport(id)
    else failed.value = { code: 'BAD_RESPONSE', message: 'the service answered without an export id' }
  } catch (exc) {
    if (exc instanceof RpcError) failed.value = { code: exc.code, message: exc.message }
    else if (!(exc instanceof Aborted) && !(exc instanceof AuthRequired)) failed.value = { code: 'NETWORK', message: (exc as Error).message }
  } finally {
    busy.value = false
  }
}
</script>

<template>
  <section v-if="settled" data-testid="page-files">
    <h1>Files of snapshot {{ snapshotId }}</h1>
    <ErrorBanner :banner="banner ?? failed" />
    <template v-if="!banner">
      <p>
        <button type="button" data-testid="export-start-snapshot" :disabled="busy" @click="start()">Export the whole snapshot</button>
      </p>
      <DataView :data="data" row-test-id="file-row" link-test-id="file-open" link-field="path" :href="href">
        <template #actions="{ item }">
          <button v-if="item.type === 'file'" type="button" data-testid="export-start-file" :data-path="String(item.path)" :disabled="busy" @click="start(String(item.path))">Export</button>
        </template>
      </DataView>
      <p>
        <button type="button" data-testid="page-prev" :disabled="offset === 0" @click="go(prevOffset(offset))">Previous</button>
        <button type="button" data-testid="page-next" :disabled="!hasNext(offset, isRecord(data) ? data.total : undefined, count())" @click="go(nextOffset(offset))">Next</button>
      </p>
    </template>
  </section>
</template>
