<script setup lang="ts">
// svc-discovery (A8, polled every 30 s while visible), svc-help (A9), svc-info (A10) of the service page.
import { useCommand } from '../command'
import DataView from '../components/DataView.vue'
import ErrorBanner from '../components/ErrorBanner.vue'
import { POLL_DISCOVERY_MS, hrefHelp, hrefInfo, intParam, isRecord, type Route } from '../lib'
import { invoke } from '../rpc'

const props = defineProps<{ kind: 'discovery' | 'help' | 'info'; route: Route }>()

const command = props.route.query.get('cmd') ?? ''
const page = Math.max(1, intParam(props.route.query, 'page', 1))

function load(): Promise<unknown> {
  if (props.kind === 'discovery') return invoke('backup_discovery_status', {})
  if (props.kind === 'help') return invoke('help', { cmdname: command === '' ? undefined : command })
  return invoke('info', { page })
}
const { data, banner, settled, stale, lastGood } = useCommand(
  load,
  props.kind === 'discovery' ? { intervalMs: POLL_DISCOVERY_MS, keepGoing: () => true } : undefined,
)

function names(): string[] {
  const listed = isRecord(data.value) ? data.value.commands : null
  return isRecord(listed) ? Object.keys(listed).sort() : []
}
function go(target: number): void {
  window.location.hash = hrefInfo(target)
}
const titles = { discovery: 'Discovery status', help: 'Help', info: 'Info' }
</script>

<template>
  <section v-if="settled" :data-testid="'svc-' + kind">
    <h1>{{ titles[kind] }}</h1>
    <ErrorBanner :banner="banner" />
    <p v-if="stale" data-testid="stale">Showing the last good answer from {{ lastGood }}.</p>
    <DataView v-if="!banner" :data="data" />
    <p v-if="kind === 'help' && command !== ''"><a :href="hrefHelp()">All commands</a></p>
    <ul v-if="kind === 'help' && !banner">
      <li v-for="name in names()" :key="name"><a :href="hrefHelp(name)">{{ name }}</a></li>
    </ul>
    <p v-if="kind === 'info' && !banner">
      <button type="button" data-testid="page-prev" :disabled="page <= 1" @click="go(page - 1)">Previous</button>
      <button type="button" data-testid="page-next" @click="go(page + 1)">Next</button>
    </p>
  </section>
</template>
