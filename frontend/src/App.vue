<script setup lang="ts">
// Shell: nav on every page, the key form (only after a 401), logout, and the hash router.
import { computed, nextTick, onBeforeUnmount, ref, watch } from 'vue'
import ErrorBanner from './components/ErrorBanner.vue'
import { parseHash } from './lib'
import ExportPage from './pages/ExportPage.vue'
import FilesPage from './pages/FilesPage.vue'
import ListPage from './pages/ListPage.vue'
import StatusPage from './pages/StatusPage.vue'
import { auth, forgetAndAbort, setKey } from './rpc'

function currentHash(): string {
  if (parseHash(window.location.hash).name === 'redirect') window.history.replaceState(null, '', '#/snapshots')
  return window.location.hash
}

const hash = ref(currentHash())
const route = computed(() => parseHash(hash.value))
function onHashChange(): void {
  hash.value = currentHash()
}
window.addEventListener('hashchange', onHashChange)
onBeforeUnmount(() => window.removeEventListener('hashchange', onHashChange))

const draft = ref('')
const keyInput = ref<HTMLInputElement | null>(null)
watch(
  () => auth.needKey,
  async (needed) => {
    if (needed) {
      await nextTick()
      keyInput.value?.focus()
    }
  },
)
function submitKey(): void {
  const typed = draft.value
  draft.value = ''
  if (typed !== '') setKey(typed)
}

/** Logout: forget the key, abort everything in flight, stop every poll (the pages unmount) and send no command until the user navigates. */
function logout(): void {
  forgetAndAbort()
  window.location.hash = '#/signed-out'
}

const notFound = { code: 404, message: 'route not found' }
const views: Record<string, unknown> = {
  snapshots: ListPage,
  sites: ListPage,
  libraries: ListPage,
  files: FilesPage,
  export: ExportPage,
  discovery: StatusPage,
  help: StatusPage,
  info: StatusPage,
}
const viewProps = computed(() => {
  const name = route.value.name
  return ['snapshots', 'sites', 'libraries', 'discovery', 'help', 'info'].includes(name) ? { kind: name, route: route.value } : { route: route.value }
})
</script>

<template>
  <nav data-testid="nav">
    <a data-testid="nav-snapshots" href="#/snapshots">Snapshots</a>
    <a data-testid="nav-sites" href="#/sites">Sites</a>
    <a data-testid="nav-discovery" href="#/discovery">Discovery</a>
    <a data-testid="nav-help" href="#/help">Help</a>
    <a data-testid="nav-info" href="#/info">Info</a>
    <button type="button" data-testid="logout" @click="logout">Log out</button>
  </nav>
  <form v-if="auth.needKey" class="key-form" data-testid="key-form" @submit.prevent="submitKey">
    <label>
      Key
      <input ref="keyInput" v-model="draft" data-testid="key-input" type="password" name="api-key" autocomplete="off" />
    </label>
    <button type="submit" data-testid="key-submit">Use key</button>
  </form>
  <main>
    <section v-if="route.name === 'signed-out'" data-testid="page-signed-out">
      <p>Signed out. No request is sent until you open a page.</p>
      <a data-testid="signin" href="#/snapshots">Sign in</a>
    </section>
    <section v-else-if="route.name === 'notfound'" data-testid="page-notfound">
      <ErrorBanner :banner="notFound" />
    </section>
    <component :is="views[route.name]" v-else :key="hash" v-bind="viewProps" />
  </main>
</template>
