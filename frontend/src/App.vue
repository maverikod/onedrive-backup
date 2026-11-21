<script setup lang="ts">
// Shell: nav on every page, the key form (only after a 401), logout, and the hash router.
import { computed, nextTick, onBeforeUnmount, ref, watch } from 'vue'
import ErrorBanner from './components/ErrorBanner.vue'
import { parseHash } from './lib'
import ExportPage from './pages/ExportPage.vue'
import FilesPage from './pages/FilesPage.vue'
import ListPage from './pages/ListPage.vue'
import MainPage from './pages/MainPage.vue'
import ServicePage from './pages/ServicePage.vue'
import { auth, forgetAndAbort, setKey } from './rpc'

const hash = ref(window.location.hash)
const route = computed(() => parseHash(hash.value))
function onHashChange(): void {
  hash.value = window.location.hash
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
  main: MainPage,
  service: ServicePage,
  libraries: ListPage,
  files: FilesPage,
  export: ExportPage,
}
const viewProps = computed(() => (route.value.name === 'libraries' ? { kind: 'libraries', route: route.value } : { route: route.value }))
</script>

<template>
  <nav data-testid="nav">
    <a data-testid="nav-search" href="#/">Поиск файлов</a>
    <a data-testid="nav-service" href="#/service">Служебные</a>
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
      <a data-testid="signin" href="#/">Sign in</a>
    </section>
    <section v-else-if="route.name === 'notfound'" data-testid="page-notfound">
      <ErrorBanner :banner="notFound" />
    </section>
    <component :is="views[route.name]" v-else :key="hash" v-bind="viewProps" />
  </main>
</template>
