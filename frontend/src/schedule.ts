// Pure helpers of the schedule section of the service page (matrix 10.20.7): problems, state labels, time text and request values.

import { formatSnapshot, isRecord } from './lib'

export interface Problem {
  line: number | null
  column: number | null
  code: string
  severity: string
  message: string
}

export const DEFAULT_TEXT = [
  '# OneDrive backup schedule (edit through the API, the client, odbcli or the UI).',
  '# Fields: minute hour day-of-month month day-of-week. Lines starting with # are comments.',
  'TZ=Europe/Kyiv',
  'JITTER=15m',
  'CATCHUP=24h',
  '30 2 * * *',
  '',
].join('\n')

export const STATE_LABELS: Record<string, string> = {
  starting: 'Запускается',
  waiting: 'Ожидает следующего запуска',
  running: 'Идёт резервное копирование',
  paused: 'Приостановлено (ENABLED=no)',
  idle: 'Нет записей: резервное копирование не запустится',
  file_invalid: 'Файл содержит ошибки, действует прежнее расписание',
  storage_unavailable: 'Хранилище недоступно',
  scaffold: 'Режим заглушки',
  not_leader: 'Планировщик ведёт другой процесс',
  stopped: 'Планировщик остановлен',
}

export const stateLabel = (state: string): string => STATE_LABELS[state] ?? state

/** The problems of an answer or an error: errors first, then warnings, each group in line order. */
export function orderProblems(value: unknown): Problem[] {
  if (!Array.isArray(value)) return []
  const items: Problem[] = value.filter(isRecord).map((item) => ({
    line: typeof item.line === 'number' ? item.line : null,
    column: typeof item.column === 'number' ? item.column : null,
    code: String(item.code ?? ''),
    severity: String(item.severity ?? 'error'),
    message: String(item.message ?? ''),
  }))
  const rank = (item: Problem): number => (item.severity === 'error' ? 0 : 1)
  return items
    .map((item, index) => ({ item, index }))
    .sort((a, b) => rank(a.item) - rank(b.item) || (a.item.line ?? 0) - (b.item.line ?? 0) || a.index - b.index)
    .map((entry) => entry.item)
}

export const hasError = (items: Problem[]): boolean => items.some((item) => item.severity === 'error')
export const problemText = (item: Problem): string => `${item.line ?? '-'}:${item.column ?? '-'} ${item.code} ${item.message}`

/** The caret offset of the start of a one-based line of the text. */
export function lineOffset(text: string, line: number): number {
  return text.split('\n').slice(0, Math.max(0, line - 1)).reduce((sum, part) => sum + part.length + 1, 0)
}

/** The instant as YYYY-MM-DD HH:MM in the zone the answer names, followed by the zone. */
export const localTime = (iso: string, zone: string): string => `${formatSnapshot(iso, zone)} (${zone})`

/** The exact parameters of a check (a dry run) and of a save; an omitted option is absent. */
export const checkValues = (text: string): Record<string, unknown> => ({ text, dry_run: true, actor: 'spa' })
export const saveValues = (text: string, revision: string): Record<string, unknown> => ({ text, expected_revision: revision, actor: 'spa' })

export const isDirty = (draft: string, loaded: string): boolean => draft !== loaded

/** Save is allowed for a changed text whose last check had no error. */
export const canSave = (draft: string, loaded: string, checked: string | null, problems: Problem[]): boolean =>
  draft !== loaded && checked === draft && !hasError(problems)

/** A conflict answer: the revision and the text the server holds now, or null for any other answer. */
export function conflictOf(code: unknown, data: unknown): { revision: string; text: string } | null {
  if (code !== 409 || !isRecord(data) || typeof data.current_revision !== 'string') return null
  return { revision: data.current_revision, text: typeof data.current_text === 'string' ? data.current_text : '' }
}

/** The status names another revision than the editor holds, other than the one that was current before the own save. */
export function changedElsewhere(statusRevision: string, loadedRevision: string | null, ignored: string | null): boolean {
  return loadedRevision !== null && statusRevision !== '' && statusRevision !== loadedRevision && statusRevision !== ignored
}
