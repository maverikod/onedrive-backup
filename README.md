# onedrive-backup 0.3.11 — OneDrive Business backups for Ubuntu

Production-only Docker service. Microsoft 365 OneDrive is read via rclone,
mirrored on backup storage, then saved as versioned, encrypted restic snapshots.
No writes are sent to OneDrive.

## Deliverables

- Docker image: vasilyvz/onedrive-backup:0.3.11, Python 3.12,
  mcp-proxy-adapter 8.11.16, HTTPS/mTLS TCP port 8050.
- Debian host package: dist/onedrive-backup_0.3.11_all.deb.
- Python client: dist/client/onedrive_backup_client-0.3.11-py3-none-any.whl.
- Verification: python -m pipeline; after image build: python -m pipeline smoke_mtls.

Build all release artifacts on CAS host via ./build.sh. It tests the code,
builds Python client wheel and sdist, image, Debian package, publishes image
to Docker Hub, and optionally publishes client to PyPI. If the PyPI
token is missing or dontpubpypi is configured, the client remains local.
Release version is defined only in VERSION.

## Network, volumes and secrets

Container: onedrive-backup, Docker network smart-assistant.
FastAPI listens on container port 8050, but NO port is published on the host.
Direct API and web UI access is limited to containers on smart-assistant.
Automatic MCP Proxy registration is enabled:

- Service ID: onedrive-backup
- Registration: https://mcp-proxy:3004/register
- Heartbeat: https://mcp-proxy:3004/proxy/heartbeat
- Interval: 30 seconds.

Host bind mounts:

| Host | Container | Role |
| --- | --- | --- |
| /etc/onedrive-backup | /config:ro | server.json, backup.json, certs |
| /var/lib/onedrive-backup/secrets | /secrets:rw | rclone.conf, restic-password |
| /srv/backup/onedrive | /data:rw | mirror, restic-repo, temporary exports |

The /srv/backup filesystem MUST be mounted before starting the service,
otherwise it refuses to start. Keep this on real backup storage, not rootfs.

Root project .env holds Docker Hub (optionally PyPI) publishing credentials.
It must never be committed or included in images/packages. At deployment
docker/deploy.sh copies it on the HOST to
/var/lib/onedrive-backup/credentials/.env (root:root, mode 0600).
/etc/default/onedrive-backup contains only that path and public Docker
settings, not the credentials themselves. These registry credentials
are NOT mounted into the container.

## Mandatory mTLS certificates

Install the following external files under /etc/onedrive-backup/certs:

- ca.crt: legacy trusted CA for internal client certificates
- proxy-ca.crt: trust anchor for MCP Proxy and issuer of the service certificate
- trust-bundle.pem: inbound mTLS trust bundle of both public CAs
- server.crt and server.key: dual-purpose TLS identity for the server and proxy registration
- client.crt and client.key: optional separately provisioned client identity (not installed by the server package)

The server will not start when any required certificate or key is missing.
For private keys use owner root, group onedrive-backup, mode 0640.
Config files under /etc/onedrive-backup are owned by root:onedrive-backup.
Client certificates are verified during the TLS handshake against trusted CAs.
CRL validation and lifecycle are delegated to MCP Proxy, not to this server.
TLS versions below 1.2, plaintext HTTP and certificates without trust
validation are not permitted. All smoke-test keys are ephemeral and NEVER
used in production.

## Installation and operations

On a CAS build host:

    python3 -m pipeline
    ./build.sh
    sudo bash docker/deploy.sh

On a separate Ubuntu host (after copying the .deb and configuring volumes):

    sudo apt install ./onedrive-backup_0.3.11_all.deb
    sudo systemctl enable --now onedrive-backup-api.service
    sudo onedrive-backup-docker info
    sudo onedrive-backup-docker status
    sudo onedrive-backup-docker ports

The API remains disabled until the admin password hash, TLS identities and
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
directly over mutual TLS and through MCP Proxy. There is no HTTP fallback and no REST layer: the
routes `/api/v1/*` are removed. Every JSON-RPC call and every download of a direct peer (odbcli, the Python client, the Vue UI, the pipeline)
needs the token header `X-API-Key`; the token is base64(login:password) of the one line `login:password` kept in
`/var/lib/onedrive-backup/secrets/api-credentials` (mode 0600, owner onedrive-backup, mounted
read-only at `/secrets`). Without a valid file (absent, empty or malformed) the service still starts and every direct request answers 401.
The MCP Proxy peer is admitted with no token on mutual-TLS transport identity alone (its transport address must be
one of the `proxy_trust.hosts` names of server.json), on every route it reaches and whether or not that file exists;
`X-Forwarded-For`, `Forwarded`, `X-Real-IP` and `Host` grant nothing, and with no configured name nobody is
admitted without a token. `/health` and
`GET /commands` stay open for MCP Proxy; `/ws` and the upload routes are closed.

To prepare a single-file export call `backup_prepare_download` with snapshot_id and a relative
file_path such as Documents/file.pdf. Without file_path the server stages a TAR.GZ export of the
entire snapshot. The returned opaque export_id grants access only to that staged export, never to
an arbitrary server-local path, and the field `url` is the temporary download link
`/downloads/<export_id>/<filename>` (GET with the token header). The same export can be read through
the adapter transfer service: `backup_download_begin` registers the session and
`GET /api/transfer/downloads/{transfer_id}/chunks` serves it; the transfer is confined to the
exports directory (`transfer.allowed_directories`). Temporary exports are plaintext, so treat
/data/exports as sensitive and remove them with `backup_delete_export` after the download. Default
maximum export size is 10 GiB (ONEDRIVE_MAX_EXPORT_BYTES).

## Python client

Install the bundled wheel (or use PyPI if published):

    python3 -m pip install dist/client/onedrive_backup_client-0.3.11-py3-none-any.whl
    mkdir -p ~/.config/onedrive-backup
    cp client/config.example.json ~/.config/onedrive-backup/client.json

Set the internal HTTPS URL, trusted CA, client CRT and client key in client.json.

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
download-link. Authentication is login and password (token base64(login:password)) or a ready token; the mTLS
client certificate is mandatory. Downloads go through the adapter transfer service or the temporary link, and the
size and SHA-256 of the export are verified before the atomic replace of the output.

Client validates hostname, trusted CA and mutual TLS on every connection.
Before committing an output, it validates downloaded length and SHA-256,
then atomically moves its temporary file to the requested destination.


## Административный веб-интерфейс (0.3.1)

FastAPI на основе MCP Proxy Adapter предоставляет /ui/login и /ui/.
Доступны авторизация, список снимков, просмотр каталога файлов,
подготовка выгрузки и скачивание файлов/архивов.

Безопасность: обязательные клиентский mTLS-сертификат и отдельный
пароль пользователя admin. Готового пароля не существует. На Ubuntu
после установки .deb выполните sudo onedrive-backup-admin-password.
Новый пароль вводится без отображения и не включается в историю команд.
В /etc/onedrive-backup/admin-password.hash хранится только соль и хеш
PBKDF2-SHA256 (600 000 итераций), права 0600, пользователь onedrive-backup.
Файл не входит в Git, Debian-пакет и Docker-образ. При смене пароля все
старые сессии автоматически становятся недействительными.

Cookie: Secure, HttpOnly, SameSite=Strict, время жизни восемь часов;
есть защита CSRF, ограничение неудачных попыток, экранирование HTML,
защитные HTTP-заголовки и запрет кеширования.
Без установленного хеша приложение не запускается.

Единый сертификат сервера и исходящего подключения к MCP Proxy:
mtls-certs/for-proxy/issued/onedrive-backup.crt и onedrive-backup.key.
Он подписан CA mtls-certs/for-proxy/ca/ca.crt, который отдельно
устанавливается как proxy-ca.crt для проверки подлинности самого прокси.
Сертификат содержит CN=onedrive-backup, SAN DNS:onedrive-backup,
DNS:localhost, IP:127.0.0.1 и EKU serverAuth + clientAuth.

Обе секции server.ssl и registration.ssl указывают на единый
/config/certs/server.crt и /config/certs/server.key. Для проверки
входящих клиентских сертификатов используются публичные CA из
trust-bundle.pem. Приватный ключ CA в контейнер не копируется.
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

Before a backup disk is mounted or a password has been set, the server
runs in restricted scaffold mode. Login returns HTTP 503 and backup
operations are blocked. The scaffold data directory is separate from
the backup volume. After setup, restart onedrive-backup-api.service
to enable normal operation. Microsoft Entra ID credentials come later.
