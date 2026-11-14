#!/usr/bin/env python3
"""OneDrive -> local mirror (rclone) -> encrypted, versioned snapshots (restic).

Requires Linux, Python >= 3.9, rclone, restic. No third-party Python packages.
"""

from __future__ import annotations

import argparse
import contextlib
import fcntl
import json
import logging
from logging.handlers import RotatingFileHandler
import os
from pathlib import Path
import shutil
import subprocess
import sys
from typing import Any, Dict, Iterator, List

LOG = logging.getLogger("onedrive_backup")


class BackupError(Exception):
    """An operational/safety check failed."""


def ensure_child(base: Path, child: Path) -> bool:
    """Return true if child is inside base, or equal to it."""
    try:
        child.relative_to(base)
        return True
    except ValueError:
        return False


def path(name: Any) -> Path:
    if not isinstance(name, str) or not name.strip():
        raise BackupError("Путь в конфигурации должен быть непустой строкой")
    value = Path(name).expanduser()
    if not value.is_absolute():
        raise BackupError("Используйте только абсолютные пути: " + name)
    return value.resolve()


def load_config(filename: Path) -> Dict[str, Any]:
    try:
        cfg = json.loads(filename.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise BackupError(f"Невозможно прочитать JSON-конфигурацию {filename}: {exc}") from exc
    if not isinstance(cfg, dict):
        raise BackupError("Конфигурация должна быть JSON-объектом")

    defaults = {
        "keep_daily": 14,
        "keep_weekly": 8,
        "keep_monthly": 12,
        "max_delete": 100,
        "transfers": 4,
        "checkers": 8,
        "allow_empty_source": False,
        "rclone_bin": "rclone",
        "restic_bin": "restic",
        "required_mountpoint": None,
        "log_file": None,
    }
    cfg = {**defaults, **cfg}
    for field in ("onedrive_remote", "rclone_config", "mirror_dir",
                  "repository_dir", "password_file", "lock_file"):
        if not isinstance(cfg.get(field), str) or not cfg[field].strip():
            raise BackupError(f"Не указан параметр: {field}")

    remote = cfg["onedrive_remote"]
    # Destination remote is intentionally never allowed; OneDrive is read-only here.
    if not remote.endswith(":") and ":" not in remote:
        raise BackupError("onedrive_remote должен выглядеть как 'onedrive:' или 'onedrive:Folder'")
    if remote.startswith(":") or remote.startswith("-"):
        raise BackupError("Некорректное имя OneDrive remote")

    for field in ("rclone_config", "mirror_dir", "repository_dir", "password_file", "lock_file"):
        cfg[field] = path(cfg[field])
    for field in ("required_mountpoint", "log_file"):
        if cfg[field] is not None:
            cfg[field] = path(cfg[field])

    mirror, repo = cfg["mirror_dir"], cfg["repository_dir"]
    if ensure_child(mirror, repo) or ensure_child(repo, mirror):
        raise BackupError("mirror_dir и repository_dir не должны пересекаться")
    if mirror == Path("/") or repo == Path("/"):
        raise BackupError("Нельзя использовать / как каталог зеркала или репозитория")
    if ensure_child(mirror, cfg["lock_file"]) or ensure_child(repo, cfg["lock_file"]):
        raise BackupError("lock_file должен располагаться вне mirror_dir и repository_dir")
    for field in ("password_file", "rclone_config", "log_file"):
        value = cfg[field]
        if value is not None and (ensure_child(mirror, value) or ensure_child(repo, value)):
            raise BackupError(f"{field} не должен быть внутри зеркала или репозитория")
    for field in ("keep_daily", "keep_weekly", "keep_monthly", "transfers", "checkers"):
        if type(cfg[field]) is not int or cfg[field] < 1:
            raise BackupError(f"{field} должен быть целым числом >= 1")
    if type(cfg["max_delete"]) is not int or cfg["max_delete"] < 0:
        raise BackupError("max_delete должен быть целым числом >= 0")
    if type(cfg["allow_empty_source"]) is not bool:
        raise BackupError("allow_empty_source должен быть true или false")
    return cfg


def configure_logging(logfile: Path | None) -> None:
    LOG.setLevel(logging.INFO)
    fmt = logging.Formatter("%(asctime)s %(levelname)-7s %(message)s")
    if not LOG.handlers:
        output = logging.StreamHandler(sys.stdout)
        output.setFormatter(fmt)
        LOG.addHandler(output)
    if logfile:
        logfile.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        handler = RotatingFileHandler(logfile, maxBytes=10 * 1024 * 1024,
                                      backupCount=5, encoding="utf-8")
        handler.setFormatter(fmt)
        LOG.addHandler(handler)


def preflight(cfg: Dict[str, Any]) -> None:
    mountpoint = cfg["required_mountpoint"]
    if mountpoint:
        if not mountpoint.is_mount():
            raise BackupError(f"Диск бэкапов не смонтирован: {mountpoint}")
        for field in ("mirror_dir", "repository_dir"):
            if not ensure_child(mountpoint, cfg[field]):
                raise BackupError(f"{field} должен быть внутри {mountpoint}")

    for executable in (cfg["rclone_bin"], cfg["restic_bin"]):
        if shutil.which(executable) is None:
            raise BackupError(f"Утилита не найдена в PATH: {executable}")
    for key in ("rclone_config", "password_file"):
        if not cfg[key].is_file():
            raise BackupError(f"Файл отсутствует: {cfg[key]}")
    if cfg["password_file"].stat().st_size == 0:
        raise BackupError("password_file пуст")
    if cfg["password_file"].stat().st_mode & 0o077:
        raise BackupError("Пароль restic должен храниться с правами 0600: " + str(cfg["password_file"]))
    if cfg["rclone_config"].stat().st_mode & 0o077:
        LOG.warning("Права на rclone_config шире 0600 — рекомендуется chmod 600")


def restic_env(cfg: Dict[str, Any]) -> Dict[str, str]:
    env = os.environ.copy()
    env["RESTIC_REPOSITORY"] = str(cfg["repository_dir"])
    env["RESTIC_PASSWORD_FILE"] = str(cfg["password_file"])
    return env


def run_command(cmd: List[str], env: Dict[str, str] | None = None, *,
                capture: bool = False) -> str:
    LOG.info("Команда: %s", " ".join(cmd))
    if capture:
        result = subprocess.run(cmd, env=env, text=True,
                                stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                check=False)
        if result.returncode != 0:
            raise BackupError(f"Команда завершилась с кодом {result.returncode}: "
                              f"{' '.join(cmd)}\n{result.stderr.strip()}")
        return result.stdout

    with subprocess.Popen(cmd, env=env, stdout=subprocess.PIPE,
                          stderr=subprocess.STDOUT, text=True,
                          bufsize=1, errors="replace") as process:
        assert process.stdout is not None
        for line in process.stdout:
            LOG.info("  %s", line.rstrip("\n"))
        return_code = process.wait()
    if return_code != 0:
        raise BackupError(f"Команда завершилась с кодом {return_code}: {' '.join(cmd)}")
    return ""


@contextlib.contextmanager
def exclusive_lock(lockfile: Path) -> Iterator[None]:
    lockfile.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    with lockfile.open("a+") as fp:
        try:
            fcntl.flock(fp.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            raise BackupError("Другой экземпляр бэкапа уже выполняется") from exc
        fp.seek(0)
        fp.truncate()
        fp.write(str(os.getpid()) + "\n")
        fp.flush()
        try:
            yield
        finally:
            fcntl.flock(fp.fileno(), fcntl.LOCK_UN)
            # Do not unlink the lock: another process may already have it open.


def rclone_base(cfg: Dict[str, Any]) -> List[str]:
    return [cfg["rclone_bin"], "--config", str(cfg["rclone_config"])]


def restic_base(cfg: Dict[str, Any]) -> List[str]:
    return [cfg["restic_bin"]]


def assert_repository(cfg: Dict[str, Any]) -> None:
    if not (cfg["repository_dir"] / "config").is_file():
        raise BackupError("Нет инициализированного restic-репозитория: "
                          "выполните сначала команду init")
    # Verify password and repository accessibility *before* touching mirror.
    run_command(restic_base(cfg) + ["cat", "config"], restic_env(cfg), capture=True)


def assert_source_not_empty(cfg: Dict[str, Any]) -> None:
    cmd = rclone_base(cfg) + ["lsjson", cfg["onedrive_remote"], "--max-depth", "1"]
    content = run_command(cmd, capture=True)
    try:
        listing = json.loads(content)
    except ValueError as exc:
        raise BackupError("rclone lsjson вернул некорректный JSON") from exc
    if not isinstance(listing, list):
        raise BackupError("rclone lsjson вернул не список объектов")
    if not listing and not cfg["allow_empty_source"]:
        raise BackupError("OneDrive выглядит пустым — остановлено во избежание удаления "
                          "зеркала. При намеренном пустом облаке задайте allow_empty_source=true")
    LOG.info("Проверка источника: объектов на верхнем уровне: %d", len(listing))


def initialize(cfg: Dict[str, Any]) -> None:
    repo = cfg["repository_dir"]
    if repo.exists() and (repo / "config").exists():
        raise BackupError(f"Репозиторий уже инициализирован: {repo}")
    if repo.exists() and any(repo.iterdir()):
        raise BackupError(f"Каталог репозитория непустой: {repo}; не перезаписываю")
    repo.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    run_command(restic_base(cfg) + ["init"], restic_env(cfg))
    LOG.info("Репозиторий restic создан: %s", repo)


def backup(cfg: Dict[str, Any], dry_run: bool) -> None:
    assert_repository(cfg)
    assert_source_not_empty(cfg)
    mirror = cfg["mirror_dir"]
    if not dry_run:
        mirror.mkdir(parents=True, exist_ok=True, mode=0o700)

    command = rclone_base(cfg) + [
        "sync", cfg["onedrive_remote"], str(mirror),
        "--max-delete", str(cfg["max_delete"]),
        "--transfers", str(cfg["transfers"]),
        "--checkers", str(cfg["checkers"]),
        "--retries", "3", "--low-level-retries", "10",
        "--stats", "30s", "--stats-one-line", "--create-empty-src-dirs",
    ]
    if dry_run:
        command.append("--dry-run")
        LOG.warning("ТЕСТОВЫЙ ЗАПУСК: ни зеркало, ни restic не будут изменены")
    run_command(command)
    if dry_run:
        LOG.info("Тест завершён: при реальном запуске после rclone sync будет создан снимок restic")
        return

    # If rclone failed, never snapshot the partially updated mirror.
    run_command(restic_base(cfg) + ["backup", str(mirror), "--tag", "onedrive"],
                restic_env(cfg))
    LOG.info("Снимок restic создан успешно")
    run_command(restic_base(cfg) + [
        "forget", "--tag", "onedrive",
        "--keep-daily", str(cfg["keep_daily"]),
        "--keep-weekly", str(cfg["keep_weekly"]),
        "--keep-monthly", str(cfg["keep_monthly"]), "--prune",
    ], restic_env(cfg))
    LOG.info("Бэкап выполнен успешно")


def main() -> int:
    parser = argparse.ArgumentParser(description="Безопасное резервное копирование OneDrive на Linux-сервер")
    parser.add_argument("--config", required=True, type=Path, metavar="FILE",
                        help="Абсолютный путь к JSON-конфигурации")
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("init", help="Однократно создать зашифрованный репозиторий restic")
    backup_parser = commands.add_parser("backup", help="Синхронизация OneDrive и создание снимка")
    backup_parser.add_argument("--dry-run", action="store_true", help="Только проверить действия rclone")
    commands.add_parser("snapshots", help="Показать доступные снимки restic")
    commands.add_parser("check", help="Проверить целостность репозитория restic")
    args = parser.parse_args()

    configure_logging(None)  # Write to stdout even when disk is not mounted.
    try:
        cfg = load_config(args.config.expanduser().resolve())
        preflight(cfg)  # Must run before creating any log/lock files on backup storage.
        configure_logging(cfg["log_file"])
        with exclusive_lock(cfg["lock_file"]):
            if args.command == "init":
                initialize(cfg)
            elif args.command == "backup":
                backup(cfg, args.dry_run)
            elif args.command == "snapshots":
                assert_repository(cfg)
                run_command(restic_base(cfg) + ["snapshots", "--tag", "onedrive"],
                            restic_env(cfg))
            elif args.command == "check":
                assert_repository(cfg)
                run_command(restic_base(cfg) + ["check"], restic_env(cfg))
    except (BackupError, OSError) as exc:
        LOG.error("Бэкап не выполнен: %s", exc)
        return 1
    except KeyboardInterrupt:
        LOG.error("Остановлено пользователем")
        return 130
    return 0


if __name__ == "__main__":
    sys.exit(main())
