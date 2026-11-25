"""Persistent run log of one backup run and the bounded reason of its non-zero exit (matrix row PL20, RL1-RL5).

Every backup run writes <data>/schedule/logs/<run_id>.log (mode 0600, rotated at 10 MiB with one rotated sibling) beside
runs.jsonl on the data volume, so the cause of a failed scheduled run survives the recreation of the container. The
newest 500 run ids are kept. The end record of runs.jsonl carries a secret-scrubbed reason of at most 500 characters when
the exit code is not zero. The run log is internal: no command, parameter, result field or exit code depends on it.
"""

from __future__ import annotations

import logging
import os
import re
import sys
from io import TextIOWrapper
from logging.handlers import RotatingFileHandler
from pathlib import Path

LOG = logging.getLogger("onedrive_backup")
KEEP_LOGS = 500
MAX_REASON = 500
MAX_LOG_BYTES = 10 * 1024 * 1024
FILE_MODE = 0o600
DIR_MODE = 0o700
NAME = re.compile(r"^([0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12})\.log(\.[0-9]+)?$")
SECRET = re.compile(
    r"(?i)\b([\w.-]*(?:token|secret|passw(?:or)?d|api[_-]?key|authorization|credential)[\w.-]*)"
    r"(\s*[=:]\s*)(\"[^\"]*\"|'[^']*'|\S+)"
)
BEARER = re.compile(r"(?i)\b(bearer|basic)\s+[A-Za-z0-9._~+/=-]{8,}")


def scrub(text: str) -> str:
    """Replace the value of every secret-looking key=value pair and every bearer credential by three asterisks.

    Args:
        text: A log line or an error text.

    Returns:
        The text without secret values.
    """
    hidden = BEARER.sub(lambda found: found.group(1) + " ***", text)
    return SECRET.sub(lambda found: found.group(1) + found.group(2) + "***", hidden)


def bounded(text: str, limit: int = MAX_REASON) -> str:
    """Put a text on one line and cut it to at most limit characters.

    Args:
        text: The text.
        limit: The longest result.

    Returns:
        The one-line text, ending with three dots when it was cut.
    """
    line = " ".join(text.split())
    return line if len(line) <= limit else line[: limit - 3] + "..."


def logs_dir(data_dir: str | Path) -> Path:
    """Return the run log directory of a data directory.

    Args:
        data_dir: The service data directory.

    Returns:
        <data>/schedule/logs.
    """
    return Path(data_dir) / "schedule" / "logs"


def make_logs_dir(data_dir: str | Path) -> bool:
    """Create the run log directory with mode 0700; a failure is one WARNING and never an exception.

    Args:
        data_dir: The service data directory.

    Returns:
        True when the directory exists afterwards.
    """
    folder = logs_dir(data_dir)
    try:
        created = not folder.is_dir()
        folder.mkdir(mode=DIR_MODE, parents=True, exist_ok=True)
        if created:
            folder.chmod(DIR_MODE)
        return True
    except OSError as exc:
        LOG.warning("run log: directory %s not ready: %s", folder, exc)
        return False


def ensure_logs_dir(data_dir: str | Path) -> bool:
    """Create the run log directory at the start of the service, so that it exists before the first run (RL5).

    Args:
        data_dir: The service data directory.

    Returns:
        True when the directory exists afterwards; False in scaffold mode or on a failure.
    """
    if os.environ.get("ONEDRIVE_SCAFFOLD_MODE") == "1":
        return False
    return make_logs_dir(data_dir)


def prune(folder: Path, keep: int = KEEP_LOGS) -> int:
    """Remove the files of the oldest run ids so that at most keep run ids remain (oldest by modification time).

    Args:
        folder: The run log directory.
        keep: The number of run ids to keep.

    Returns:
        The number of files removed.
    """
    try:
        entries = list(folder.iterdir())
    except OSError:
        return 0
    files: dict[str, list[Path]] = {}
    newest: dict[str, float] = {}
    for path in entries:
        match = NAME.match(path.name)
        if match is None:
            continue
        try:
            stamp = path.stat().st_mtime
        except OSError:
            continue
        run = match.group(1)
        files.setdefault(run, []).append(path)
        newest[run] = max(newest.get(run, 0.0), stamp)
    doomed = sorted(files, key=lambda run: (newest[run], run))[: max(len(files) - keep, 0)]
    removed = 0
    for run in doomed:
        for path in files[run]:
            try:
                path.unlink()
                removed += 1
            except OSError:
                continue
    return removed


def reason_of(record: logging.LogRecord) -> str:
    """Build the reason text of one ERROR record: the class of the exception being handled, then the message.

    Args:
        record: The log record.

    Returns:
        The scrubbed one-line text of at most 500 characters.
    """
    error = record.exc_info[1] if record.exc_info else None
    error = error or sys.exc_info()[1]
    text = record.getMessage()
    if error is not None and not text.startswith(("guard", "discovery", "library", "unexpected")):
        text = "%s: %s" % (type(error).__name__, text)
    return bounded(scrub(text))


class RunLogHandler(RotatingFileHandler):
    """The file handler of one run: mode 0600, secret-scrubbed lines, the last ERROR kept as the reason of the run.

    Attributes:
        reason: The scrubbed text of the last ERROR record before freeze(), or None.
        frozen: True after freeze(); later ERROR records no longer change the reason.
    """

    def __init__(self, path: Path) -> None:
        """Open the run log of one run id.

        Args:
            path: The <run_id>.log file.
        """
        super().__init__(path, maxBytes=MAX_LOG_BYTES, backupCount=1, encoding="utf-8")
        self.reason: str | None = None
        self.frozen = False
        self.setLevel(logging.INFO)
        self.setFormatter(logging.Formatter("%(asctime)s %(levelname)-7s %(message)s"))

    def _open(self) -> TextIOWrapper:
        """Create the file with mode 0600 before opening it, also after a rotation.

        Returns:
            The open stream.
        """
        os.close(os.open(self.baseFilename, os.O_WRONLY | os.O_APPEND | os.O_CREAT, FILE_MODE))
        return super()._open()

    def format(self, record: logging.LogRecord) -> str:
        """Format a record and scrub the secrets out of it, the traceback included.

        Args:
            record: The log record.

        Returns:
            The scrubbed line.
        """
        return scrub(super().format(record))

    def emit(self, record: logging.LogRecord) -> None:
        """Remember an ERROR record as the reason of the run, then write it.

        Args:
            record: The log record.

        Returns:
            None.
        """
        if record.levelno >= logging.ERROR and not self.frozen:
            try:
                self.reason = reason_of(record)
            except Exception:  # noqa: BLE001 - a broken record must not stop the run
                self.reason = None
        super().emit(record)


def open_run_log(data_dir: str | Path, run_id: str) -> RunLogHandler | None:
    """Attach the run log of this run to the backup logger and prune the old logs; never raises.

    Args:
        data_dir: The service data directory.
        run_id: The run id of the start record.

    Returns:
        The handler, or None when the log could not be opened (one WARNING).
    """
    if not make_logs_dir(data_dir):
        return None
    folder = logs_dir(data_dir)
    try:
        handler = RunLogHandler(folder / ("%s.log" % run_id))
    except OSError as exc:
        LOG.warning("run log: %s not opened: %s", folder, exc)
        return None
    LOG.addHandler(handler)
    prune(folder)
    return handler


def close_run_log(handler: RunLogHandler | None) -> None:
    """Detach and close the run log of the run.

    Args:
        handler: The handler returned by open_run_log, or None.

    Returns:
        None.
    """
    if handler is not None:
        LOG.removeHandler(handler)
        handler.close()


def freeze(handler: RunLogHandler | None) -> None:
    """Stop later ERROR records (the file index step after the backup) from replacing the reason of the run.

    Args:
        handler: The handler returned by open_run_log, or None.

    Returns:
        None.
    """
    if handler is not None:
        handler.frozen = True


def end_reason(handler: RunLogHandler | None, exit_code: int) -> str | None:
    """Return the reason for the end record of a run: None for exit code 0, else a bounded text.

    Args:
        handler: The handler returned by open_run_log, or None.
        exit_code: The exit code of the run.

    Returns:
        None for a successful run; the last logged error, or a fixed text when none was logged.
    """
    if exit_code == 0:
        return None
    if handler is not None and handler.reason:
        return handler.reason
    return "exit code %d without a logged error" % exit_code
