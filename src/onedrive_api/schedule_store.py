"""The schedule store: the file, its history, the change log, the atomic write and the fallback rules (10.20.2)."""

from __future__ import annotations

import fcntl
import json
import logging
import os
import threading
import time
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Callable, Iterator

from .schedule_cron import iso_utc
from .schedule_parse import DEFAULT_TEXT, ScheduleError, parse, revision

LOG = logging.getLogger("onedrive_backup")
HISTORY_KEEP = 50
LOCK_WAIT_SECONDS = 5.0


def _unavailable(details: str) -> ScheduleError:
    """Build the storage refusal.

    Args:
        details: What is wrong.

    Returns:
        The error 503 SCHEDULE_STORAGE_UNAVAILABLE.
    """
    message = "schedule storage unavailable: %s" % details
    return ScheduleError("SCHEDULE_STORAGE_UNAVAILABLE", 503, message, {"details": details})


class ScheduleStore:
    """The schedule directory of the service: schedule.cron, history/, changes.jsonl and the writer lock.

    Attributes:
        directory: The schedule directory.
        path: The live file.
        storage_ok: The storage guard, or None for always.
        zone: The default time zone of a text without TZ.
        held: The last valid parse this store has seen.
        _mutex: The thread lock of the writers.
        _logged: The revisions of invalid files already logged.
    """

    def __init__(self, directory: str | Path, storage_ok: Callable[[], bool] | None = None, zone: str | None = None) -> None:
        """Remember the directory and the guard; nothing is touched.

        Args:
            directory: The schedule directory, normally <data>/schedule.
            storage_ok: The storage guard G2; None means the storage is fine.
            zone: The default time zone; the service setting ONEDRIVE_UI_TIMEZONE when omitted.
        """
        self.directory = Path(directory)
        self.path = self.directory / "schedule.cron"
        self.storage_ok = storage_ok
        self.zone = zone or os.environ.get("ONEDRIVE_UI_TIMEZONE", "Europe/Kyiv")
        self.held: dict[str, Any] | None = None
        self._mutex = threading.Lock()
        self._logged: set[str] = set()

    def guard(self) -> bool:
        """Run the storage guard.

        Returns:
            True when the storage may be written.
        """
        return self.storage_ok is None or bool(self.storage_ok())

    def _parse(self, text: str) -> dict[str, Any]:
        """Parse a text with the default zone of this store.

        Args:
            text: The schedule text.

        Returns:
            The parse result.
        """
        return parse(text, datetime.now(UTC), self.zone)

    def _load(self) -> str | None:
        """Read the live file.

        Returns:
            The text as stored, or None."""
        try:
            return self.path.read_bytes().decode("utf-8", "replace")
        except FileNotFoundError:
            return None
        except OSError as exc:
            LOG.error("scheduler: schedule file unreadable: %s", exc)
            return None

    def _ensure_dir(self) -> None:
        """Create the schedule directory with mode 0700.

        Returns:
            None.

        Raises:
            ScheduleError: The directory cannot be created.
        """
        try:
            self.directory.mkdir(mode=0o700, parents=True, exist_ok=True)
        except OSError as exc:
            raise _unavailable(str(exc)) from exc

    @contextmanager
    def _locked(self) -> Iterator[None]:
        """Hold the writer lock (a thread mutex and flock on schedule.lock) for at most five seconds of waiting.

        Returns:
            A context manager; the lock is held inside its block.

        Raises:
            ScheduleError: The lock could not be taken in time.
        """
        if not self._mutex.acquire(timeout=LOCK_WAIT_SECONDS):
            raise _unavailable("lock busy")
        try:
            self._ensure_dir()
            try:
                handle = os.open(self.directory / "schedule.lock", os.O_RDWR | os.O_CREAT, 0o600)
            except OSError as exc:
                raise _unavailable(str(exc)) from exc
            try:
                deadline = time.monotonic() + LOCK_WAIT_SECONDS
                while True:
                    try:
                        fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
                        break
                    except BlockingIOError:
                        if time.monotonic() > deadline:
                            raise _unavailable("lock busy") from None
                        time.sleep(0.05)
                try:
                    yield
                finally:
                    fcntl.flock(handle, fcntl.LOCK_UN)
            finally:
                os.close(handle)
        finally:
            self._mutex.release()

    def _put(self, path: Path, text: str) -> None:
        """Write a file through a temporary file in the same directory, fsync it and replace the target.

        Args:
            path: The target file.
            text: The content.

        Returns:
            None.
        """
        temp = path.with_name(path.name + ".tmp-%d" % os.getpid())
        handle = os.open(temp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        try:
            with os.fdopen(handle, "wb") as stream:
                stream.write(text.encode("utf-8"))
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temp, path)
        except BaseException:
            temp.unlink(missing_ok=True)
            raise
        folder = os.open(path.parent, os.O_RDONLY)
        try:
            os.fsync(folder)
        finally:
            os.close(folder)

    def log_change(self, actor: str, before: str | None, after: str, parsed: dict[str, Any]) -> None:
        """Append one line to changes.jsonl; a failure is only logged.

        Args:
            actor: Who changed the schedule: a label, service or file.
            before: The previous revision, or None.
            after: The new revision.
            parsed: The parse result of the new text.

        Returns:
            None.
        """
        line = {
            "at": iso_utc(datetime.now(UTC)), "actor": actor, "from_revision": before, "to_revision": after,
            "entries": len(parsed["entries"]), "enabled": parsed["enabled"],
        }
        try:
            handle = os.open(self.directory / "changes.jsonl", os.O_WRONLY | os.O_APPEND | os.O_CREAT, 0o600)
            try:
                os.write(handle, (json.dumps(line) + "\n").encode("utf-8"))
            finally:
                os.close(handle)
        except OSError as exc:
            LOG.warning("scheduler: change log not written: %s", exc)

    def _create_default(self) -> None:
        """Write the default text when the file is missing (the lock is held by the caller).

        Returns:
            None.
        """
        if self.path.exists():
            return
        self._put(self.path, DEFAULT_TEXT)
        LOG.warning("scheduler: schedule file missing, default written")
        self.log_change("service", None, revision(DEFAULT_TEXT), self._parse(DEFAULT_TEXT))

    def bootstrap(self) -> bool:
        """Create the directory and the default file when absent, and take the stored schedule into memory.

        Returns:
            True when the storage is usable.
        """
        if not self.guard():
            return False
        try:
            with self._locked():
                self._create_default()
        except (ScheduleError, OSError) as exc:
            LOG.error("scheduler: schedule store not ready: %s", exc)
            return False
        self.read()
        return True

    def _history(self) -> list[Path]:
        """List the history files, newest first.

        Returns:
            The paths.
        """
        folder = self.directory / "history"
        if not folder.is_dir():
            return []
        return sorted(folder.glob("schedule.*.cron"), key=lambda item: item.stat().st_mtime_ns, reverse=True)

    def _fallback(self) -> tuple[dict[str, Any], str]:
        """Choose the effective schedule when the stored file is not valid.

        Returns:
            The parse result and its source: memory, history:<name> or default.
        """
        if self.held is not None:
            return self.held, "memory"
        for item in self._history():
            try:
                parsed = self._parse(item.read_bytes().decode("utf-8", "replace"))
            except OSError:
                continue
            if parsed["valid"]:
                return parsed, "history:" + item.name
        return self._parse(DEFAULT_TEXT), "default"

    def read(self, create_missing: bool = False) -> dict[str, Any]:
        """Read the schedule: the stored text, its state and the effective schedule.

        Args:
            create_missing: Write the default file when it is missing and the storage guard allows it.

        Returns:
            text, revision, exists, source, valid, problems and parsed (the effective schedule).
        """
        text = self._load()
        if text is None and create_missing and self.guard():
            try:
                with self._locked():
                    self._create_default()
            except (ScheduleError, OSError) as exc:
                LOG.error("scheduler: default schedule not written: %s", exc)
            text = self._load()
        if text is None:
            parsed = self._parse(DEFAULT_TEXT)
            return {
                "text": DEFAULT_TEXT, "revision": revision(DEFAULT_TEXT), "exists": False, "source": "default",
                "valid": True, "problems": [], "parsed": parsed,
            }
        stored = self._parse(text)
        number = revision(text)
        result: dict[str, Any] = {
            "text": text, "revision": number, "exists": True, "source": "file", "valid": stored["valid"],
            "problems": stored["problems"], "parsed": stored,
        }
        if stored["valid"]:
            self.held = stored
            return result
        if number not in self._logged:
            self._logged.add(number)
            LOG.error("scheduler: schedule file invalid (revision %s): %d problem(s)", number[:12], len(stored["problems"]))
        result["parsed"], result["source"] = self._fallback()
        return result

    def _copy_to_history(self, text: str) -> str:
        """Copy a text into history/ under schedule.<UTC time>.<8 hex>.cron with a strictly newer mtime.

        Args:
            text: The previous text.

        Returns:
            The file name.
        """
        folder = self.directory / "history"
        folder.mkdir(mode=0o700, exist_ok=True)
        name = "schedule.%s.%s.cron" % (datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ"), revision(text)[:8])
        handle = os.open(folder / name, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        try:
            os.write(handle, text.encode("utf-8"))
            os.fsync(handle)
        finally:
            os.close(handle)
        newest = max((item.stat().st_mtime_ns for item in folder.glob("schedule.*.cron") if item.name != name), default=0)
        stamp = max(time.time_ns(), newest + 1)
        os.utime(folder / name, ns=(stamp, stamp))
        return name

    def _prune(self) -> None:
        """Remove the oldest history files beyond the newest fifty; a version equal to the live file stays.

        Returns:
            None.
        """
        files = self._history()
        live = self.path.read_bytes() if self.path.exists() else None
        excess = len(files) - HISTORY_KEEP
        for item in reversed(files):
            if excess <= 0:
                break
            if live is not None and item.read_bytes() == live:
                continue
            item.unlink(missing_ok=True)
            excess -= 1

    def _answer(self, parsed: dict[str, Any], written: bool, changed: bool, previous: str | None, backup: str | None,
                dry_run: bool) -> dict[str, Any]:
        """Build the result of a write.

        Args:
            parsed: The parse result of the new text.
            written: True when the file was written.
            changed: True when the text differs from the stored one.
            previous: The revision before the call, or None.
            backup: The history file made, or None.
            dry_run: True for a check without a write.

        Returns:
            The result map.
        """
        return {"written": written, "changed": changed, "dry_run": dry_run, "revision": parsed["revision"],
                "previous_revision": previous, "backup_file": backup, "text": parsed["text"], "parsed": parsed}

    def write(self, text: str, *, expected_revision: str | None = None, dry_run: bool = False,
              actor: str = "unknown") -> dict[str, Any]:
        """Validate and store a new schedule text atomically (10.20.2).

        Args:
            text: The new text.
            expected_revision: The revision the caller read; a different current one is a conflict.
            dry_run: Validate only; nothing is written and expected_revision is ignored.
            actor: The label for the change log.

        Returns:
            written, changed, dry_run, revision, previous_revision, backup_file, text and parsed.

        Raises:
            ScheduleError: INVALID_SCHEDULE, SCHEDULE_STORAGE_UNAVAILABLE, SCHEDULE_CONFLICT or SCHEDULE_WRITE_FAILED.
        """
        parsed = self._parse(text)
        if not parsed["valid"]:
            raise ScheduleError("INVALID_SCHEDULE", 400, "invalid schedule", {"problems": parsed["problems"]})
        current = self._load()
        if dry_run:
            return self._answer(parsed, False, parsed["text"] != current, revision(current) if current is not None else None,
                                None, True)
        if not self.guard():
            raise _unavailable("the archive storage guard failed")
        with self._locked():
            current = self._load()
            shown = current if current is not None else DEFAULT_TEXT
            if expected_revision is not None and expected_revision != revision(shown):
                raise ScheduleError("SCHEDULE_CONFLICT", 409, "the schedule changed",
                                    {"current_revision": revision(shown), "current_text": shown})
            previous = revision(current) if current is not None else None
            if current is not None and current == parsed["text"]:
                return self._answer(parsed, False, False, previous, None, False)
            backup = None
            try:
                if current is not None:
                    backup = self._copy_to_history(current)
                self._put(self.path, parsed["text"])
            except OSError as exc:
                if backup is not None:
                    (self.directory / "history" / backup).unlink(missing_ok=True)
                raise ScheduleError("SCHEDULE_WRITE_FAILED", 500, "the schedule was not written: %s" % exc) from exc
            self._prune()
            self.log_change(actor, previous, parsed["revision"], parsed)
        self.held = parsed
        return self._answer(parsed, True, True, previous, backup, False)
