<script setup lang="ts">
// svc-snapshots (A1) and svc-sites (A6, search and paging) of the service page, page-libraries (A7, paging) of one site.
import { ref } from 'vue'
import { useCommand } from '../command'
import DataView from '../components/DataView.vue'
import ErrorBanner from '../components/ErrorBanner.vue'
import { PAGE_SIZE, hasNext, hrefFiles, hrefLibraries, hrefSites, intParam, isRecord, nextOffset, prevOffset, type Route } from '../lib'
import { invoke } from '../rpc'

const props = defineProps<{ kind: 'snapshots' | 'sites' | 'libraries'; route: Route }>()

const offset = intParam(props.route.query, 'offset', 0, PAGE_SIZE)
const search = (props.route.query.get('q') ?? '').slice(0, 128)
const siteId = props.route.params.id ?? ''
const typed = ref(search)

function load(): Promise<unknown> {
  if (props.kind === 'snapshots') return invoke('backup_snapshots', { limit: PAGE_SIZE })
  if (props.kind === 'sites') return invoke('backup_sites_list', { limit: PAGE_SIZE, offset, query: search === '' ? undefined : search })
  return invoke('backup_libraries_list', { site_id: siteId, limit: PAGE_SIZE, offset })
}
const { data, banner, settled } = useCommand(load)

const config = {
  snapshots: { title: 'Snapshots', page: 'svc-snapshots', row: 'snap-row', link: 'snap-open', field: 'id' },
  sites: { title: 'Sites', page: 'svc-sites', row: 'site-row', link: 'site-libraries', field: 'site_id' },
  libraries: { title: 'Libraries', page: 'page-libraries', row: 'library-row', link: undefined, field: undefined },
}[props.kind]

function href(item: Record<string, unknown>): string | null {
  const id = item[config.field ?? '']
  if (typeof id !== 'string' || id === '') return null
  return props.kind === 'snapshots' ? hrefFiles(id) : props.kind === 'sites' ? hrefLibraries(id) : null
}
function count(): number {
  const list = isRecord(data.value) ? (data.value.items ?? data.value.nodes) : null
  return Array.isArray(list) ? list.length : 0
}
function total(): unknown {
  return isRecord(data.value) ? data.value.total : undefined
}
function go(target: number): void {
  window.location.hash = props.kind === 'sites' ? hrefSites(search, target) : hrefLibraries(siteId, target)
}
function submitSearch(): void {
  window.location.hash = hrefSites(typed.value.trim().slice(0, 128), 0)
}
</script>

<template>
  <section v-if="settled" :data-testid="config.page">
    <h1>{{ config.title }}</h1>
    <form v-if="kind === 'sites'" @submit.prevent="submitSearch">
      <input v-model="typed" data-testid="search-input" type="search" maxlength="128" placeholder="Search sites" />
      <button type="submit" data-testid="search-submit">Search</button>
    </form>
    <ErrorBanner :banner="banner" />
    <DataView v-if="!banner" :data="data" :row-test-id="config.row" :link-test-id="config.link" :link-field="config.field" :href="href" />
    <p v-if="!banner && kind !== 'snapshots'">
      <button type="button" data-testid="page-prev" :disabled="offset === 0" @click="go(prevOffset(offset))">Previous</button>
      <button type="button" data-testid="page-next" :disabled="!hasNext(offset, total(), count())" @click="go(nextOffset(offset))">Next</button>
    </p>
  </section>
</template>
