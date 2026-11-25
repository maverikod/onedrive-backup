'''Frozen titles of the info manual pages 2..45 of release 0.3.27 (matrix TODO 10.22.9 TM9: pages 2..45 keep their titles and numbers).

Read from the live service on 2026-11-25 (0.3.28 serves the same manual: ONEDRIVE_INFO.md last changed before 0.3.27). Page 1 is the table of
contents and its text changes with the appended page, so its title only is kept apart; the recipes page is appended after page 45.
'''

from __future__ import annotations

TITLES_0327: dict[int, str] = {
    2: 'Назначение и ограничения системы',
    3: 'Архитектура и поток данных',
    4: 'Как вызываются MCP-команды',
    5: 'Пагинация info и структура страниц',
    6: 'Установка Debian и жизненный цикл',
    7: 'Параметры /etc/default/onedrive-backup',
    8: 'Docker Hub credentials и публикация',
    9: 'Сертификаты, HTTPS и CRL',
    10: 'Docker-сеть, тома и доступность',
    11: 'Регистрация MCP Proxy и обнаружение команд',
    12: 'Режим ограниченного каркаса',
    13: 'Веб-интерфейс (Vue SPA)',
    14: 'Токен API и загрузка выгрузок',
    15: 'Конфигурация server.json',
    16: 'Конфигурация backup.json и политики хранения',
    17: 'Конфигурация backup.json и политики хранения',
    18: 'Microsoft Entra ID и секреты резервирования',
    19: 'Команды локального резервного копирования',
    20: 'Systemd, расписание и безопасность запуска',
    21: 'Консольный Python-клиент',
    22: 'Восстановление и контрольный прогон',
    23: 'Диагностика, ошибки и устранение',
    24: 'Сборка, тестирование и правила релиза',
    25: 'Chapter: backup',
    26: 'backup_delete_export',
    27: 'backup_download_begin',
    28: 'backup_download_status',
    29: 'backup_filter_options',
    30: 'backup_folder_children',
    31: 'backup_list_files',
    32: 'backup_prepare_download',
    33: 'backup_schedule_get',
    34: 'backup_schedule_set',
    35: 'backup_schedule_status',
    36: 'backup_search_files',
    37: 'backup_snapshots',
    38: 'backup_suggest_names',
    39: 'Chapter: documentation',
    40: 'help',
    41: 'info',
    42: 'Chapter: sharepoint',
    43: 'backup_discovery_status',
    44: 'backup_libraries_list',
    45: 'backup_sites_list',
}
