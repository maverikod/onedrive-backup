# OneDrive Backup — руководство по серверу и эксплуатации

Действующая справка production-сервера. Первая страница команды info автоматически формирует содержание; каждый раздел этого файла становится отдельной страницей. Команды MCP документируются на последующих страницах из их фактических метаданных.

## Назначение и ограничения системы

OneDrive Backup — сервер резервного копирования Microsoft OneDrive Business (Microsoft 365) на Ubuntu. Он использует `rclone` для локального зеркала, `restic` для зашифрованных и версионированных снимков и FastAPI c `mcp-proxy-adapter` для доступа к каталогу. Пользовательский интерфейс встроен в FastAPI; есть самостоятельный консольный Python-клиент.

OneDrive служит **только источником**. По умолчанию резервируется один настроенный rclone remote, а не все пользователи организации Microsoft 365. Функции массового обнаружения пользователей и полномасштабного экспорта тенанта не реализованы.

Регистрационные данные Microsoft Entra ID пока не предоставлены. Работоспособность инфраструктуры, TLS и MCP Proxy можно проверить в ограниченном режиме каркаса, но это не подтверждает наличие снимков.

Система разрабатывается и поставляется как **production-only**. Отдельный DEV-сервер не разворачивается.

## Архитектура и поток данных

```text
Microsoft OneDrive Business
       | rclone sync (не записывает в источник)
       v
/data/mirror — локальное зеркало
       | restic backup --tag onedrive
       v
/data/restic-repo — зашифрованный репозиторий
       | restic snapshots / ls / dump / restore
       v
Каталог снимков -> FastAPI + UI + JSON-RPC -> MCP Proxy / Python-клиент
```

Код: `src/onedrive_backup.py` — резервирование; `src/onedrive_api/server.py` — API и регистрация; `catalog.py` — каталог restic и подготовка выгрузок; `ui.py` — HTML-кабинет; `admin_password.py` — пароль admin; `info_command.py` и `command_reference.py` — справка.

Передача через MCP предназначена для метаданных и управления выгрузкой; бинарные файлы скачиваются по HTTPS REST. Произвольный доступ к файловой системе хоста не предоставляется.

## Как вызываются MCP-команды

MCP Proxy регистрирует `server_id=onedrive-backup` и адрес `https://onedrive-backup:8050`. Вызов принимает название команды и объект параметров:

```text
call_server(server_id="onedrive-backup", command="help", params={})
call_server(server_id="onedrive-backup", command="info", params={"page": 1})
call_server(server_id="onedrive-backup", command="backup_snapshots", params={"limit": 20})
```

Команда `help` перечисляет действующий реестр; `help(cmdname="backup_snapshots")` показывает точную схему и расширенные метаданные одной команды. `info(page=1)` возвращает содержание. Дальше идут общие главы, глава о командном интерфейсе и **отдельная страница каждой зарегистрированной команды**.

Контракт результата: при успехе `success=true` и объект `data`; при отказе `success=false` и описание ошибки. JSON Schema строго запрещает неизвестные поля там, где `additionalProperties=false`. Ошибка валидации параметров не запускает операцию.

## Пагинация info и структура страниц

Аргумент `page` — целое число от 1 до `total_pages` (по умолчанию 1). Все ответы содержат `page`, `total_pages`, `title`, `kind`, `content`, `previous_page` и `next_page`.

- `toc` — содержание на первой странице: номера и названия абсолютно всех страниц.
- `general` — полные главы руководства по архитектуре, установке, эксплуатации и безопасности.
- `chapter` — обзор группы MCP-команд и номера их страниц.
- `command` — реальная команда сервера: предназначение, аргументы, результат, ошибки, примеры и рекомендации.

`next_page=null` означает последнюю страницу. Перечитывание выполняется последовательными вызовами `info(page=N)`. Неверный тип или номер страницы, выходящий за границы, должны давать ошибку с указанием допустимого диапазона. Тексты страниц не сокращаются без предупреждения; при невозможности выдать целую страницу сервер сообщает об ошибке.

## Установка Debian и жизненный цикл

Единый выпуск включает Docker-образ `vasilyvz/onedrive-backup:<VERSION>`, Debian-пакет `onedrive-backup_<VERSION>_all.deb` и wheel Python-клиента с той же версией. Версия читается из `VERSION`. `build.sh` собирает, проверяет, публикует и устанавливает релиз. Для Git-операций используется CAS.

```bash
sudo dpkg -i onedrive-backup_<VERSION>_all.deb
sudo systemctl status onedrive-backup-api.service
sudo onedrive-backup-docker status
```

`postinst` создаёт пользователя и защищённые каталоги, сохраняет локальные параметры в `/etc/default/onedrive-backup`, проверяет TLS, переносит сертификаты, выполняет `docker pull` и запускает либо перезапускает API. `docker/deploy.sh` только вызывает установку .deb. Права на секреты и сертификаты защищены; секреты не встраиваются в пакет или образ.

До реального резервирования обязательны хранилище, пароль администратора, конфигурация rclone, пароль restic, пробное копирование и проверка восстановления. Автоматический backup timer не должен активироваться раньше.

## Параметры /etc/default/onedrive-backup

Этот файл содержит **пути и несекретные настройки**, не значения PAT или приватных ключей. Он принадлежит root. Шаблон пакета: `/usr/share/onedrive-backup/defaults`.

| Переменная | Значение/назначение |
| --- | --- |
| `ONEDRIVE_IMAGE` | Пинованный тег Docker Hub |
| `ONEDRIVE_CONTAINER` | Имя контейнера: onedrive-backup |
| `ONEDRIVE_NETWORK` | Docker network: smart-assistant |
| `ONEDRIVE_CONFIG_DIR` | /etc/onedrive-backup |
| `ONEDRIVE_DATA_DIR` | /srv/backup/onedrive |
| `ONEDRIVE_SECRET_DIR` | /var/lib/onedrive-backup/secrets |
| `ONEDRIVE_SCAFFOLD_DATA_DIR` | Данные ограниченного каркаса |
| `ONEDRIVE_CERT_SOURCE` | Путь к исходному публичному сертификату сервера |
| `ONEDRIVE_KEY_SOURCE` | Путь к его закрытому ключу |
| `ONEDRIVE_PROXY_CA_SOURCE` | Публичный CA MCP Proxy |
| `ONEDRIVE_CLIENT_CA_SOURCE` | Публичный доверенный клиентский CA |
| `ONEDRIVE_CREDENTIALS_FILE` | Путь к root-only Docker Hub credentials |

Все `*_SOURCE` — абсолютные пути к существующим обычным файлам; не используйте символьные ссылки. При обновлении установщик сохраняет локально изменённые настройки. Если сертификаты заменены, повторно выполняйте штатную процедуру установки и проверку mTLS.

## Docker Hub credentials и публикация

`ONEDRIVE_CREDENTIALS_FILE` обычно указывает на `/var/lib/onedrive-backup/credentials/.env`, владелец root, режим 0600. Он может содержать `DOCKER_USER` и `DOCKER_PAT`. Debian-установщик использует временный `DOCKER_CONFIG` и `docker login --password-stdin`, не записывая PAT в командную строку и постоянную конфигурацию.

Для сборки проектный `.env` содержит параметры публикации. `dontpubpypi` означает, что Python-клиент собирается локально, без загрузки на PyPI. Docker Hub credentials не передаются контейнеру и не дают прав на чтение Microsoft 365.

Не выводите PAT или содержимое секретных файлов в логи, результаты MCP или Git.

## Сертификаты, mTLS и CRL

Одна пара `server.crt`/`server.key`, выданная доверенным CA прокси, используется и для HTTPS-сервера, и для исходящей регистрации MCP Proxy. Требуются `CN/SAN DNS:onedrive-backup` и EKU `serverAuth`, `clientAuth`. Проверяются цепочка, DNS-имя, соответствие приватного ключа и назначение сертификата.

Файлы на хосте — `/etc/onedrive-backup/certs/server.crt`, `server.key`, `proxy-ca.crt`, `ca.crt`, `trust-bundle.pem`. В контейнере они видны под `/config/certs`, каталог /config монтируется только для чтения. HTTPS требует клиентский сертификат `CERT_REQUIRED`, TLS не ниже 1.2.

`server.ssl.crl` и `registration.ssl.crl` равны `null`. CRL в OneDrive Backup не проверяется; политика отзыва переносится в MCP Proxy и должна проверяться **отдельно**. Не используйте прежние SHA-1 `backup-srv.crt`/`backup-srv.key`.

## Docker-сеть, тома и доступность

Имя контейнера `onedrive-backup`, внешний Docker network `smart-assistant`, внутренний HTTPS `8050`. FastAPI слушает `0.0.0.0:8050` только **внутри контейнера**. Публикации порта на хосте нет; это проверяется через `docker inspect ... HostConfig.PortBindings` (пустой объект).

Конфигурация: `/etc/onedrive-backup -> /config:ro`. При штатном режиме: `/srv/backup/onedrive -> /data:rw`. При отсутствии смонтированного диска каркас вместо неё использует отдельную `/var/lib/onedrive-backup/scaffold-data`.

Внимание: текущий `docker-run.sh` должен быть дополнительно проверен на фактическое монтирование каталога `ONEDRIVE_SECRET_DIR` в `/secrets` до включения реального backup. Наличие `rclone.conf` и пароля restic на хосте само по себе недостаточно, если они не доступны внутри контейнера.

Веб-интерфейс с другой локальной машины требует специально настроенного доверенного шлюза; открывать порт всем интерфейсам хоста не следует.

## Регистрация MCP Proxy и обнаружение команд

Регистрация выполняется по `https://mcp-proxy:3004/register` с использованием mTLS. Действующие параметры: server_id `onedrive-backup`, URL `https://onedrive-backup:8050`, heartbeat примерно каждые 30 секунд.

MCP Proxy проверяет `/health` и обращается к `GET /commands` для обнаружения команд. Если `/commands` отсутствует, регистрация отвергается с сообщением `returned no commands via get_methods()`. Доступен лишь намеренно ограниченный реестр: `help`, `info`, `backup_*`. Произвольные admin/transfer/конфигурационные операции адаптера отключены.

После развёртывания проверьте сервер через список MCP Proxy, вызов `help`, `info(page=1)` и `backup_snapshots`. В режиме каркаса последняя команда ожидаемо отвечает 503, но сервер должен оставаться зарегистрированным.

## Режим ограниченного каркаса

При отсутствии хеша admin или отдельной файловой системы `/srv/backup` контроллер включает `ONEDRIVE_SCAFFOLD_MODE=1` и отдельный каталог данных, не являющийся репозиторием. Это позволяет проверять HTTPS, регистрацию и справку без Microsoft 365.

Работают `/health`, `GET /commands`, `GET /api/v1/health`, `help` и `info`. Просмотр снимков и подготовка выгрузки возвращают 503; HTML-вход без пароля администратора недоступен. Никаких тестовых снимков и паролей не создаётся.

Чтобы перейти к полной эксплуатации: подключите backup-диск, задайте admin-пароль, настроьте секреты rclone и restic, проверьте конфигурацию, затем перезапустите API-службу и выполните контрольный backup. Не включайте таймер до успешной проверки восстановления.

## Конфигурация server.json

`/etc/onedrive-backup/server.json`, копия шаблона `config/server.json`, разделы:
- `server`: host=0.0.0.0; port=8050; protocol=mtls; servername/advertised_host=onedrive-backup; cert/key и trust-bundle; log_level.
- `registration`: enabled=true; protocol=mtls; register_url=https://mcp-proxy:3004/register; unregister_url=/unregister; server_id=onedrive-backup; cert/key как у сервера; ca=proxy-ca.crt; DNS/hostname check=true; heartbeat URL и interval.
- `client.enabled=false`, `queue_manager.enabled=false`; прямой HTTP-клиент адаптера не создаётся.
- `auth.use_token=false` и `auth.use_roles=false`: для HTML admin применяется отдельный пароль, машинным клиентам необходим mTLS.

Сервер использует только защищённые маршруты приложения и discovery `/commands`. Отсутствие `server.ssl.ca` или ключа должно препятствовать запуску; TLS-проверки нельзя отключать ради регистрации.

## Конфигурация backup.json и политики хранения

`/config/backup.json` задаёт:
- `onedrive_remote="onedrive:"`; `rclone_config="/secrets/rclone.conf"`.
- `mirror_dir="/data/mirror"`; `repository_dir="/data/restic-repo"`.
- `password_file="/secrets/restic-password"`; `lock_file="/secrets/backup.lock"`.
- `required_mountpoint="/data"` — настоящая файловая система backup-диска.
- `keep_daily=14`, `keep_weekly=8`, `keep_monthly=12`.
- `max_delete=100`, `transfers=4`, `checkers=8`, `allow_empty_source=false`.

Зеркало не является резервной копией само по себе: восстановление предыдущих версий обеспечивается restic. Пароль restic храните отдельно и сохраняйте безопасную копию: его утрата делает расшифровку невозможной. Не устанавливайте `required_mountpoint=null` как обход отсутствующего диска.

## Microsoft Entra ID и секреты резервирования

Tenant ID, Client ID, Client Secret пока **не предоставлены**; штатная unattended-авторизация OneDrive Business будет настраиваться отдельно. Конфигурация rclone должна содержать разрешённый OneDrive remote `onedrive:`, доступный из процесса резервного копирования.

`rclone.conf` и файл пароля restic — отдельные от Docker Hub credentials секреты. Они должны находиться в каталоге, недоступном посторонним, с минимальными файловыми правами и монтироваться в контейнер под `/secrets`. Перед разрешением backup проверьте чтение конфигурации внутри контейнера, работу rclone и точный объём OneDrive.

Не записывайте регистрационные данные Microsoft 365 в `/etc/default`, Docker image, .deb, stdout или Git.

## Команды локального резервного копирования

Движок `src/onedrive_backup.py` поддерживает `init`, `backup`, `backup --dry-run`, `snapshots` и `check`. Прямой пример внутри корректно настроенного контейнера:

```bash
python -m onedrive_backup --config /config/backup.json init
python -m onedrive_backup --config /config/backup.json backup --dry-run
python -m onedrive_backup --config /config/backup.json backup
python -m onedrive_backup --config /config/backup.json snapshots
python -m onedrive_backup --config /config/backup.json check
```

`init` запускается один раз для пустого restic-репозитория. `backup --dry-run` проверяет синхронизацию без изменения зеркала и снимков. Реальный `backup` выполняет rclone sync с ограничением массового удаления `max_delete`, затем restic backup, а после успеха — forget/prune по политике хранения. При ошибке rclone снимок не создаётся. Файловая блокировка `flock` не допускает параллельных запусков.

Документированные в старых версиях оболочки команды `onedrive-backup-docker backup/init` следует сверить с установленным runner: доступный сейчас shell runner обслуживает start/stop/status/ports; backup через него не реализован.

## Systemd, расписание и безопасность запуска

`onedrive-backup-api.service` управляет контейнером и использует `/etc/default/onedrive-backup`. Тип `oneshot` с `RemainAfterExit=yes`: статус active означает успех запуска контроллера; фактическое состояние контейнера необходимо проверить отдельно.

`onedrive-backup.service` — разовый backup unit; `onedrive-backup.timer` — ежедневный timer примерно на 02:30 с случайной задержкой до 15 минут. До настройки OneDrive и проверки рабочего механизма запуска backup unit **не включайте таймер**.

```bash
sudo systemctl status onedrive-backup-api.service
sudo docker inspect onedrive-backup
sudo docker logs --tail 100 onedrive-backup
sudo onedrive-backup-docker status
sudo onedrive-backup-docker ports
```

Не применяйте массовый Docker prune, удаление volumes или очистку restic-repo без предварительной оценки хранилища.

## REST API и безопасность экспорта

Под mTLS доступны:
- `GET /api/v1/health` — состояние API.
- `GET /api/v1/snapshots?limit=100` — снимки.
- `GET /api/v1/snapshots/{snapshot_id}/files` с prefix, offset, limit.
- `POST /api/v1/exports` с snapshot_id, необязательным file_path.
- `GET /api/v1/exports/{export_id}` — байты файла.
- `GET /api/v1/exports/{export_id}/status` — метаданные.
- `DELETE /api/v1/exports/{export_id}` — удалить выгрузку.

`export_id` непрозрачен; нельзя передавать в API путь к произвольному файлу хоста. При выгрузке полного снимка создаётся `tar.gz`. По умолчанию лимит экспорта 10 GiB (`ONEDRIVE_MAX_EXPORT_BYTES`), срок жизни 24 часа.

**Выгрузки содержат plaintext**, несмотря на зашифрованный исходный restic. После скачивания проверяйте размер и SHA-256, затем удаляйте временную выгрузку. Просроченный export возвращает 410, неизвестный — 404, превышение лимита — 413.

## HTML-интерфейс и авторизация admin

Сервер предоставляет `/ui/login` и `/ui/`, просмотр снимков/файлов, подготовку выгрузок, скачивание и выход. HTML работает внутри того же FastAPI; отдельного сервера нет.

Единственный пользователь — `admin`. Пароль задаётся интерактивно через `sudo onedrive-backup-admin-password` и хранится исключительно как PBKDF2-HMAC-SHA256 хеш с 600000 итераций и солью. Файл `/etc/onedrive-backup/admin-password.hash` должен иметь права 0600.

Дополнительная защита: mTLS, cookie Secure/HttpOnly/SameSite=Strict, срок сессии 8 часов, CSRF, ограничение попыток входа, экранирование HTML, защитные HTTP-заголовки и запрет кеширования. Смена пароля инвалидирует старые сессии. В каркасе без хеша вход возвращает HTTP 503; готового пароля нет.

## Консольный Python-клиент

Wheel `onedrive_backup_client-<VERSION>-py3-none-any.whl` собирается локально. `~/.config/onedrive-backup/client.json` содержит внутренний HTTPS URL, пути к доверенному CA и клиентской паре cert/key, timeout. Клиент должен иметь сетевой доступ к контейнеру (или контролируемому шлюзу) и корректные TLS credentials.

```bash
onedrive-backup-client health
onedrive-backup-client snapshots
onedrive-backup-client files SNAPSHOT --prefix Documents --limit 100
onedrive-backup-client prepare SNAPSHOT --path Documents/file.pdf
onedrive-backup-client status EXPORT_ID
onedrive-backup-client fetch EXPORT_ID --output file.pdf
onedrive-backup-client download SNAPSHOT --output snapshot.tar.gz
onedrive-backup-client delete EXPORT_ID
```

Клиент потоково скачивает файл, проверяет размер и SHA-256, после чего атомарно переименовывает временный файл. `--force` позволяет заменить уже существующий файл. Проверки TLS и hostname должны оставаться включёнными.

## Восстановление и контрольный прогон

План контроля перед включением автоматических резервных копий: проверьте mountpoint /srv/backup, успешный rclone remote, доступность restic-password, выполните init, dry-run, одну реальную копию, команду check и восстановление отдельного тестового файла или снимка в **другой каталог**.

Сравните SHA-256 восстановленного файла с ожидаемым. Проверьте сохранение нескольких версий, возраст снимков и политику хранения. Не восстанавливайте поверх зеркала автоматически. Резервные копии ключей/пароля restic нужно хранить вне основного сервера.

Здоровый `/health=200` или зарегистрированный в прокси сервер **не** доказывает корректность OneDrive-авторизации, последнего backup или восстановления.

## Диагностика, ошибки и устранение

- `help` есть, а `info` отсутствует: установлен старый production-образ либо команда не зарегистрирована.
- MCP Proxy отвечает `returned no commands via get_methods()`: отсутствует endpoint `GET /commands`; проверьте разрешённые маршруты FastAPI.
- TLS handshake failed: проверьте SAN, EKU, CA trust, права server.key и mTLS client identity. Не используйте `verify=False`.
- `HTTP 503` на снимках в каркасе: ожидаемая блокировка; необходимы диск, пароль admin и рабочий restic.
- `HTTP 503` при штатном режиме: проверить mountpoint, `/secrets`, пароль restic и целостность репозитория.
- `HTTP 400`: неправильные аргументы (snapshot_id, prefix, page).
- `HTTP 404/410`: отсутствует/просрочен export.
- `HTTP 413`: превышен лимит экспорта.
- `systemctl active` при аварии контейнера: отдельно проверьте `docker inspect` и logs.
- Ошибка Docker/containerd или нехватка места: сначала инвентаризация; не удаляйте тома и снимки без анализа.

Главные диагностические команды: `systemctl status onedrive-backup-api.service`, `journalctl -u onedrive-backup-api.service`, `docker logs --tail 100 onedrive-backup`, проверка в списке MCP Proxy, `help` и `info(page=1)`.

## Сборка, тестирование и правила релиза

Единая контрольная точка: `python3 -m pipeline` — синтаксис, конфигурация, unit tests и безопасность. `python3 -m pipeline smoke_mtls` — реальное mTLS соединение с тестовыми ключами. В production-образе запускаются браузерные тесты FastAPI. После изменения состава команд проверяются `help` и последовательное чтение абсолютно всех страниц `info`.

`build.sh` — единственная сборочная точка: Python wheel/sdist, Docker image, Debian, публикация при наличии прав, установка production. Используйте версию из `VERSION` для образа, пакета и клиента.

Git-операции выполнять только через CAS; ветка `cas`, в `main` не переходить без разрешения. Перед коммитом проверить исключение сертификатов, закрытых ключей, токенов и данных backup. Остановиться на ошибке pipeline; не объявлять релиз зелёным при пропущенной проверке, критичной для изменённых функций.