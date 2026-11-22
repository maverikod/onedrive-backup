<script setup lang="ts">
// svc-schedule (matrix 10.20.7): view and edit the backup schedule. Entering sends one backup_schedule_get and one
// backup_schedule_status; only the status is polled (every 15 s while the section is visible); the text is never re-read by the poll.
import { computed, ref, watch } from 'vue'
import { useCommand, type Banner } from '../command'
import ErrorBanner from '../components/ErrorBanner.vue'
import { POLL_SCHEDULE_MS, isRecord } from '../lib'
import { RpcError, invoke } from '../rpc'
import {
  DEFAULT_TEXT, canSave, changedElsewhere, checkValues, conflictOf, isDirty, lineOffset, localTime, orderProblems, problemText, saveValues,
  stateLabel, type Problem,
} from '../schedule'

const stored = useCommand(() => invoke('backup_schedule_get', {}))
const status = useCommand(() => invoke('backup_schedule_status', {}), { intervalMs: POLL_SCHEDULE_MS, keepGoing: () => true })

const area = ref<HTMLTextAreaElement | null>(null)
const draft = ref('')
const loaded = ref<{ text: string; revision: string } | null>(null)
const plans = ref<Record<string, unknown>[]>([])
const zone = ref('Europe/Kyiv')
const problems = ref<Problem[]>([])
const checked = ref<string | null>(null)
const saved = ref<string | null>(null)
const conflict = ref<{ revision: string; text: string } | null>(null)
const failure = ref<Banner | null>(null)
const ignored = ref<string | null>(null)

function takePlans(data: Record<string, unknown>): void {
  plans.value = Array.isArray(data.next_runs) ? data.next_runs.filter(isRecord) : []
  if (typeof data.timezone === 'string') zone.value = data.timezone
}

function adopt(data: unknown): void {
  if (!isRecord(data) || typeof data.text !== 'string' || typeof data.revision !== 'string') return
  loaded.value = { text: data.text, revision: data.revision }
  draft.value = data.text
  checked.value = null
  conflict.value = null
  problems.value = orderProblems(data.problems)
  takePlans(data)
}
watch(
  () => stored.data.value,
  (data) => {
    if (loaded.value === null) adopt(data)
  },
  { immediate: true },
)

const dirty = computed(() => loaded.value !== null && isDirty(draft.value, loaded.value.text))
const savable = computed(() => loaded.value !== null && canSave(draft.value, loaded.value.text, checked.value, problems.value))
const thread = computed<Record<string, unknown>>(() => (isRecord(status.data.value) && isRecord(status.data.value.scheduler) ? status.data.value.scheduler : {}))
const statusRevision = computed(() => (isRecord(status.data.value) && isRecord(status.data.value.schedule) ? String(status.data.value.schedule.revision ?? '') : ''))
const elsewhere = computed(() => changedElsewhere(statusRevision.value, loaded.value?.revision ?? null, ignored.value))
const current = computed(() => (isRecord(status.data.value) && isRecord(status.data.value.current_run) ? status.data.value.current_run : null))
const last = computed(() => (isRecord(status.data.value) && isRecord(status.data.value.last_run) ? status.data.value.last_run : null))
const missed = computed(() => (isRecord(status.data.value) && isRecord(status.data.value.missed) && status.data.value.missed.pending === true ? status.data.value.missed : null))
const history = computed<Record<string, unknown>[]>(() => (isRecord(status.data.value) && Array.isArray(status.data.value.history) ? status.data.value.history.filter(isRecord) : []))

async function send(values: Record<string, unknown>, save: boolean): Promise<void> {
  failure.value = null
  conflict.value = null
  saved.value = null
  try {
    const result = await invoke('backup_schedule_set', values)
    if (!isRecord(result)) return
    problems.value = orderProblems(result.problems)
    takePlans(result)
    if (save) {
      ignored.value = statusRevision.value
      loaded.value = { text: String(result.text), revision: String(result.revision) }
      draft.value = String(result.text)
      saved.value = String(result.revision)
      checked.value = null
    } else {
      checked.value = String(values.text)
    }
  } catch (exc) {
    if (!(exc instanceof RpcError)) throw exc
    checked.value = null
    const found = conflictOf(exc.code, exc.data)
    if (found !== null) conflict.value = found
    else if (isRecord(exc.data) && Array.isArray(exc.data.problems)) problems.value = orderProblems(exc.data.problems)
    else failure.value = { code: exc.code, message: exc.message }
  }
}

function check(): void {
  void send(checkValues(draft.value), false)
}
function save(): void {
  if (loaded.value !== null) void send(saveValues(draft.value, loaded.value.revision), true)
}
function reset(): void {
  if (loaded.value !== null) draft.value = loaded.value.text
  checked.value = null
  problems.value = []
}
function insertDefault(): void {
  draft.value = DEFAULT_TEXT
  checked.value = null
}
function reload(): void {
  loaded.value = null
  ignored.value = null
  stored.reload()
}
function takeServerText(): void {
  if (conflict.value === null) return
  if (!window.confirm('Правки в редакторе будут потеряны. Загрузить текст с сервера?')) return
  reload()
}
function goto(item: Problem): void {
  const field = area.value
  if (field === null || item.line === null) return
  const at = lineOffset(draft.value, item.line)
  field.focus()
  field.setSelectionRange(at, at)
}
const text = (item: Record<string, unknown>, name: string): string => String(item[name] ?? '')
</script>

<template>
  <section data-testid="svc-schedule">
    <h1>Расписание резервного копирования</h1>
    <ErrorBanner :banner="stored.banner.value ?? status.banner.value ?? failure" />
    <p v-if="elsewhere" data-testid="schedule-changed-elsewhere">
      Расписание изменено в другом месте.
      <button type="button" data-testid="schedule-reload" @click="reload">Загрузить заново</button>
    </p>
    <p>
      Состояние: <span data-testid="schedule-state" :data-raw="text(thread, 'state')">{{ stateLabel(text(thread, 'state')) }}</span>;
      поток: <span data-testid="schedule-thread" :data-raw="text(thread, 'thread_alive') || 'false'">{{ thread.thread_alive === true ? 'работает' : 'не работает' }}</span>
    </p>
    <p v-if="current" data-testid="schedule-current-run" :data-raw="text(current, 'run_id')" :data-trigger="text(current, 'trigger')">
      Идёт бэкап ({{ text(current, 'trigger') }}), {{ text(current, 'elapsed_seconds') }} с
    </p>
    <p v-if="last" data-testid="schedule-last-run" :data-raw="text(last, 'status')" :data-exit-code="text(last, 'exit_code')">
      Последний запуск: {{ text(last, 'status') }}, {{ text(last, 'finished_at') }}
    </p>
    <p v-if="missed" data-testid="schedule-missed">Пропущенный слот {{ text(missed, 'slot_utc') }} будет выполнен после {{ text(missed, 'will_start_after_utc') }}</p>
    <h2>Ближайшие запуски</h2>
    <ul data-testid="schedule-next-runs">
      <li v-for="item in plans" :key="text(item, 'start_utc')" data-testid="schedule-next-run" :data-raw="text(item, 'start_utc')" :data-slot="text(item, 'slot_utc')">
        {{ localTime(text(item, 'start_utc'), zone) }}
      </li>
    </ul>
    <p v-if="conflict" data-testid="schedule-conflict">
      Расписание изменили пока вы редактировали; ваш текст сохранён в редакторе.
      <button type="button" data-testid="schedule-conflict-reload" @click="takeServerText">Загрузить текст с сервера</button>
    </p>
    <textarea
      ref="area"
      v-model="draft"
      data-testid="schedule-text"
      :data-raw="loaded?.revision ?? ''"
      class="mono"
      rows="16"
      cols="90"
      spellcheck="false"
    ></textarea>
    <span v-if="dirty" data-testid="schedule-dirty" hidden></span>
    <p>
      <button type="button" data-testid="schedule-check" @click="check">Проверить</button>
      <button type="button" data-testid="schedule-save" :disabled="!savable" @click="save">Сохранить</button>
      <button type="button" data-testid="schedule-reset" @click="reset">Отменить правки</button>
      <button type="button" data-testid="schedule-default" @click="insertDefault">Вставить расписание по умолчанию</button>
    </p>
    <p v-if="saved" data-testid="schedule-saved" :data-raw="saved">Расписание сохранено.</p>
    <ul v-if="problems.length" data-testid="schedule-problems">
      <li
        v-for="(item, index) in problems"
        :key="index"
        data-testid="schedule-problem"
        :data-line="item.line ?? ''"
        :data-column="item.column ?? ''"
        :data-code="item.code"
        :data-severity="item.severity"
      >
        {{ problemText(item) }}
        <button type="button" data-testid="schedule-problem-goto" @click="goto(item)">к строке</button>
      </li>
    </ul>
    <div data-testid="schedule-help">
      <p>Запись — пять полей: минута час день-месяца месяц день-недели. Строки с # — комментарии.</p>
      <p>Директивы: TZ=&lt;зона&gt;, JITTER=&lt;n&gt;m, CATCHUP=&lt;n&gt;h, ENABLED=yes|no.</p>
      <pre>{{ DEFAULT_TEXT }}</pre>
    </div>
    <h2>История запусков</h2>
    <ul data-testid="schedule-history">
      <li v-for="item in history" :key="text(item, 'run_id')" data-testid="schedule-history-row">
        <span data-field="started_at" :data-raw="text(item, 'started_at')">{{ text(item, 'started_at') }}</span>
        <span data-field="status" :data-raw="text(item, 'status')">{{ text(item, 'status') }}</span>
        <span data-field="trigger" :data-raw="text(item, 'trigger')">{{ text(item, 'trigger') }}</span>
        <span data-field="exit_code" :data-raw="text(item, 'exit_code')">{{ text(item, 'exit_code') }}</span>
      </li>
    </ul>
  </section>
</template>
