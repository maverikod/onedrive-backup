# OneDrive Backup — руководство по серверу и эксплуатации

Действующая справка production-сервера. Первая страница команды info автоматически формирует содержание; каждый раздел этого файла становится отдельной страницей. Команды MCP документируются на последующих страницах из их фактических метаданных.

## Назначение и ограничения системы

`onedrive-backup` — существующее имя production-сервера резервного копирования **файлов библиотек SharePoint Online** организации Microsoft 365. Сайты и библиотеки обнаруживаются через Microsoft Graph в режиме app-only. Источник используется только на чтение; восстановление допускается только локально, без загрузки в SharePoint.

Граница резервирования: документы и каталоги библиотек. **Не входят** SharePoint Lists, страницы сайтов, ACL/права, настройки, workflows и исходная история версий SharePoint. Версии restic фиксируют состояния файлов только с момента запуска собственного backup.

В ранних выпусках реализованы Graph discovery и базовый CLI для отдельных зеркал/снимков библиотек. Команды MCP для обнаружения доступны, но реальный Graph и резервирование ещё не приняты: нет проверенного диска `/srv/backup`, restic-password и контрольного восстановления. Systemd timer отключён. Старый каталог выгрузок пока не адаптирован для полноценной навигации сайт → библиотека → снимок.

Сервис поставляется как production-only; HTTP API доступен внутри Docker-сети под обязательным mTLS, без опубликованного порта хоста.

## Архитектура и поток данных

```text
Microsoft Graph: /sites/getAllSites → /sites/{siteId}/drives
             | полная пагинация и проверка coverage
             v
/data/sharepoint/inventory.json — стабильные site_id / drive_id
             | каждый цикл discovery проверяется заново
             v
rclone onedrive: --onedrive-drive-id <drive_id> (только чтение)
             | отдельное зеркало по SHA-256(site_id)/SHA-256(drive_id)
             v
/data/mirror/sharepoint/<site-key>/<drive-key>
             | restic backup с тегами sharepoint, site-*, drive-*
             v
/data/restic-repo — зашифрованные версионные снимки
             | каталог и экспорт (полная интеграция SharePoint в работе)
             v
FastAPI / MCP Proxy / Web UI
```

`src/onedrive_api/sharepoint_discovery.py` отвечает за полный обход и безопасную инвентаризацию; `sharepoint_backup.py` выполняет цикл по библиотекам, `sharepoint_discover_cli.py` запускает discovery. `src/onedrive_backup.py` сохраняет общий низкоуровневый механизм restic, preflight и блокировку. При неполном обходе Graph ни один rclone sync не запускается. При ошибке библиотеки задание завершается ошибкой, без `forget/prune`.

Каталог пока содержит прежние однодисковые механизмы. Их расширение до site/library snapshot и Vue 3 — отдельные незавершённые работы.

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

При отсутствии секретов rclone и restic или отдельной файловой системы `/srv/backup` контроллер включает `ONEDRIVE_SCAFFOLD_MODE=1` и отдельный каталог данных, не являющийся репозиторием. Это позволяет проверять HTTPS, регистрацию и справку без Microsoft 365.

Работают `/health`, `GET /commands`, `help` и `info`. Просмотр снимков и подготовка выгрузки возвращают 503; Никаких тестовых снимков и паролей не создаётся.

Чтобы перейти к полной эксплуатации: подключите backup-диск, настройте секреты rclone и restic (пароль restic задаёт docker/deploy.sh при первом запуске), проверьте конфигурацию, затем перезапустите API-службу и выполните контрольный backup. Не включайте таймер до успешной проверки восстановления.

## Токен API и загрузка выгрузок

API — это команды mcp-proxy-adapter поверх JSON-RPC (`POST /api/jsonrpc`). REST `/api/v1/*` удалён. Каждый вызов JSON-RPC и каждая ссылка `/downloads/...` прямого клиента (odbcli, клиент Python, Vue, pipeline) защищены токеном в заголовке `X-API-Key`. Токен — base64(login:password); логин и пароль хранятся одной строкой `login:password` в файле `/var/lib/onedrive-backup/secrets/api-credentials` на хосте (режим 0600, владелец onedrive-backup; в контейнере `/secrets/api-credentials`). Без действующего файла (он отсутствует, пуст или неверного формата) сервис всё равно запускается, а все защищённые запросы прямых клиентов получают 401. Пир MCP Proxy допускается без токена по идентичности mTLS-соединения (адрес транспортного пира должен совпадать с одним из имён `proxy_trust.hosts` в server.json), на каждом маршруте и независимо от наличия этого файла; заголовки `X-Forwarded-For`, `Forwarded`, `X-Real-IP` и `Host` ничего не дают, а без настроенных имён никто не допускается без токена (fail closed). `/health` и `GET /commands` открыты для MCP Proxy; `/ws` и загрузка файлов на сервер закрыты.

`backup_prepare_download` и `backup_download_status` возвращают поле `url` — временную ссылку `/downloads/<export_id>/<filename>` (GET с токеном). Другой способ — `backup_download_begin` и адаптерный `GET /api/transfer/downloads/{transfer_id}/chunks`; передача ограничена каталогом `/data/exports` (`transfer.allowed_directories`), размер и SHA-256 нужно проверить после загрузки.

## Конфигурация server.json

`/etc/onedrive-backup/server.json`, копия шаблона `config/server.json`, разделы:
- `server`: host=0.0.0.0; port=8050; protocol=mtls; servername/advertised_host=onedrive-backup; cert/key и trust-bundle; log_level.
- `registration`: enabled=true; protocol=mtls; register_url=https://mcp-proxy:3004/register; unregister_url=/unregister; server_id=onedrive-backup; cert/key как у сервера; ca=proxy-ca.crt; DNS/hostname check=true; heartbeat URL и interval.
- `client.enabled=false`, `queue_manager.enabled=false`; прямой HTTP-клиент адаптера не создаётся.
- `auth.use_token=false` и `auth.use_roles=false`: машинным клиентам необходим mTLS.

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

## Конфигурация backup.json и политики хранения

`/config/backup.json` содержит `onedrive_remote="onedrive:"` (только корень, без папок), `rclone_config="/secrets/rclone.conf"`, `password_file="/secrets/restic-password"`, `mirror_dir="/data/mirror"`, `repository_dir="/data/restic-repo"`, `lock_file="/data/backup.lock"` и `required_mountpoint="/data"`.

Опции `max_delete=100`, `transfers=4`, `checkers=8` ограничивают синхронизацию. `allow_empty_source=false` не позволяет принять неожиданно пустую библиотеку за удалённые файлы. Библиотеки выбираются по стабильному Graph `drive_id`; пути зеркал строятся из SHA-256 `site_id` и `drive_id`, а не из отображаемых названий.

Политика 14 ежедневных / 8 еженедельных / 12 ежемесячных снимков предусмотрена, но **автоматический forget/prune для многобиблиотечного SharePoint ещё не включён**. Очистку нельзя разрешать до полного backup/restore E2E и корректной обработки исчезнувших библиотек. Не ослабляйте проверку mountpoint.

## Microsoft Entra ID и секреты резервирования

Источник работает только с Microsoft Graph app-only (Tenant ID, Client ID, Client Secret **VALUE**), с администраторским согласием на read-only Application permissions, в частности `Sites.Read.All` и документированный доступ к файлам (`Files.Read.All` или совместимый read-only уровень). Права на запись не требуются и не разрешаются.

`/secrets/rclone.conf` имеет режим 0600 и монтируется **только для чтения**. Он должен содержать раздел `[onedrive]` с `type=onedrive`, `client_credentials=true`, `tenant`, `client_id`, `client_secret`. `restic-password` хранится отдельно, вне репозитория и Docker-образа, с правами 0600. Файлы не копируются в Git, пакеты, stdout или TODO.

`GET /sites/getAllSites` и `GET /sites/{siteId}/drives` выполняются до backup, с обработкой полной пагинации. Неполный обход делает readiness отрицательным. Live-проверка прав и unattended rclone ещё не выполнена; сведения о сконфигурированном приложении сами по себе не подтверждают доступ к сайтам.

## Команды локального резервного копирования

Host runner `onedrive-backup-docker` поддерживает `start`, `stop`, `status`, `ports`, `discover [--dry-run]`, `init`, `backup [--dry-run]`, `check`. Он всегда проверяет `/srv/backup`, наличие секретов и состояние рабочего контейнера; в scaffold запуск backup/init/check запрещён.

`discover` запускает чтение всех сайтов и библиотек, при полном результате атомарно обновляет `/data/sharepoint/inventory.json`; `--dry-run` не изменяет каталог. `backup` заново запускает Graph discovery, затем обходит библиотеки через `rclone` с конкретным `--onedrive-drive-id` и делает отдельные restic snapshots с тегами сайта и библиотеки. `backup --dry-run` проверяет источники и выводит предполагаемые действия без создания зеркал и снимков.

Примеры (только после настройки и проверки диска):

```bash
sudo onedrive-backup-docker discover --dry-run
sudo onedrive-backup-docker discover
sudo onedrive-backup-docker init
sudo onedrive-backup-docker backup --dry-run
sudo onedrive-backup-docker backup
sudo onedrive-backup-docker check
```

При ошибке Graph, пустом источнике, отказе rclone или restic цикл завершаетcя неуспехом. При частичном выполнении уже созданные снимки остаются в restic, но `forget/prune` не вызывается. Исходный SharePoint никогда не изменяется.

## Systemd, расписание и безопасность запуска

`onedrive-backup-api.service` управляет контейнером с mTLS. `onedrive-backup.service` вызывает host runner `onedrive-backup-docker backup` — один цикл discovery + синхронизация всех найденных библиотек + restic snapshots. `onedrive-backup.timer` содержит базовый календарь 02:30 с разбросом до 15 минут, `Persistent=true`. Функция настройки календаря и отслеживания отдельных jobs через MCP ещё не реализована.

**Таймер оставлен disabled/inactive.** Перед его включением требуется подтверждённый `/srv/backup`, app-only Graph доступ, `rclone.conf`, `restic-password`, инициализированный restic, полный dry-run, успешный первый снимок, `check` и контрольное восстановление с проверкой SHA-256. Глобальная блокировка `/data/backup.lock` исключает параллельные циклы.

Команды проверки: `systemctl status onedrive-backup-api.service`, `systemctl is-enabled onedrive-backup.timer`, `docker inspect onedrive-backup`, `onedrive-backup-docker status`. Состояние API `active` или успешный mTLS handshake сами по себе не подтверждают работающий backup.

## Консольный Python-клиент

Wheel `onedrive_backup_client-<VERSION>-py3-none-any.whl` собирается локально. `~/.config/onedrive-backup/client.json` содержит внутренний HTTPS URL, пути к доверенному CA и клиентской паре cert/key, timeout. Клиент должен иметь сетевой доступ к контейнеру (или контролируемому шлюзу) и корректные TLS credentials.

```bash
odbcli health
odbcli snapshots
odbcli files SNAPSHOT --prefix Documents --limit 100
odbcli prepare SNAPSHOT --path Documents/file.pdf
odbcli status EXPORT_ID
odbcli download-link EXPORT_ID
odbcli download-begin EXPORT_ID
odbcli fetch EXPORT_ID --output file.pdf
odbcli download SNAPSHOT --output snapshot.tar.gz
odbcli delete EXPORT_ID
```

Клиент - тонкая обертка над JsonRpcClient библиотеки mcp-proxy-adapter, `odbcli` построен на клиенте. Вход: login и password (токен base64(login:password)) или готовый токен; клиентский сертификат mTLS обязателен. Скачивание идет через transfer-сервис адаптера или временную ссылку; размер и SHA-256 проверяются, после чего временный файл атомарно переименовывается. `--force` позволяет заменить уже существующий файл. Проверки TLS и hostname должны оставаться включёнными.

## Восстановление и контрольный прогон

План контроля перед включением автоматических резервных копий: проверьте mountpoint /srv/backup, успешный rclone remote, доступность restic-password, выполните init, dry-run, одну реальную копию, команду check и восстановление отдельного тестового файла или снимка в **другой каталог**.

Сравните SHA-256 восстановленного файла с ожидаемым. Проверьте сохранение нескольких версий, возраст снимков и политику хранения. Не восстанавливайте поверх зеркала автоматически. Резервные копии ключей/пароля restic нужно хранить вне основного сервера.

Здоровый `/health=200` или зарегистрированный в прокси сервер **не** доказывает корректность OneDrive-авторизации, последнего backup или восстановления.

## Диагностика, ошибки и устранение

- `help` есть, а `info` отсутствует: установлен старый production-образ либо команда не зарегистрирована.
- MCP Proxy отвечает `returned no commands via get_methods()`: отсутствует endpoint `GET /commands`; проверьте разрешённые маршруты FastAPI.
- TLS handshake failed: проверьте SAN, EKU, CA trust, права server.key и mTLS client identity. Не используйте `verify=False`.
- `HTTP 503` на снимках в каркасе: ожидаемая блокировка; необходимы диск, секреты rclone и рабочий restic.
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