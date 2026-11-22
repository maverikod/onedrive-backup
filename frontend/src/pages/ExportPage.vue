<script setup lang="ts">
// A4 export card with the plain download link, A5 delete. Polls backup_download_status every 5 s ONLY while the answer is not final.
// As a page ('#/exports/<id>') it is page-export; inline in the side panel of the main page (exportId prop) it is the card inside export-panel,
// with the download link and the delete button shown first so they stay visible without scrolling the panel.
import { computed, ref } from 'vue'
import { useCommand, type Banner } from '../command'
import DataView from '../components/DataView.vue'
import ErrorBanner from '../components/ErrorBanner.vue'
import { POLL_EXPORT_MS, downloadUrl, hrefFiles, isExpired, isFinalExport, isRecord, type Route } from '../lib'
import { Aborted, AuthRequired, RpcError, auth, downloadWithKey, invoke } from '../rpc'

const props = defineProps<{ route?: Route; exportId?: string }>()
const emit = defineEmits<{ (event: 'gone'): void }>()

const inline = props.exportId !== undefined
const exportId = props.exportId ?? props.route?.params.id ?? ''
const STOP_CODES = [404, 410]

const { data, banner, settled } = useCommand(() => invoke('backup_download_status', { export_id: exportId }), {
  intervalMs: POLL_EXPORT_MS,
  keepGoing: (answer, failure) => {
    if (failure !== null) return !STOP_CODES.includes(Number(failure.code))
    return !isFinalExport(answer) && !isExpired(answer)
  },
})

const card = computed(() => (isRecord(data.value) ? data.value : null))
const expired = computed(() => isExpired(data.value))
const link = computed(() => (card.value ? downloadUrl(exportId, String(card.value.filename ?? '')) : null))
const failed = ref<Banner | null>(null)
const busy = ref(false)

/** Used only while a key is held after a 401: fetch with X-API-Key and save the blob. */
async function saveWithKey(event: Event): Promise<void> {
  event.preventDefault()
  if (link.value === null || card.value === null) return
  try {
    await downloadWithKey(link.value, String(card.value.filename))
  } catch (exc) {
    if (exc instanceof RpcError) failed.value = { code: exc.code, message: exc.message }
  }
}

/** Delete the export: exactly one backup_delete_export, no confirmation; the page goes back to the files of its snapshot, the inline card closes. */
async function remove(): Promise<void> {
  if (busy.value || card.value === null) return
  busy.value = true
  failed.value = null
  const snapshot = String(card.value.snapshot_id ?? '')
  try {
    await invoke('backup_delete_export', { export_id: exportId })
    if (inline) emit('gone')
    else window.location.hash = hrefFiles(snapshot)
  } catch (exc) {
    if (exc instanceof RpcError) failed.value = { code: exc.code, message: exc.message }
    else if (!(exc instanceof Aborted) && !(exc instanceof AuthRequired)) failed.value = { code: 'NETWORK', message: (exc as Error).message }
  } finally {
    busy.value = false
  }
}
</script>

<template>
  <section v-if="settled" :data-testid="inline ? undefined : 'page-export'">
    <h1 v-if="!inline">Export {{ exportId }}</h1>
    <ErrorBanner :banner="banner ?? failed" />
    <div v-if="card" data-testid="export-card" :class="{ 'inline-card': inline }">
      <DataView :data="card" />
      <p v-if="expired" data-testid="export-expired">This export has expired.</p>
      <p class="export-actions">
        <a v-if="link" data-testid="download-link" :href="link" download v-on="auth.hasKey ? { click: saveWithKey } : {}">Download</a>
        <button type="button" data-testid="export-delete" :disabled="busy" @click="remove()">Delete export</button>
      </p>
    </div>
  </section>
</template>

<style scoped>
.inline-card {
  display: flex;
  flex-direction: column;
}
.inline-card .export-actions {
  order: -1;
  margin: 0 0 0.5rem;
}
</style>
