# onedrive-backup 0.3.3 — OneDrive Business backups for Ubuntu

Production-only Docker service. Microsoft 365 OneDrive is read via rclone,
mirrored on backup storage, then saved as versioned, encrypted restic snapshots.
No writes are sent to OneDrive.

## Deliverables

- Docker image: vasilyvz/onedrive-backup:0.3.3, Python 3.12,
  mcp-proxy-adapter 8.11.15, HTTPS/mTLS TCP port 8050.
- Debian host package: dist/onedrive-backup_0.3.3_all.deb.
- Python client: dist/client/onedrive_backup_client-0.3.3-py3-none-any.whl.
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

    sudo apt install ./onedrive-backup_0.3.3_all.deb
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

## HTTP API, read-only restic access

All endpoints are protected by mutual TLS. There is no HTTP fallback.

GET    /api/v1/health
GET    /api/v1/snapshots?limit=100
GET    /api/v1/snapshots/{snapshot_id}/files?prefix=...&offset=0&limit=1000
POST   /api/v1/exports
GET    /api/v1/exports/{export_id}
GET    /api/v1/exports/{export_id}/status
DELETE /api/v1/exports/{export_id}

To prepare a single-file export, POST a JSON object containing snapshot_id
and a relative file_path such as Documents/file.pdf. Without file_path,
the server stages a TAR.GZ export of the entire snapshot. The returned
opaque export_id grants access only to that staged export, never to a
server-local arbitrary filesystem path. Data is streamed, not returned as
base64 in JSON. Temporary exports are plaintext, so treat /data/exports
as sensitive and remove them promptly after download. Default maximum
export size is 10 GiB (ONEDRIVE_MAX_EXPORT_BYTES).

JSON-RPC commands provided to MCP Proxy: backup_snapshots,
backup_list_files, backup_prepare_download, backup_download_status,
backup_delete_export. The adapter admin and unrestricted file-transfer
commands are intentionally not exposed by this server.

Without configured restic storage, health returns HTTP 200, while
backup browsing returns HTTP 503 rather than a fabricated empty result.

## Python client

Install the bundled wheel (or use PyPI if published):

    python3 -m pip install dist/client/onedrive_backup_client-0.3.3-py3-none-any.whl
    mkdir -p ~/.config/onedrive-backup
    cp client/config.example.json ~/.config/onedrive-backup/client.json

Set the internal HTTPS URL, trusted CA, client CRT and client key in client.json.

    onedrive-backup-client health
    onedrive-backup-client snapshots
    onedrive-backup-client files SNAPSHOT --prefix Documents
    onedrive-backup-client prepare SNAPSHOT --path Documents/file.pdf
    onedrive-backup-client status EXPORT_ID
    onedrive-backup-client fetch EXPORT_ID --output file.pdf
    onedrive-backup-client download SNAPSHOT --output snapshot.tar.gz
    onedrive-backup-client delete EXPORT_ID

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
