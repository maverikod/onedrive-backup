"""Process-level helpers of the scheduler: the storage guard, the lock probe, the leader lock and the state file."""

from __future__ import annotations

import fcntl
import json
import logging
import os
from pathlib import Path
from typing import Any

LOG = logging.getLogger("onedrive_backup")


def storage_guard(data_dir: Path) -> bool:
    """Check the archive storage guard G2: the data directory is writable and not on the state filesystem.

    Args:
        data_dir: The service data directory.

    Returns:
        True when the storage is usable.
    """
    try:
        data = os.stat(data_dir)
        state = Path(os.environ.get("ONEDRIVE_RCLONE_STATE", "/rclone-state"))
        if state.exists() and os.stat(state).st_dev == data.st_dev:
            return False
        return os.access(data_dir, os.W_OK)
    except OSError:
        return False


def probe_lock(data_dir: Path) -> bool:
    """Probe the backup lock without taking it.

    Args:
        data_dir: The service data directory.

    Returns:
        True when another process holds <data>/backup.lock.
    """
    try:
        handle = os.open(data_dir / "backup.lock", os.O_RDONLY)
    except FileNotFoundError:
        return False
    try:
        fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
        fcntl.flock(handle, fcntl.LOCK_UN)
        return False
    except BlockingIOError:
        return True
    finally:
        os.close(handle)


def take_leader(data_dir: Path) -> int | None:
    """Take the leader lock for the life of the process.

    Args:
        data_dir: The service data directory.

    Returns:
        The descriptor that holds the lock, or None when another process is the leader or the directory is unusable.
    """
    try:
        folder = data_dir / "schedule"
        folder.mkdir(mode=0o700, parents=True, exist_ok=True)
        handle = os.open(folder / "scheduler.lock", os.O_RDWR | os.O_CREAT, 0o600)
    except OSError:
        return None
    try:
        fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        os.close(handle)
        return None
    return handle


def load_state(data_dir: Path) -> dict[str, Any] | None:
    """Read the stored baseline state.

    Args:
        data_dir: The service data directory.

    Returns:
        The state with a baseline, or None when there is none.
    """
    try:
        stored = json.loads((data_dir / "schedule" / "state.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return stored if isinstance(stored, dict) and stored.get("baseline_utc") else None


def save_state(data_dir: Path, state: dict[str, Any]) -> None:
    """Store the baseline state atomically; a failure is only logged.

    Args:
        data_dir: The service data directory.
        state: The state.

    Returns:
        None.
    """
    path = data_dir / "schedule" / "state.json"
    body = {"schema": 1, "schedule_revision": state.get("schedule_revision"), "baseline_utc": state.get("baseline_utc")}
    temp = path.with_name(path.name + ".tmp-%d" % os.getpid())
    try:
        temp.write_text(json.dumps(body), encoding="utf-8")
        os.replace(temp, path)
    except OSError as exc:
        LOG.warning("scheduler: state not stored: %s", exc)
        temp.unlink(missing_ok=True)


def changes_tail(data_dir: Path) -> str:
    """Read the last lines of changes.jsonl.

    Args:
        data_dir: The service data directory.

    Returns:
        The text of the last five lines, empty when there is none.
    """
    try:
        lines = (data_dir / "schedule" / "changes.jsonl").read_text(encoding="utf-8").splitlines(True)
    except OSError:
        return ""
    return "".join(lines[-5:])
