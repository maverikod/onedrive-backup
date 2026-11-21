# onedrive-backup 0.3.21 — OneDrive Business backups for Ubuntu

Production-only Docker service. Microsoft 365 OneDrive is read via rclone,
mirrored on backup storage, then saved as versioned, encrypted restic snapshots.
No writes are sent to OneDrive.

## Deliverables

- Docker image: vasilyvz/onedrive-backup:0.3.21, Python 3.12, rclone 1.76.0 (official release, SHA256-verified),
  mcp-proxy-adapter 8.11.20, server-auth HTTPS (mcp-proxy-adapter configuration), container port 8050 published on the LAN as 8443.
- Debian host package: dist/onedrive-backup_0.3.21_all.deb.
- Python client: dist/client/onedrive_backup_client-0.3.21-py3-none-any.whl.
- Verification: python -m pipeline; after image build: python -m pipeline smoke_https.
- Web UI: a Vue 3 single page application built into the service image (Node 22 stage of docker/Dockerfile, no nginx, no second
  image) and served by the service itself at https://192.168.254.26:8443/ (the same origin as /api/jsonrpc and /downloads, server-auth
  HTTPS, hash routes: #/snapshots, #/sites, #/discovery, #/help, #/info). The service is open on the LAN, so the page asks for a key
  only after a 401 answer and keeps it in page memory. Sources: frontend/ (`npm ci`, `npm run build`, `npm test`).

Build all release artifacts on CAS host via ./build.sh. It tests the code,
builds Python client wheel and sdist, image, Debian package, publishes image
to Docker Hub, and optionally publishes client to PyPI. If the PyPI
token is missing or dontpubpypi is configured, the client remains local.
Release version is defined only in VERSION.

Colliding names (matrix revision 10). Two files of one library that share a folder and whose names are equal after
Unicode NFC normalisation and case folding (for example one name typed in the NFC and the NFD form) cannot both live at
one mirror path: rclone mirrors the first and ignores the rest. Every further copy is kept: the service scans the library
read-only, lets the sync mirror the first object, then fetches each extra by its Graph item id (read-only GET, the
redirect target without the Authorization header) and stores it beside its twin as `<stem>.dup-<h><ext>`, where `<h>` is
the first 8 hex digits of sha256 of the item id (more digits on a name clash). The copy is verified against the size and
quickXorHash of the listing and lands in the same restic snapshot. A kept and verified copy leaves the library `ok` and is
reported by the `duplicates` list and `duplicate_summary` of the run record and by one WARNING log line; a failed fetch or a
hash mismatch makes the library `duplicate_incomplete` (an error library, exit code 1). A real source object named like a
stored copy is not synced and is reported (`DUPLICATE_NAME_RESERVED`). No command, parameter or response schema changes.

## Network, volumes and secrets

Container: onedrive-backup, Docker network smart-assistant.
The service listens on container port 8050 with server-authentication HTTPS (no client certificate) and publishes it
on the LAN as host port 8443 (https://192.168.254.26:8443); the MCP Proxy keeps reaching it by the docker alias
https://onedrive-backup:8050 on smart-assistant. The service is open for now (adapter auth off).
Automatic MCP Proxy registration is enabled:

- Service ID: onedrive-backup
- Registration: https://mcp-proxy:3004/register
- Heartbeat: https://mcp-proxy:3004/proxy/heartbeat
- Interval: 30 seconds.

Host bind mounts:

| Host | Container | Role |
| --- | --- | --- |
| /etc/onedrive-backup | /config:ro | server.json, backup.json, certs |
| /var/lib/onedrive-backup/secrets | /secrets:ro | rclone.conf (original), restic-password |
| /var/lib/onedrive-backup/rclone-state | /rclone-state:rw | writable copy of rclone.conf (refreshed OAuth token) |
| /srv/archive/onedrive-backup | /data:rw | mirror, restic-repo, temporary exports |

The /srv/archive filesystem MUST be mounted and the data directory must lie on it. `docker/deploy.sh`, the Debian
`postinst` and every `docker-run.sh` action (except stop, status and ports) refuse otherwise, naming the resolved path
and its filesystem; the refusal never degrades into the restricted scaffold. The data directory is created by the
operator (owner `onedrive-backup`, mode 0750), never by `postinst`.

`docker-run.sh start` seeds `/var/lib/onedrive-backup/rclone-state/rclone.conf` (mode 0600, owner `onedrive-backup`)
from `/var/lib/onedrive-backup/secrets/rclone.conf` when the copy is absent, empty or older than the original; an
existing newer copy is kept, so a token refreshed by rclone survives a restart. The original stays read-only.

Root project .env holds Docker Hub (optionally PyPI) publishing credentials.
It must never be committed or included in images/packages. At deployment
docker/deploy.sh copies it on the HOST to
/var/lib/onedrive-backup/credentials/.env (root:root, mode 0600).
/etc/default/onedrive-backup contains only that path and public Docker
settings, not the credentials themselves. These registry credentials
are NOT mounted into the container.

## Server certificates (HTTPS)

Install the following external files under /etc/onedrive-backup/certs:

- ca.crt: legacy trusted CA for internal client certificates
- proxy-ca.crt: trust anchor for MCP Proxy and issuer of the service certificate
- trust-bundle.pem: trust bundle of both public CAs (provisioned for the later switch to mTLS, not required for HTTPS)
- server.crt and server.key: dual-purpose TLS identity for the server and proxy registration (SAN: onedrive-backup, localhost, 127.0.0.1 and the LAN address 192.168.254.26)
- client.crt and client.key: optional separately provisioned client identity (not installed by the server package)

The server will not start when server.crt or server.key is missing.
For private keys use owner root, group onedrive-backup, mode 0640.
Config files under /etc/onedrive-backup are owned by root:onedrive-backup.
No client certificate is requested. Exposing the service outside the LAN switches the same adapter configuration to mtls.
CRL validation and lifecycle are delegated to MCP Proxy, not to this server.
TLS versions below 1.2, plaintext HTTP and certificates without trust
validation are not permitted. All smoke-test keys are ephemeral and NEVER
used in production.

## Installation and operations

On a CAS build host:

    python3 -m pipeline
    ./build.sh
    sudo bash docker/deploy.sh

The first `docker/deploy.sh` run on a host asks for the restic repository password on the terminal (twice and
without echo for a new repository, once and checked against the repository when one already exists), writes it to
`/var/lib/onedrive-backup/secrets/restic-password` (mode 0600) and initialises the repository
`/srv/archive/onedrive-backup/restic-repo` with it. Keep a copy of that password outside the host: without it the backups
cannot be restored. Without a terminal and without the password file the script stops with an exact message and
changes nothing; `restic` must be installed on the host.

On a separate Ubuntu host (after copying the .deb and configuring volumes):

    sudo apt install ./onedrive-backup_0.3.21_all.deb
    sudo systemctl enable --now onedrive-backup-api.service
    sudo onedrive-backup-docker info
    sudo onedrive-backup-docker status
    sudo onedrive-backup-docker ports

The API remains disabled until the TLS identities and
mounted backup storage are ready. Microsoft 365 authorization is not required
to start the API; keep the backup timer disabled until authorization and
one successful test backup.

After OneDrive authorization, configure the remote onedrive: in
/var/lib/onedrive-backup/secrets/rclone.conf, and create a strong restic
password in /var/lib/onedrive-backup/secrets/restic-password. Both files
must be mode 0600, owner onedrive-backup. Preserve the encryption password
outside the backup server. OneDrive credentials are NOT included in this
release; Microsoft 365 Entra ID configuration will be done separately.

    sudo onedrive-backup-docker init
    sudo onedrive-backup-docker backup --dry-run
    sudo onedrive-backup-docker backup
    sudo onedrive-backup-docker snapshots
    sudo onedrive-backup-docker check
    sudo systemctl enable --now onedrive-backup.timer

Never enable the timer before one successful backup and a tested restore.
Retention defaults: 14 daily, 8 weekly and 12 monthly snapshots. Only
the configured OneDrive remote is covered (no tenant-wide user discovery).

## API, read-only restic access

The API is the set of mcp-proxy-adapter commands over JSON-RPC (`POST /api/jsonrpc`), reachable
directly over server-authentication HTTPS and through MCP Proxy. There is no HTTP fallback and no REST layer: the
routes `/api/v1/*` are removed. The service is open for now: adapter `auth.use_token` is false, no credential is
checked and every route the adapter itself serves (JSON-RPC, `/downloads`, `/api/transfer/*`, `/api/async`, `/tools/*`,
`/ws`, `/docs`, `/openapi.json`) is reachable by any LAN host; the project owns no route filter, middleware or
authentication code. The later password mode is the adapter static key, switched on by configuration only
(`auth.use_token` true with the key in `auth.tokens` or `security.tokens` from a host secret file, header `X-API-Key`);
the Python client and odbcli then send their optional `password` as that header.

To prepare a single-file export call `backup_prepare_download` with snapshot_id and a relative
file_path such as Documents/file.pdf. Without file_path the server stages a TAR.GZ export of the
entire snapshot. The returned opaque export_id grants access only to that staged export, never to
an arbitrary server-local path, and the field `url` is the temporary download link
`/downloads/<export_id>/<filename>` (GET; with the key header once the password mode is on). The same export can be read through
the adapter transfer service: `backup_download_begin` registers the session and
`GET /api/transfer/downloads/{transfer_id}/chunks` serves it; the transfer is confined to the
exports directory (`transfer.allowed_directories`). Temporary exports are plaintext, so treat
/data/exports as sensitive and remove them with `backup_delete_export` after the download. Default
maximum export size is 10 GiB (ONEDRIVE_MAX_EXPORT_BYTES).

## Python client

Install the bundled wheel (or use PyPI if published):

    python3 -m pip install dist/client/onedrive_backup_client-0.3.21-py3-none-any.whl
    mkdir -p ~/.config/onedrive-backup
    cp client/config.example.json ~/.config/onedrive-backup/client.json

Set the HTTPS URL and the trusted CA in client.json; the client certificate and key are optional (both or neither: mTLS or HTTPS) and so is `password`.

    odbcli health
    odbcli snapshots
    odbcli files SNAPSHOT --prefix Documents
    odbcli prepare SNAPSHOT --path Documents/file.pdf
    odbcli status EXPORT_ID
    odbcli download-link EXPORT_ID
    odbcli download-begin EXPORT_ID
    odbcli fetch EXPORT_ID --output file.pdf
    odbcli download SNAPSHOT --output snapshot.tar.gz
    odbcli delete EXPORT_ID
    odbcli call backup_snapshots --params-json '{"limit": 5}'

The Python client (BackupClient) is a thin wrapper over the mcp-proxy-adapter JsonRpcClient and `odbcli` is
built on it: one method and one subcommand per server command, plus call, raw_call, health, fetch, download and
download-link. Authentication is an optional `password`, sent as `X-API-Key` when configured; the client certificate and key are optional, both or neither. Downloads go through the adapter transfer service or the temporary link, and the
size and SHA-256 of the export are verified before the atomic replace of the output.

Client validates hostname and trusted CA on every connection (mutual TLS when a client certificate is configured).
Before committing an output, it validates downloaded length and SHA-256,
then atomically moves its temporary file to the requested destination.


## Сертификаты сервера (HTTPS)

Единый сертификат сервера и исходящего подключения к MCP Proxy:
mtls-certs/for-proxy/issued/onedrive-backup.crt и onedrive-backup.key.
Он подписан CA mtls-certs/for-proxy/ca/ca.crt, который отдельно
устанавливается как proxy-ca.crt для проверки подлинности самого прокси.
Сертификат содержит CN=onedrive-backup, SAN DNS:onedrive-backup,
DNS:localhost, IP:127.0.0.1, IP:192.168.254.26 и EKU serverAuth + clientAuth.

Обе секции server.ssl и registration.ssl указывают на единый
/config/certs/server.crt и /config/certs/server.key. Клиентский сертификат не запрашивается (server.protocol https);
trust-bundle.pem остаётся подготовленным для будущего перехода на mtls. Приватный ключ CA в контейнер не копируется.
CRL внутри сервера и Python-клиента не используются: политика
отзыва сертификатов выполняется на стороне MCP Proxy.
Сценарий docker/deploy.sh проверяет и переносит файлы на хост
в /etc/onedrive-backup/certs/ с ограниченными правами. Они НЕ входят
в Git, .deb или Docker image.

Исходные mtls-certs/backup-srv.crt и backup-srv.key НЕ используются
ни для сервера, ни для регистрации в прокси: SHA-1 был отклонён OpenSSL.
Новый листовой сертификат подписан SHA-256.

В конфигурации сервера и регистрации значение ssl.crl=null.
FastAPI остаётся доступным исключительно через внутреннюю Docker-сеть
smart-assistant (порт 8050 не публикуется на хост).
Если нужен доступ с локальной сети за пределами Docker, его следует
организовать через отдельный контролируемый шлюз, а не открывать порт
контейнера на всех интерфейсах.


## Debian deployment

/etc/default/onedrive-backup contains source file paths:
ONEDRIVE_CERT_SOURCE, ONEDRIVE_KEY_SOURCE, ONEDRIVE_PROXY_CA_SOURCE,
ONEDRIVE_CLIENT_CA_SOURCE, ONEDRIVE_CREDENTIALS_FILE, and runtime paths.
No secret values are stored there. The Docker Hub file is owned by root
with mode 0600 and may contain DOCKER_USER / DOCKER_PAT.

Debian postinst validates both EKUs, hostname, CA chain and matching key,
installs certs in /etc/onedrive-backup/certs, builds trust-bundle.pem,
pulls the pinned Docker image, and starts the service on the
internal smart-assistant Docker network, without publishing a host port.

Before a backup disk is mounted or the rclone and restic secrets are set, the server
runs in restricted scaffold mode. Snapshot and export commands answer 503 and backup
operations are blocked. The scaffold data directory is separate from
the backup volume. After setup, restart onedrive-backup-api.service
to enable normal operation. Microsoft Entra ID credentials come later.
