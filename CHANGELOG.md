## 0.3.25 — toolbar of service sections and page toolbar of the result list (UI correction of matrix revision 11, user request 2026-11-23)

- Web UI only, no command, parameter or result change. The six links of the service page `#/service` are one toolbar (`svc-toolbar`): button-like boxes in one row, each at least 24 px high with its own border and background and a gap between them; the open section keeps `aria-current=page` and is drawn differently (filled, bold). The result list of the main page `#/` has a page toolbar `result-pager` above the table: `page-first`, `page-prev`, `page-info` ("page N of M"), `page-next`, `page-last`; first and previous are disabled on the first page, next and last on the last one, and one click sends one `backup_search_files` with the new offset and the same limit of 100. The new component is `frontend/src/components/ResultPager.vue`; the test ids `page-prev` and `page-next` are unchanged, `svc-toolbar`, `result-pager`, `page-first`, `page-last` and `page-info` are new.

## 0.3.24 — properties and download side panel on the main page (UI correction of matrix revision 11, user request 2026-11-22)

- Web UI only, no command, parameter or result change: the main page `#/` is two columns, the result list on the left and the side panel `detail-panel` on the right. A click on a file name shows its properties (file name with the copy marker, site, library / folder, size, backup date and time) and the export card with the download link and the delete button in that panel, so a long list no longer hides them below the table. The panel stays in the viewport (sticky, own scroll); below a window width of 900 px it stacks under the list. All earlier test ids are unchanged; `detail-panel` is new.

## 0.3.23 — backup schedule file, scheduler thread and schedule section (matrix revision 12, section 10.20)

- New commands `backup_schedule_get`, `backup_schedule_set` and `backup_schedule_status` (matrix rows M15-M17) read and write the cron-style schedule file `<data>/schedule/schedule.cron` and show the scheduler state; Python client methods `schedule_get`, `schedule_set`, `schedule_status` and the odbcli subcommands `schedule-get`, `schedule-set`, `schedule-status` use the same commands.
- The schedule file (default: daily 02:30 Europe/Kyiv, JITTER=15m, CATCHUP=24h) has five cron fields per entry and the directives TZ, JITTER, CATCHUP and ENABLED; a write is atomic, keeps the 50 newest previous versions in `history/` and appends who changed what to `changes.jsonl`; a missing file is recreated with the default, a corrupt one falls back to the held schedule, a history version or the default.
- A scheduler thread inside the API container (leader lock `schedule/scheduler.lock`) decides every 30 seconds with the pure function `decide()` and starts `python -m onedrive_api.backup_run` as a child process; the existing backup lock, the fail-closed guards, duplicate keeping and the post-backup indexing stay in force. A missed slot is run once after a start (catch-up window 24 hours, replaces `Persistent=true`), a slot is skipped while a backup still runs, DST gaps and repeated hours fire once.
- `backup_run` writes a start and an end record for every start to `<data>/schedule/runs.jsonl`.
- Служебные: a sixth section "Расписание" shows and edits the schedule, checks it with a dry run, shows the next runs and the scheduler state (ids svc-tab-schedule and schedule-*).
- Packaging: the package no longer ships `onedrive-backup.timer` and `onedrive-backup.service`; the preinst captures and the postinst retires the old timer, creates the schedule file only when absent (ENABLED=yes only when the timer was enabled or active; a fresh install creates ENABLED=no) and records the old timer settings in `/var/lib/onedrive-backup/timer-migration.txt` (`NOT MIGRATED` when they were not the default 02:30). `docker/deploy.sh` refuses while a backup runs.
- Rollback: install the previous .deb and run `systemctl enable --now onedrive-backup.timer`; `/data/schedule` stays on the disk.
## 0.3.22 — single filter page, file name index and three search commands (matrix revision 11, section 10.19)

- New commands `backup_filter_options` (sites that have indexed snapshots and the backup dates of the ticked sites), `backup_search_files` (files of the ticked sites and dates by name part, 100 rows per page, all versions, ordered by name key then snapshot time newest first) and `backup_suggest_names` (distinct names for the autocomplete, at least two characters besides stars). A backup date is the calendar day of the snapshot time in the zone of `ONEDRIVE_UI_TIMEZONE` (default Europe/Kyiv). The name part is a contains match; with an unescaped `*` it is a full-name pattern, `\*` is a literal star, case and Unicode normalisation are ignored. A stored duplicate copy of rev 10 is returned with the original name, `is_copy` and `copy_index`. Errors: 400 INVALID_SITE_ID, INVALID_DATE, INVALID_NAME_PART; 503 SCAFFOLD_ONLY, SOURCE_NOT_READY.
- Persistent name index (SQLite, `<data>/file-index/index.sqlite3`, created by the service, derived from `restic ls`, rebuildable at any time): every snapshot is indexed once; the service indexes the missing snapshots in a background thread at start (the commands answer with `index.complete` false meanwhile) and the backup run indexes the snapshots it made after the backup (`onedrive_api.backup_run`); an indexing failure is one ERROR log line and never changes the exit status of the backup.
- Python client: `filter_options`, `search_files`, `suggest_names`. odbcli: `filter-options`, `search-files`, `suggest-names`.
- Web UI: one filter page `#/` (site and date checkboxes, name field with autocomplete and `*` wildcard, result table with the columns site name, file name, date, download of a row in an inline export panel) and one service page `#/service` with five sections (snapshots, sites, discovery, help, info) and the drill-down routes under it; the routes of 0.3.21 are removed (page-notfound). `tzdata` joins the image requirements.

## 0.3.21 — every copy of colliding file names is kept (matrix revision 10, bug 1147348f)

- Two or more files of one library that collide on the mirror path (same folder, names equal after NFC normalisation and case folding; the observed case is an NFC and an NFD spelling of one name) are all kept. Before the sync the service scans the library read-only (`rclone lsjson -R --hash`); the sync mirrors the first object as before and now carries `--exclude '*.dup-[0-9a-f]{8}*'` so that a stored copy survives it (`--max-delete` unchanged); every further object is fetched by its Graph item id (read-only `GET /drives/{drive}/items/{item}/content`, the pre-authenticated redirect without the Authorization header, 3 attempts) into a temporary file next to the mirror and renamed to `<stem>.dup-<h><ext>` in the folder of its twin, `<h>` being the first 8 hex digits of sha256 of the item id (4 more per name clash), and lands in the same restic snapshot. The primary is the member whose size and quickXorHash (`rclone hashsum quickxor`) equal the mirrored file, the smallest item id otherwise. A stored copy that already equals the listing is not fetched again; a copy whose twin is gone stays and is counted as stale. Nothing is written to SharePoint.
- Run record: every library entry carries `duplicates` (one object per extra: `path`, `name`, `item_id`, `stored_as`, `size`, `quickxor`, `integrity` ok, hash_unavailable, mismatch, fetch_failed or not_fetched, `error`) and `duplicate_summary` (`groups`, `kept`, `failed`, `stale`); the new library outcome `duplicate_incomplete` (an error library: status partial or failed, exit 1) means a scan failure (`DUPLICATE_SCAN_FAILED`), a real source object named like a stored copy that is not synced (`DUPLICATE_NAME_RESERVED`), two colliding directories (`DUPLICATE_DIRECTORY_UNSUPPORTED`), a failed fetch (`DUPLICATE_FETCH_FAILED`) or a size or hash mismatch that is kept and flagged (`DUPLICATE_INTEGRITY_MISMATCH`). Kept and verified copies leave the library `ok` and are reported by one WARNING log line each. No command, parameter or response schema changes; `backup_list_files`, `backup_prepare_download` and the client download the stored copy under its suffixed name like any file.
- Project check configuration for the CAS/editor write gate: `setup.cfg` carries `[flake8]` (`max-line-length` 127, the measured longest line of `src/`, `client/` and `tests/`; `E501` ignored only for `pipeline/`, whose evidence strings reach 308 columns) and `[mypy]` (no ignore list). The gate runs flake8 and mypy with `config_source` auto, so they read this file; the docstring check is a built-in, non-blocking server tool with no project configuration. `validate_transfer` in `src/onedrive_api/server.py` is restructured so mypy sees a `dict` (same behaviour, same error message). No product behaviour changes (task 70, TODO 32fe6b13).

## 0.3.20 — Vue SPA served by the service, backup timer kept over an upgrade (matrix revision 8, group B)

- The user's web UI is a Vue 3 + Vite + TypeScript single page application under `frontend/` (`package.json`, lockfile,
  `.node-version` 22, Vitest groups auth, commands, paging, polling, download, error banner, no-demo-data, `npm test`). It talks only
  to the adapter command API (`POST /api/jsonrpc`, `X-API-Key` only after a 401 and only in page memory) and to `/downloads`.
  Hash routes: `#/snapshots`, `#/snapshots/<id>/files`, `#/exports/<export_id>`, `#/sites`, `#/sites/<site_id>/libraries`,
  `#/discovery`, `#/help`, `#/info`, `#/signed-out`; test ids and the logout and polling rules follow matrix section 10.18
  (candidate, not approved). The build is reproducible (fixed file names `assets/app.js`, `assets/app.css`, SOURCE_DATE_EPOCH) and
  emits `command-manifest.json` from the one typed command table `frontend/src/commands.ts`.
- `docker/Dockerfile` gains a `node:22` build stage (`npm ci`, `npm run build`) and copies the build to `/app/web`, which the
  existing `StaticFiles` mount serves (now with `html=True`, so `GET /` is the index page; an unknown path stays 404). No second
  image, no nginx, no new route or transport code. The SPA is at https://192.168.254.26:8443/.
- `packaging/prerm`: an upgrade no longer disables and stops `onedrive-backup.timer`; an enabled and active timer stays so, a
  disabled one stays disabled, a removal or deconfigure still disables and stops it, and a fresh install never enables it
  (TODO 70425f95).

## 0.3.19 — adapter-only server-auth HTTPS, open service, LAN port 8443 (matrix revision 8, group A: transport and auth)

- The listener is server-auth HTTPS from the mcp-proxy-adapter configuration alone (`server.protocol` https, `server.ssl`
  cert and key from the project CA; no `ca`); no client certificate is requested and plain HTTP is refused. `auth.use_token`
  is false and `proxy_trust` is gone: the service is open on the LAN. The later password mode is the adapter static key,
  switched on by configuration only (`auth.tokens` or `security.tokens` from a host secret file, header `X-API-Key`), and the
  later exposure outside the LAN switches the same configuration to mtls.
- Project-owned transport code removed from `src/onedrive_api/server.py`: `_validate_mtls_config`, `tls_server_settings`
  (forced `CERT_REQUIRED`), `api_token` / `secure_auth` (base64 token from `api-credentials`), `ProxyTrustMiddleware` and the
  `proxy_trust` configuration, `ALLOWED_ROUTES` with the route filter. Every route of the adapter is served as the adapter
  defines it (`/ws`, `/api/transfer/uploads*`, `/api/async`, `/tools/*` included, open on the LAN); the one project hook besides
  command registration, `set_public_download_resolver` and the transfer configuration is the single `StaticFiles` mount of
  the SPA directory `/app/web` (`ONEDRIVE_BACKUP_WEB`), added last and empty until the SPA is built into the image.
- The service port is published on the LAN: `docker-run.sh start` and `docker/compose.yml` map host 8443 to container 8050
  (`https://192.168.254.26:8443`); the MCP Proxy still reaches `https://onedrive-backup:8050`. `docker-run.sh start` requires
  only `server.crt` and `server.key` (the CA files stay provisioned, not required) and no longer reports `api-credentials`.
  `scripts/issue-proxy-certificate.sh` adds the SAN `IP:192.168.254.26`.
- Client and odbcli: `BackupClient(url, ca=None, cert=None, key=None, timeout=180, password=None)`; `cert` and `key` are
  all-or-none (both: mTLS, neither: HTTPS), `login` and `token` are removed, `password` is sent as `X-API-Key` when set and
  never printed. `odbcli`: only `--url` is required, `--login` and `--token` are removed, the password is `--password`,
  `ONEDRIVE_BACKUP_PASSWORD` or the `password` config key.
- `scripts/smoke-mtls.sh` is replaced by `scripts/smoke-https.sh`; `build.sh` and the documents name `python -m pipeline
  smoke_https`. The standards section of `CLAUDE.md` and `AGENTS.md` carries the revision 8 text.

## 0.3.18 — data directory on /srv/archive and a writable rclone state copy (bugs 6508698d, be82d15d)

- The data directory moves to `/srv/archive/onedrive-backup` (built-in default of `docker/deploy.sh`, `docker-run.sh`,
  `postinst`, `packaging/defaults`, compose and env examples; `packaging/config.json` uses `/srv/archive`). The filesystem
  guard of `docker-run.sh` (every action except stop, status and ports), `docker/deploy.sh` (before the password prompt
  and before the package) and `postinst` refuses, with one stderr line naming the resolved path and its filesystem, when
  `/srv/archive` is not mounted or the directory is not on it. `postinst` no longer creates the data directory.
- rclone writes its refreshed OAuth token into its configuration file, which lay on the read-only `/secrets` mount
  (`Failed to save config`). The service now uses a writable copy `/rclone-state/rclone.conf` in the new state directory
  `/var/lib/onedrive-backup/rclone-state` (`ONEDRIVE_RCLONE_STATE_DIR`, created by `postinst` 0700 `onedrive-backup`,
  mounted read-write). `docker-run.sh start` seeds the copy from the original when it is absent, empty or older, through
  a temporary file renamed onto it, and otherwise keeps it. `discover`, `init`, `check` and `backup` refuse with
  `rclone state copy unavailable` when the copy is missing. `rclone_config` of `config/backup.json` and
  `packaging/api-backup.json` is `/rclone-state/rclone.conf`; `sharepoint_discover_cli` admits paths under
  `/rclone-state`. `/secrets` stays read-only (`restic-password`, `api-credentials`, the original `rclone.conf`).

## 0.3.17 — mcp-proxy-adapter upgraded 8.11.16 -> 8.11.20

- `mcp-proxy-adapter` is pinned `==8.11.20` in `docker/requirements-server.txt` and in the `onedrive-backup-client` dependency
  (`client/pyproject.toml`); the image and the client install the same adapter. No configuration, command or result of this
  service changes. Adapter changes 8.11.16 -> 8.11.20 reviewed: the module splits are internal; `enabled_commands` empty or
  absent now allows every command (this service sets neither key); the JSON-RPC client retries only a failed connect for
  up to 15 s by default and raises `ClientRetryExhaustedError`, a `ClientError` that `BackupClient` already maps; the
  dynamic-token routes `/api/auth/*` and `TokenAuth` exist only when `auth.dynamic.enabled` is true (not set here); the
  server entrypoint now syncs the loaded config into the global config singleton.

## 0.3.16 — container rclone upgraded to the official release 1.76.0 (bug 68fc1822)

- The image no longer installs the Debian `rclone` package (v1.60.1), which has no OneDrive OAuth client credential flow
  (first released in rclone v1.69.0), so every SharePoint library listing failed with `failed to configure OneDrive:
  empty token found`. The Dockerfile now installs the official linux/amd64 release pinned by the build arguments
  `OFFICIAL_RCLONE_VERSION` (1.76.0) and `OFFICIAL_RCLONE_SHA256`, downloaded from https://downloads.rclone.org in a separate build stage
  and verified against the release's published `SHA256SUMS` and the pinned digest; any mismatch fails the build.
  The final image carries only the verified `/usr/bin/rclone` binary; user, paths and entrypoint are unchanged.
- `rclone.conf` (`client_credentials`, no token) is unchanged.

## 0.3.15 — empty SharePoint libraries no longer abort the backup run (bug 81bb226e)

- `backup_libraries` handles a library whose remote root is empty: one that was never backed up (no mirror) is skipped,
  with outcome `empty` and no error; one that has a mirror is not synced (mirror and snapshots stay untouched) and an
  error `SHAREPOINT_LIBRARY_EMPTY` is recorded with outcome `source_emptied`. The run continues with the other
  libraries. Before, the first empty library raised `SHAREPOINT_LIBRARY_EMPTY` and no later library was backed up.
- `backup_libraries` returns the run record `{status, libraries: [{site_id, drive_id, outcome, error}]}` and the
  command line exits 1 when any library recorded an error. `max_delete` and `allow_empty_source=true` behave as before.

## 0.3.14 — backup_list_files of an unknown snapshot answers an empty list

- `Catalog.files` answers the success result `{snapshot_id, items: [], total: 0, offset, limit}` for a well-formed snapshot
  id that no snapshot carries (the id echoed in lowercase); before, the 404 `Snapshot not found` of the unknown id escaped
  from the listing. `backup_prepare_download` of an unknown snapshot keeps the command error 404 `Snapshot not found`;
  no other command, parameter or result changes.

## 0.3.13 — restic cache directory in the container (bug 60eae9c7)

- The image sets `RESTIC_CACHE_DIR=/tmp/restic-cache` and `XDG_CACHE_HOME=/tmp/cache`. The container runs as the host
  service uid without a passwd entry (HOME=/), so restic tried to create `/.cache` and printed `unable to open cache:
  mkdir /.cache: permission denied` on every call; it surfaced in `backup_prepare_download` errors. The cache is created
  by the service user inside the container; the container stays non-root, no-new-privileges, with read-only config and secrets.
- `Catalog` answers command error 404 `Snapshot not found` for a snapshot id that restic ignores (restic 0.14 exits 0 with an
  empty listing and `no matching ID found`); before, `backup_prepare_download` of an unknown snapshot reached `restic restore`
  and answered 503.

## 0.3.12 — first-run restic password, server HTML UI and admin password removed

- `docker/deploy.sh` asks the restic repository password on the first run (twice and without echo when the repository
  is new, once and verified against the repository when it exists), stores it in the restic password file (mode 0600,
  owner root, handed to the service user by the package `postinst`) and initialises the repository with it; without a
  terminal and without the password file it stops with an exact message before touching the package or the container.
  `restic` is now a Debian package dependency; `ONEDRIVE_SECRET_DIR`, `ONEDRIVE_DATA_DIR` and `ONEDRIVE_DEFAULTS_FILE`
  override the host paths.
- The server-side HTML interface (`/ui*`, `ui.py`) and the admin password (`admin_password.py`,
  `onedrive-backup-admin-password`, `admin-password.hash`, `ONEDRIVE_ADMIN_HASH_FILE`) are removed; every former `/ui*`
  route answers the framework 404. Restricted scaffold mode now depends only on `rclone.conf` and `restic-password`.

## 0.3.11 — source-size refactoring, no behaviour change

- `server.py`, `command_reference.py` and `sharepoint_discovery.py` are split into cohesive modules of at most 400
  lines (`commands_base`, `commands_backup`, `commands_sharepoint`, `command_reference_*`, `sharepoint_base`,
  `sharepoint_graph`, `sharepoint_scan`, `sharepoint_inventory`); the original module paths keep their public names.
- The three identical `export_id` `get_schema` bodies are one shared implementation; commands, parameters, schemas,
  results and errors are unchanged.

## 0.3.10 — B4 client: JsonRpcClient wrapper and odbcli

- The Python client `BackupClient` is a thin wrapper over the mcp-proxy-adapter 8.11.16 `JsonRpcClient`: no own TLS or
  HTTP transport, one method per server command, `call`, `raw_call`, login and password or token authentication.
- Downloads verify size and SHA-256 and replace the output atomically: `fetch` and `download` by the adapter transfer
  service (`backup_download_begin`), `fetch_link` and `download_link` by the temporary uuid4 link.
- New console command `odbcli` (every server command with all its arguments, plus health, fetch, download, call,
  download-link, download-begin); the REST-era `onedrive-backup-client` command is removed.

## 0.3.9 — B4 MCP Proxy peer admission

- The MCP Proxy peer is admitted on its mTLS transport identity alone, with no token, on every route it reaches, whether
  or not `/secrets/api-credentials` exists: the server holds a random per-process internal token that only the proxy
  middleware presents (before, the middleware injected T, which does not exist without the secret).
- An absent, empty or malformed `/secrets/api-credentials` no longer stops the service: direct peers answer 401 and the
  proxy peer is served.
- Fail closed: with no `proxy_trust.hosts` nobody is admitted without a token; `X-Forwarded-For`, `Forwarded`,
  `X-Real-IP` and `Host` grant nothing; mTLS stays mandatory; direct peers are unchanged.
- `scripts/smoke-mtls.sh` also starts the service with the secret absent and empty and expects 401.

## 0.3.8 — B4 server: commands, download link, token gate

- REST `/api/v1/*` is removed; the served routes are the adapter framework routes, `/downloads/{file_id}/{filename}`
  and `/api/transfer/downloads*`; `/ws` and the upload routes stay closed.
- `backup_prepare_download` and `backup_download_status` return `url` (`/downloads/<export_id>/<filename>`);
  the new command `backup_download_begin` registers an adapter transfer session confined to the exports directory.
- Interim authentication: the adapter token gate is on (`auth.use_token`); the token is base64(login:password)
  of the file `/secrets/api-credentials`; `/health` and `GET /commands` stay open.
- `backup_sites_list` and `backup_libraries_list` refuse a malformed query or site_id before the scaffold gate.
- The info manual no longer names stale releases.

## 0.3.7 — B3 product fixes

- The host wrapper passes every argument to docker-run.sh unchanged; no argument still means status.
- The catalog lists OneDrive and SharePoint snapshots with a source marker.
- Export preparation validates its inputs before any side effect; expired exports are removed.
- The host backup directory is a plain directory owned by onedrive-backup (created by the package
  install); the mount point is checked inside the container and refused with STORAGE_NOT_MOUNTED.
- The container always binds the host data directory at /data; the scaffold flag follows the secrets.

## 0.3.6 — Single version source and adapter 8.11.16
- VERSION is the single source of the release version: the server reads it at runtime through
  onedrive_api.version (help, info, OpenAPI and command metadata); the Docker image carries it
  as /opt/onedrive-backup/VERSION; no version literal remains in src/.
- Image tag, Debian package, wheel names, README, compose and container.env.example, the client
  __version__ and the client package metadata all name 0.3.6.
- mcp-proxy-adapter is pinned ==8.11.16 in docker/requirements-server.txt and now also declared
  by the client package (client/pyproject.toml dependencies).
- Test fixtures derive the expected version from VERSION.
- Packaging scripts (postinst, docker-run.sh, install-runtime.sh, defaults) updated for the
  production-only deployment.

## 0.3.3 — MCP Proxy method discovery
- Restore the restricted GET /commands endpoint required for proxy registration.
- Continue filtering all privileged filesystem, admin, and transfer endpoints.
- Verify the real production container registers successfully in MCP Proxy.
- Exclude generated, root-owned client/build from syntax verification.
- Clean disposable build directories after successful release and allow Debian first-time installation without a pre-existing /etc/default file.

## 0.3.2 — Debian-owned deployment and proxy registration
- Debian postinst installs certificates using paths from /etc/default and checks TLS before deployment.
- Debian package now installs its required docker-run.sh runtime helper; build failures no longer hide deployment failures.
- Docker Hub credentials read from a root-only external file, never packaged.
- Restricted internal FastAPI scaffold can register without an admin password, OneDrive credentials, or backup disk.
- Browser login and backup operations are blocked while in scaffold mode.

## 0.3.1 — internal network and delegated CRL (2026-11-14)
- Remove CRL validation and CRL file requirements from server, client, and deployment; delegate revocation handling to MCP Proxy.
- Keep mandatory mTLS trust validation for internal FastAPI and certificate-verified proxy registration.
- Remove host port publication: API/UI reachable only on the smart-assistant Docker network.
- Update mTLS smoke test, config contract, client configuration, and operational documentation.
- Exclude Python bytecode and old-version wheels from release artifacts.

## 0.3.0
- Dual-use CN=onedrive-backup certificate signed by MCP Proxy CA, used for registration and server TLS.
- FastAPI web dashboard, admin login via independent password hash file and protected session.
- Certificate preflight and mTLS certificate import from local mtls-certs directory.
- Debian password setup CLI and browser API regression tests.

# Changelog

## 0.1.1 — 2026-11-14
- Fix Debian 12/Ubuntu system-user creation: explicit nologin shell.
- Document noexec /tmp handling in CAS test sandbox.

## 0.1.0 — 2026-11-14
- First Debian package for Ubuntu/Debian with system user, systemd service/timer and safe configuration.
- OneDrive Business OAuth via rclone, encrypted restic snapshots, integrity checks, dry-run and retention.
- Integration tests with mock rclone/restic; package validation.

## 0.2.0 — mTLS production API
- Containerized API on mcp-proxy-adapter 8.11.15.
- Read-only backup browsing and temporary exports; streaming download client.
- Certificate revocation checks on server and client.
- Docker Hub image, Debian package, systemd and client distribution.
- Smart Assistant proxy registration and one verified pipeline.
