// One typed table of the adapter commands the SPA calls: command -> { parameter -> { type, required } }.
// It feeds the API client (buildParams) and the build step that writes dist/command-manifest.json.

// The live help of the service spells a nullable string parameter (file_path) exactly as the text below (matrix 10.18.7 (3)).
export const NULLABLE_STRING = "['string', 'null']"
export type ParamType = 'string' | 'integer' | 'boolean' | 'number' | 'object' | 'array' | typeof NULLABLE_STRING
export interface ParamSpec {
  type: ParamType
  required: boolean
}

const str = (required: boolean): ParamSpec => ({ type: 'string', required })
const int = (required: boolean): ParamSpec => ({ type: 'integer', required })
const bool = (required: boolean): ParamSpec => ({ type: 'boolean', required })
const list = (required: boolean): ParamSpec => ({ type: 'array', required })

export const COMMANDS: Record<string, Record<string, ParamSpec>> = {
  backup_snapshots: { limit: int(false) },
  backup_list_files: { snapshot_id: str(true), prefix: str(false), offset: int(false), limit: int(false) },
  backup_prepare_download: { snapshot_id: str(true), file_path: { type: NULLABLE_STRING, required: false } },
  backup_download_status: { export_id: str(true) },
  backup_delete_export: { export_id: str(true) },
  backup_sites_list: { limit: int(false), offset: int(false), query: str(false) },
  backup_libraries_list: { site_id: str(true), limit: int(false), offset: int(false) },
  backup_discovery_status: {},
  backup_filter_options: { site_ids: list(false) },
  backup_search_files: { site_ids: list(false), dates: list(false), name_part: str(false), limit: int(false), offset: int(false) },
  backup_suggest_names: { text: str(true), site_ids: list(false), dates: list(false), limit: int(false) },
  backup_schedule_get: { next_count: int(false) },
  backup_schedule_set: { text: str(true), expected_revision: str(false), dry_run: bool(false), next_count: int(false), actor: str(false) },
  backup_schedule_status: { history_limit: int(false) },
  help: { cmdname: str(false) },
  info: { page: int(false) },
}

// Commands the SPA deliberately does not call: the download goes through the temporary link, not the adapter transfer path.
export const NOT_USED: string[] = ['backup_download_begin']

/** Build the parameter object of one command: an unset (undefined or null) optional is omitted, never sent as null. */
export function buildParams(command: string, values: Record<string, unknown>): Record<string, unknown> {
  const spec = COMMANDS[command]
  if (!spec) throw new Error(`command ${command} is not in the command table`)
  const out: Record<string, unknown> = {}
  for (const [name, value] of Object.entries(values)) {
    if (!(name in spec)) throw new Error(`parameter ${name} is not accepted by ${command}`)
    if (value === undefined || value === null) continue
    out[name] = value
  }
  for (const [name, item] of Object.entries(spec)) {
    if (item.required && !(name in out)) throw new Error(`parameter ${name} is required by ${command}`)
  }
  return out
}
