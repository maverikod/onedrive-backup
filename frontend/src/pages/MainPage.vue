<script setup lang="ts">
// The single filter page '#/': site and date checkboxes, the file name field with its autocomplete and, below them, three regions in one row:
// the folder tree (left), the result list of the selected folder (middle: breadcrumb with the recursive switch, page toolbar, exactly three columns:
// site, file name, date) and the side panel `detail-panel` (right) with the properties of the clicked row and its export controls. The tree and the
// filters work together by AND: the tree shows only folders with matching files, the list shows the files of the selected folder that match.
// The filter state and the folder scope live in the hash (pushState, no remount).
import { computed, onBeforeUnmount, onMounted, onUpdated, ref, watch } from 'vue'
import type { Banner } from '../command'
import ErrorBanner from '../components/ErrorBanner.vue'
import FolderTree from '../components/FolderTree.vue'
import ResultPager from '../components/ResultPager.vue'
import {
  SUGGEST_DELAY_MS,
  SUGGEST_LIMIT,
  copyMarker,
  escapeName,
  formatBytes,
  formatSnapshot,
  hasFilter,
  hrefMain,
  isRecord,
  parseFilter,
  scopeOf,
  scopeValues,
  searchValues,
  suggestible,
  withScope,
  type Filter,
  type Route,
  type Scope,
} from '../lib'
import { Aborted, AuthRequired, RpcError, auth, invoke } from '../rpc'
import { crumbsOf, scopeChain } from '../tree'
import { createTree } from '../treeState'
import ExportPage from './ExportPage.vue'

const props = defineProps<{ route: Route }>()

const sites = ref<{ site_id: string; name: string }[]>([])
const dates = ref<string[]>([])
const tickedSites = ref<string[]>([])
const tickedDates = ref<string[]>([])
const typed = ref('')
const dropped = ref(false)
const result = ref<Record<string, unknown> | null>(null)
const banner = ref<Banner | null>(null)
const exportId = ref('')
const selected = ref<Record<string, unknown> | null>(null)
const busy = ref(false)
const zone = ref('Europe/Kyiv')
const applied = ref<Filter>(parseFilter(props.route.query))
const suggestions = ref<string[]>([])
const active = ref(-1)
const grid = ref<HTMLElement | null>(null)
const gridHeight = ref('')

let alive = true
let timer: ReturnType<typeof setTimeout> | null = null
let pending: AbortController | null = null
let lastAsked = ''
let searchSeq = 0

function fail(exc: unknown): void {
  if (exc instanceof Aborted || exc instanceof AuthRequired) return
  banner.value = exc instanceof RpcError ? { code: exc.code, message: exc.message } : { code: 'NETWORK', message: (exc as Error).message }
}

const tree = createTree(fail)
const scope = computed<Scope>(() => scopeOf(applied.value))
const crumbs = computed(() => crumbsOf(scope.value, tree.state.names))

/** One backup_filter_options: the sites that have backups and the dates of the ticked sites. */
async function refreshOptions(): Promise<boolean> {
  try {
    const data = await invoke('backup_filter_options', { site_ids: tickedSites.value.length ? [...tickedSites.value] : undefined })
    if (!alive || !isRecord(data)) return false
    const listed = Array.isArray(data.sites) ? data.sites.filter(isRecord) : []
    sites.value = listed.map((item) => ({ site_id: String(item.site_id), name: String(item.name) }))
    tree.seedSites(sites.value)
    dates.value = (Array.isArray(data.dates) ? data.dates.filter(isRecord) : []).map((item) => String(item.date))
    if (typeof data.timezone === 'string') zone.value = data.timezone
    banner.value = null
    return true
  } catch (exc) {
    fail(exc)
    return false
  }
}

/**
 * One backup_search_files for the filter; a command error shows the banner and no rows. Only the newest search may render:
 * the answer of a superseded search (the default view that is still running when the user applies a filter) is dropped.
 */
async function runSearch(filter: Filter): Promise<void> {
  const mine = ++searchSeq
  try {
    const data = await invoke('backup_search_files', searchValues(filter))
    if (!alive || mine !== searchSeq) return
    result.value = isRecord(data) ? data : null
    banner.value = null
  } catch (exc) {
    if (!alive || mine !== searchSeq) return
    result.value = null
    fail(exc)
  }
}

/** Apply a filter: the search always runs; the tree is computed again only when the filters were applied (reload), not for a scope, a page or the recursive switch. */
async function applyFilter(filter: Filter, remember = true, reload = false): Promise<void> {
  applied.value = filter
  if (remember) window.history.pushState(null, '', hrefMain(filter))
  if (reload) void tree.reset({ sites: [...filter.sites], dates: [...filter.dates], q: filter.q }, scopeChain(scopeOf(filter)))
  await runSearch(filter)
}

/** The form state with the applied folder scope kept. */
function formFilter(offset = 0): Filter {
  const filter: Filter = { ...withScope({ ...applied.value, sites: [...tickedSites.value], dates: [...tickedDates.value], q: typed.value.trim() }, scopeOf(applied.value)), offset }
  return filter
}

async function start(): Promise<void> {
  const initial = parseFilter(props.route.query)
  tickedSites.value = [...initial.sites]
  tickedDates.value = [...initial.dates]
  typed.value = initial.q
  if (!(await refreshOptions())) return
  let filter = initial
  if (!hasFilter(props.route.query) && dates.value.length > 0) {
    tickedDates.value = [dates.value[0]]
    filter = { ...initial, dates: [dates.value[0]] }
  }
  await applyFilter(filter, false, true)
}
void start()
// After a key was typed following a 401 the page loads again, as every page of the SPA does.
watch(() => auth.epoch, () => void start())

async function toggleSite(id: string): Promise<void> {
  tickedSites.value = tickedSites.value.includes(id) ? tickedSites.value.filter((item) => item !== id) : [...tickedSites.value, id]
  if (!(await refreshOptions())) return
  const kept = tickedDates.value.filter((day) => dates.value.includes(day))
  dropped.value = kept.length !== tickedDates.value.length
  tickedDates.value = kept
}
function toggleDate(day: string): void {
  dropped.value = false
  tickedDates.value = tickedDates.value.includes(day) ? tickedDates.value.filter((item) => item !== day) : [...tickedDates.value, day]
}

function cancelSuggest(): void {
  if (timer !== null) clearTimeout(timer)
  timer = null
  if (pending !== null) pending.abort()
  pending = null
}
function closeList(): void {
  cancelSuggest()
  suggestions.value = []
  active.value = -1
}

/** Ask for suggestions of the CURRENT form state inside the selected folder; only the latest request may render. */
async function ask(text: string): Promise<void> {
  timer = null
  lastAsked = text
  const mine = new AbortController()
  pending = mine
  try {
    const data = await invoke(
      'backup_suggest_names',
      {
        text,
        site_ids: tickedSites.value.length ? [...tickedSites.value] : undefined,
        dates: tickedDates.value.length ? [...tickedDates.value] : undefined,
        limit: SUGGEST_LIMIT,
        ...scopeValues(applied.value),
      },
      mine.signal,
    )
    if (!alive || pending !== mine) return
    const items = isRecord(data) && Array.isArray(data.items) ? data.items : []
    suggestions.value = items.map((item) => (isRecord(item) ? String(item.name ?? '') : '')).filter((name) => name !== '')
    active.value = -1
  } catch (exc) {
    if (!alive || pending !== mine) return
    closeList()
    fail(exc)
  } finally {
    if (pending === mine) pending = null
  }
}

function onInput(event: Event): void {
  typed.value = (event.target as HTMLInputElement).value
  cancelSuggest()
  const text = typed.value.trim()
  if (!suggestible(text) || text === lastAsked) {
    suggestions.value = []
    active.value = -1
    return
  }
  timer = setTimeout(() => void ask(text), SUGGEST_DELAY_MS)
}

function pick(name: string): void {
  typed.value = escapeName(name)
  lastAsked = ''
  closeList()
  void applyFilter(formFilter(), true, true)
}

function onKey(event: KeyboardEvent): void {
  const count = suggestions.value.length
  if (event.key === 'ArrowDown' && count > 0) {
    event.preventDefault()
    active.value = Math.min(active.value + 1, count - 1)
  } else if (event.key === 'ArrowUp' && count > 0) {
    event.preventDefault()
    active.value = Math.max(active.value - 1, 0)
  } else if (event.key === 'Enter') {
    event.preventDefault()
    if (active.value >= 0 && active.value < count) pick(suggestions.value[active.value])
    else {
      closeList()
      void applyFilter(formFilter(), true, true)
    }
  } else if (event.key === 'Escape' || event.key === 'Tab') {
    closeList()
  }
}

function apply(): void {
  closeList()
  void applyFilter(formFilter(), true, true)
}

async function reset(): Promise<void> {
  closeList()
  const hadSites = tickedSites.value.length > 0
  tickedSites.value = []
  tickedDates.value = []
  typed.value = ''
  lastAsked = ''
  dropped.value = false
  if (hadSites) await refreshOptions()
}

function go(offset: number): void {
  void applyFilter({ ...applied.value, offset })
}

/** A node of the tree, a crumb or the root of the tree: the scope changes, the filters stay, the search runs once and the tree is not asked again. */
function select(next: Scope): void {
  closeList()
  void applyFilter(withScope(applied.value, next))
}

/** The recursive switch of the folder list: the files of the whole subtree instead of the folder itself. */
function setRecursive(event: Event): void {
  const filter: Filter = { ...applied.value, offset: 0 }
  if ((event.target as HTMLInputElement).checked) filter.rec = true
  else delete filter.rec
  void applyFilter(filter)
}

/** Download of a row through the export flow: the row's properties go to the side panel, exactly one backup_prepare_download, then the export card in it. */
async function download(item: Record<string, unknown>): Promise<void> {
  if (busy.value) return
  busy.value = true
  selected.value = item
  try {
    const out = await invoke('backup_prepare_download', { snapshot_id: String(item.snapshot_id), file_path: String(item.file_path) })
    const id = isRecord(out) ? out.export_id : undefined
    if (typeof id === 'string' && id !== '') exportId.value = id
    else banner.value = { code: 'BAD_RESPONSE', message: 'the service answered without an export id' }
  } catch (exc) {
    fail(exc)
  } finally {
    busy.value = false
  }
}

const rows = computed<Record<string, unknown>[]>(() => (result.value !== null && Array.isArray(result.value.items) ? result.value.items.filter(isRecord) : []))
const total = computed(() => (result.value !== null && typeof result.value.total === 'number' ? result.value.total : 0))
const notIndexed = computed(() => {
  const index = result.value !== null ? result.value.index : null
  if (!isRecord(index) || index.complete !== false) return 0
  return Number(index.snapshots_total ?? 0) - Number(index.snapshots_indexed ?? 0)
})
const where = (item: Record<string, unknown>): string => [item.library_name, item.dir].filter((part) => typeof part === 'string' && part !== '').join(' / ')

/** The three regions fill the window below the filters (each scrolls by itself, the document does not); below 900 px they stack and the page scrolls. */
function fit(): void {
  const el = grid.value
  if (el === null || window.innerWidth < 900) {
    gridHeight.value = ''
    return
  }
  const top = el.getBoundingClientRect().top + window.scrollY
  gridHeight.value = `${Math.max(320, Math.floor(window.innerHeight - top - 24))}px`
}
onMounted(() => {
  fit()
  window.addEventListener('resize', fit)
})
onUpdated(fit)

onBeforeUnmount(() => {
  alive = false
  cancelSuggest()
  window.removeEventListener('resize', fit)
})
</script>

<template>
  <section data-testid="page-main">
    <form data-testid="filter-panel" class="filter-panel" @submit.prevent="apply">
      <fieldset data-testid="filter-sites">
        <legend>Сайты</legend>
        <label v-for="site in sites" :key="site.site_id">
          <input type="checkbox" data-testid="site-check" data-field="site_name" :data-raw="site.site_id" :checked="tickedSites.includes(site.site_id)" @change="toggleSite(site.site_id)" />
          {{ site.name }}
        </label>
      </fieldset>
      <fieldset data-testid="filter-dates">
        <legend>Даты бэкапа</legend>
        <label v-for="day in dates" :key="day">
          <input type="checkbox" data-testid="date-check" :data-raw="day" :checked="tickedDates.includes(day)" @change="toggleDate(day)" />
          {{ day }}
        </label>
        <p v-if="dropped" data-testid="filter-date-dropped">Дата снята: у выбранных сайтов нет бэкапа в эту дату.</p>
      </fieldset>
      <div class="name-field">
        <label>
          Часть имени файла
          <input
            data-testid="name-input"
            type="text"
            maxlength="128"
            autocomplete="off"
            role="combobox"
            aria-autocomplete="list"
            aria-controls="name-suggest"
            :aria-expanded="suggestions.length > 0"
            :aria-activedescendant="active >= 0 ? 'name-suggest-item-' + active : undefined"
            :value="typed"
            @input="onInput"
            @keydown="onKey"
            @blur="closeList"
          />
        </label>
        <ul v-if="suggestions.length > 0" id="name-suggest" data-testid="name-suggest" role="listbox" class="suggest">
          <li
            v-for="(name, index) in suggestions"
            :id="'name-suggest-item-' + index"
            :key="name"
            data-testid="name-suggest-item"
            role="option"
            :data-raw="name"
            :aria-selected="index === active"
            @mousedown.prevent
            @click="pick(name)"
          >
            {{ name }}
          </li>
        </ul>
      </div>
      <button type="submit" data-testid="filter-apply">Применить</button>
      <button type="button" data-testid="filter-reset" @click="reset">Сбросить</button>
    </form>

    <div ref="grid" data-testid="main-grid" class="main-grid" :style="gridHeight !== '' ? { height: gridHeight } : undefined">
      <FolderTree :tree="tree" :scope="scope" @select="select" />

      <section data-testid="result-area" class="result-area">
        <ErrorBanner :banner="banner" />
        <div data-testid="folder-path" class="folder-path">
          <button type="button" data-testid="crumb-all" class="crumb" @click="select({})">Все файлы</button>
          <template v-for="(crumb, index) in crumbs" :key="index">
            <span class="crumb-sep" aria-hidden="true">/</span>
            <button type="button" data-testid="crumb" class="crumb" :aria-current="index === crumbs.length - 1 ? 'true' : undefined" @click="select(crumb.scope)">{{ crumb.label }}</button>
          </template>
          <label class="rec-switch">
            <input type="checkbox" data-testid="folder-recursive" :checked="applied.rec === true" :disabled="!applied.fd" @change="setRecursive" />
            С вложенными
          </label>
        </div>
        <p data-testid="result-count" data-field="total" :data-raw="String(total)">{{ total }}</p>
        <p v-if="notIndexed > 0" data-testid="result-index-note">индекс ещё строится: {{ notIndexed }} снимков не учтено</p>
        <p v-if="result !== null && total === 0" data-testid="result-empty">Ничего не найдено</p>
        <ResultPager :offset="applied.offset" :total="total" :count="rows.length" @go="go" />
        <div data-testid="result-scroll" class="result-scroll">
          <table data-testid="result-table">
            <thead>
              <tr>
                <th data-testid="col-site">Имя сайта</th>
                <th data-testid="col-name">Имя файла</th>
                <th data-testid="col-date">Дата</th>
              </tr>
            </thead>
            <tbody>
              <tr
                v-for="(item, index) in rows"
                :key="index"
                data-testid="result-row"
                :class="{ picked: selected === item }"
                :data-snapshot-id="String(item.snapshot_id)"
                :data-path="String(item.file_path)"
                :data-library="String(item.library_name)"
                :data-size="String(item.size)"
                :data-copy-index="String(item.copy_index)"
              >
                <td data-field="site_name" :data-raw="String(item.site_name)">{{ item.site_name }}</td>
                <td data-field="name" :data-raw="String(item.name)">
                  <span data-testid="result-where" :title="where(item)" :data-raw="where(item)">
                    <button type="button" data-testid="result-download" :disabled="busy" @click="download(item)">{{ item.name }}</button>
                  </span>
                  <span v-if="Number(item.copy_index) > 0" data-testid="result-copy-mark" data-field="copy_index" :data-raw="String(item.copy_index)">{{ copyMarker(Number(item.copy_index)) }}</span>
                </td>
                <td data-field="snapshot_time" :data-raw="String(item.snapshot_time)">{{ formatSnapshot(String(item.snapshot_time), zone) }}</td>
              </tr>
            </tbody>
          </table>
        </div>
      </section>

      <aside data-testid="detail-panel" class="detail-panel" :class="{ empty: selected === null }">
        <template v-if="selected !== null">
          <h2>Свойства файла</h2>
          <dl data-testid="detail-props">
            <dt>Имя файла</dt>
            <dd data-testid="detail-name">{{ selected.name }} <span v-if="Number(selected.copy_index) > 0" data-testid="detail-copy-mark">{{ copyMarker(Number(selected.copy_index)) }}</span></dd>
            <dt>Сайт</dt>
            <dd data-testid="detail-site">{{ selected.site_name }}</dd>
            <dt>Библиотека / папка</dt>
            <dd data-testid="detail-where">{{ where(selected) }}</dd>
            <dt>Размер</dt>
            <dd data-testid="detail-size">{{ formatBytes(String(selected.size)) }}</dd>
            <dt>Дата и время бэкапа</dt>
            <dd data-testid="detail-time">{{ formatSnapshot(String(selected.snapshot_time), zone) }}</dd>
          </dl>
        </template>
        <p v-else data-testid="detail-hint">Нажмите на имя файла в списке: здесь появятся его свойства и кнопки скачивания.</p>
        <div v-if="exportId !== ''" data-testid="export-panel">
          <ExportPage :key="exportId" :export-id="exportId" @gone="exportId = ''" />
        </div>
      </aside>
    </div>
  </section>
</template>

<style scoped>
.name-field {
  position: relative;
}
.suggest {
  position: absolute;
  z-index: 10;
  margin: 0;
  padding: 0;
  list-style: none;
  background: #fff;
  border: 1px solid #888;
  max-height: 20em;
  overflow-y: auto;
}
.suggest li {
  padding: 0.25em 0.75em;
  cursor: pointer;
}
.suggest li[aria-selected='true'] {
  background: #cde;
}
.main-grid {
  display: grid;
  grid-template-columns: 300px minmax(0, 1fr) 340px;
  grid-template-rows: minmax(0, 1fr);
  gap: 1rem;
  align-items: stretch;
}
.result-area {
  display: flex;
  flex-direction: column;
  min-width: 0;
  min-height: 0;
}
.result-area p {
  margin: 0.25rem 0;
}
.folder-path {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 0.35rem;
  margin: 0.25rem 0;
}
.crumb {
  border: 0;
  background: none;
  padding: 0.1rem 0.25rem;
  font: inherit;
  color: #0969da;
  cursor: pointer;
}
.crumb[aria-current='true'] {
  color: #1f2328;
  font-weight: 600;
}
.rec-switch {
  margin-left: auto;
}
.result-scroll {
  flex: 1 1 auto;
  min-height: 0;
  overflow-y: auto;
}
.result-area table {
  width: 100%;
  margin-top: 0;
}
.result-area tr.picked td {
  background: #ddf4ff;
}
.detail-panel {
  min-height: 0;
  overflow-y: auto;
  box-sizing: border-box;
  padding: 0.5rem 0.75rem;
  background: #fff;
  border: 1px solid #d0d7de;
}
.detail-panel h2 {
  margin: 0 0 0.5rem;
  font-size: 1.1rem;
}
.detail-panel dl {
  margin: 0 0 0.5rem;
}
.detail-panel dt {
  font-size: 0.8rem;
  color: #57606a;
}
.detail-panel dd {
  margin: 0 0 0.35rem;
  overflow-wrap: anywhere;
}
@media (max-width: 899px) {
  .main-grid {
    grid-template-columns: minmax(0, 1fr);
    grid-template-rows: auto;
  }
  .result-scroll {
    max-height: 60vh;
  }
  .detail-panel {
    max-height: 50vh;
  }
}
</style>
