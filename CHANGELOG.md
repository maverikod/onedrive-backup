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
