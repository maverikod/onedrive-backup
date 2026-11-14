# onedrive-backup — резервное копирование OneDrive Business

Резервное копирование Microsoft 365 OneDrive Business на Ubuntu/Debian: `rclone sync` выполняет загрузку в зеркало, затем `restic backup` создаёт **зашифрованный версионный снимок**. Предыдущие версии остаются доступны после удаления файлов в облаке до истечения политики хранения. OneDrive используется **только как источник**; записи в облако скрипт не делает.

## Сборка Debian-пакета (на CAS-сервере)

```bash
./build.sh
# dist/onedrive-backup_0.1.1_all.deb
sha256sum -c dist/onedrive-backup_0.1.1_all.deb.sha256
dpkg-deb --info dist/onedrive-backup_0.1.1_all.deb
```

Требуется `dpkg-deb` (пакет `dpkg`), Python 3.9+, Bash. Для сборки `root` не нужен благодаря `dpkg-deb --root-owner-group`.

## Установка на сервер Ubuntu/Debian

```bash
sudo apt install ./dist/onedrive-backup_0.1.1_all.deb
# Если переносили .deb на отдельный сервер, укажите путь к файлу там.
```

`apt` устанавливает зависимости: `python3`, `rclone`, `restic`, `adduser`. `postinst` создаёт системного пользователя `onedrive-backup`, приватный каталог `/var/lib/onedrive-backup` и выставляет безопасные права на конфигурацию. Устанавливаются служба `onedrive-backup.service`, таймер `onedrive-backup.timer`, CLI `/usr/bin/onedrive-backup` и man-страница.

**Таймер намеренно не запускается после установки**: сначала требуется авторизовать Microsoft 365, подключить диск бэкапов, задать пароль restic и проверить сухой запуск.

## Подключить диск (обязательно до инициализации)

По умолчанию ожидается файловая система, примонтированная в `/srv/backup`. Проверка `required_mountpoint` предохраняет от записи резервных копий на системный диск, если накопитель не смонтирован.

```bash
findmnt /srv/backup  # должен показывать отдельное смонтированное хранилище
sudo install -d -m 0700 -o onedrive-backup -g onedrive-backup \
  /srv/backup/onedrive
```

Если используется другой путь/точка монтирования, измените `/etc/onedrive-backup/config.json`: `required_mountpoint`, `mirror_dir` и `repository_dir`. Не располагайте зеркало внутри restic-репозитория и наоборот. Не снимайте проверку монтирования без необходимости.

## Авторизация OneDrive Business

**Не передавайте логины, пароли, MFA-коды или OAuth-токены в переписке, репозиторий и Debian-пакет.** Для Microsoft 365 используется делегированный OAuth через `rclone`.

```bash
sudo -u onedrive-backup -H rclone config --config /var/lib/onedrive-backup/rclone.conf
```

Создайте remote `onedrive` (`Storage: onedrive`), авторизуйтесь под своей учётной записью Microsoft 365, выберите диск `OneDrive Personal or Business`, затем нужный Business drive. Если сервер без браузера — на вопрос `Use web browser...` ответьте `n`, на локальном ПК с браузером исполните `rclone authorize "onedrive"` и вставьте результат в **защищённую терминальную сессию сервера**. Рекомендуется версия rclone на ПК, соответствующая версии сервера. Некоторые tenant Microsoft 365 требуют согласия администратора на разрешения приложения; может потребоваться собственная регистрация приложения Microsoft Entra ID. См. https://rclone.org/onedrive/ и https://rclone.org/remote_setup/ .

```bash
sudo chown onedrive-backup:onedrive-backup /var/lib/onedrive-backup/rclone.conf
sudo chmod 600 /var/lib/onedrive-backup/rclone.conf
sudo -u onedrive-backup -H rclone --config /var/lib/onedrive-backup/rclone.conf lsf onedrive:
```

Параметр `onedrive_remote` в `/etc/onedrive-backup/config.json` по умолчанию `onedrive:`. Можно выбрать подкаталог, например `onedrive:Documents`. Политики Microsoft Entra ID могут потребовать одобрения администратором; резервное копирование начнётся **только после** успешной авторизации.

**Область охвата:** копируются доступные пользователю файлы выбранного диска OneDrive. Версии файлов, созданные в Microsoft 365 до первого бэкапа, внутренние корзины, сторонние SharePoint-сайты и данные других пользователей *автоматически не охватываются*. Для них требуются отдельные источники/настройки.

## Ключ шифрования и первый запуск

Сгенерируйте пароль restic под системным пользователем. Сохраните его отдельно, вне сервера (при утере восстановление невозможно):

```bash
sudo -u onedrive-backup -H sh -c \
 'umask 077; head -c 48 /dev/urandom | base64 > /var/lib/onedrive-backup/restic-password'
sudo -u onedrive-backup -H onedrive-backup init
sudo -u onedrive-backup -H onedrive-backup backup --dry-run
sudo -u onedrive-backup -H onedrive-backup backup
sudo -u onedrive-backup -H onedrive-backup snapshots
sudo -u onedrive-backup -H onedrive-backup check
```

`backup --dry-run` проверяет операции синхронизации без изменения зеркала и создания restic-снимка. Первый полноценный запуск может скачивать много данных. Если синхронизация завершилась ошибкой, снимок **не** создаётся; если ошибка при создании restic-снимка — **не** запускается очистка старых снимков.

## Расписание и диагностика

```bash
sudo systemctl daemon-reload
sudo systemctl enable --now onedrive-backup.timer
systemctl list-timers onedrive-backup.timer
sudo systemctl start onedrive-backup.service
sudo journalctl -u onedrive-backup.service --no-pager -n 100
```

Каждый день около 02:30 (плюс случайная задержка до 15 минут); пропущенный запуск выполняется при следующем старте таймера. Одновременные бэкапы блокируются `flock`.

Ограничение на массовые удаления: `max_delete=100`. Если число удалений локального зеркала превысит порог, rclone останавливается и снимок не делается. При намеренном массовом удалении установите осмысленный новый порог после проверки причины. Пустой источник запрещён по умолчанию (`allow_empty_source=false`).

Политика хранения по умолчанию: 14 ежедневных, 8 недельных и 12 месячных снимков. Настраивается в `/etc/onedrive-backup/config.json`. Данные шифруются restic; отдельно от самого сервера полезно сохранять резервную копию restic-репозитория (другой носитель/площадка, защита от удаления).

## Восстановление

Просмотрите идентификаторы снимков:

```bash
sudo -u onedrive-backup -H onedrive-backup snapshots
```

Восстановление на отдельное место (не в живое зеркало):

```bash
sudo install -d -m 0700 -o onedrive-backup -g onedrive-backup /srv/restore-onedrive
sudo -u onedrive-backup -H env \
 RESTIC_REPOSITORY=/srv/backup/onedrive/restic-repo \
 RESTIC_PASSWORD_FILE=/var/lib/onedrive-backup/restic-password \
 restic restore latest:/srv/backup/onedrive/mirror --target /srv/restore-onedrive
```

Замените `latest` на ID конкретного снимка. Точный путь внутри снимка можно узнать через `restic ls <snapshot-id>`. После первого бэкапа обязательно протестируйте восстановление файла.

## Обновление / удаление

Обновление `sudo apt install ./onedrive-backup_<version>_all.deb` сохраняет пользовательскую `conffile` в `/etc` согласно правилам dpkg. `prerm` выключает таймер только при удалении, не на обновлении. При удалении сохраняются приватный каталог с OAuth-токенами, ключом шифрования и сами бэкапы: удалять их следует отдельно вручную после восстановления/архивации.

## Разработка и тестирование

```bash
TMPDIR="$PWD" python3 -m unittest discover -s tests -v
bash -n scripts/build-deb.sh
sh -n packaging/postinst packaging/prerm packaging/postrm packaging/onedrive-backup
./build.sh
```

Интеграционные тесты используют поддельные `rclone`/`restic`, не требуют Microsoft 365 и не затрагивают настоящий сервер бэкапов. Проверка пакета включает `dpkg-deb --info`, `--contents`, распаковку пакета и smoke-тест скрипта.
