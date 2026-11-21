"""Entry point of the backup run: the SharePoint backup cycle, then the indexing of the snapshots it made (10.19.6, PL14).

The index is derived data. Its failure is logged as one ERROR line and never changes the exit status of the backup run.
"""

from __future__ import annotations

import logging
import os
import sys

from . import sharepoint_backup
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
    """Run the SharePoint backup, then index its snapshots unless it was a dry run or was refused.

    Args:
        argv: Optional CLI arguments of the backup.

    Returns:
        The exit status of the backup, unchanged.
    """
    code = sharepoint_backup.main(argv)
    arguments = sys.argv[1:] if argv is None else argv
    if "--dry-run" not in arguments and code in (0, 1):
        index_new_snapshots()
    return code


if __name__ == "__main__":
    sys.exit(main())
