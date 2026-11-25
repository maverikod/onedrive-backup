"""Entry point of the backup run: the SharePoint backup cycle, then the indexing of the snapshots it made (10.19.6, PL14).

The index is derived data. Its failure is logged as one ERROR line and never changes the exit status of the backup run.
"""

from __future__ import annotations

import logging
import os
import sys

from . import sharepoint_backup
from .run_log import close_run_log, end_reason, freeze, open_run_log
from .run_records import RunRecorder
from .catalog import Catalog
from .file_index import FileIndex
from .file_index_build import index_pending

LOG = logging.getLogger("onedrive_backup")


def index_new_snapshots() -> None:
    """Index every snapshot that the file name index does not know yet; never raises.

    Returns:
        None.
    """
    try:
        data = os.environ.get("ONEDRIVE_BACKUP_DATA", "/data")
        catalog = Catalog(os.environ.get("ONEDRIVE_BACKUP_CONFIG", "/config/backup.json"), data)
        done, failed = index_pending(catalog, FileIndex(data))
        LOG.info("File index: %d snapshot(s) indexed, %d failed", done, failed)
    except Exception as exc:  # noqa: BLE001 - derived data must not fail the backup
        LOG.error("File index failed: %s", exc)


def main(argv: list[str] | None = None) -> int:
    """Run the SharePoint backup with its run records, then index its snapshots unless it was a dry run.

    Every start writes a start record and, in a finally, an end record to <data>/schedule/runs.jsonl (10.20.5). The run
    log <data>/schedule/logs/<run_id>.log keeps the log lines of the run; a non-zero end record carries its reason.

    Args:
        argv: Optional CLI arguments of the backup.

    Returns:
        The exit status of the backup, unchanged.
    """
    arguments = sys.argv[1:] if argv is None else argv
    dry_run = "--dry-run" in arguments
    data_dir = os.environ.get("ONEDRIVE_BACKUP_DATA", "/data")
    recorder = RunRecorder(data_dir)
    run_id = recorder.start(dry_run)
    os.environ["ONEDRIVE_RUN_ID"] = run_id
    sharepoint_backup.configure_logging(None)
    handler = open_run_log(data_dir, run_id)
    code = 1
    try:
        code = sharepoint_backup.main(argv)
        freeze(handler)
        if not dry_run and code in (0, 1):
            index_new_snapshots()
        return code
    except Exception as exc:
        LOG.error("unexpected: %s: %s", type(exc).__name__, exc, exc_info=True)
        raise
    finally:
        recorder.end(run_id, code, end_reason(handler, code))
        close_run_log(handler)


if __name__ == "__main__":
    sys.exit(main())
