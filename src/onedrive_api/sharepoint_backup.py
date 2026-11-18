"""Read-only multi-library SharePoint backup with stable mirror identities.

The source is Microsoft Graph/rclone (read-only). Each library receives its own
restic snapshot. Retention/prune is intentionally excluded until restore E2E.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import logging
import os
from pathlib import Path
import sys
from typing import Any

from onedrive_backup import (
    BackupError,
    assert_repository,
    configure_logging,
    exclusive_lock,
    load_config,
    preflight,
    rclone_base,
    restic_base,
    restic_env,
    run_command,
)

from .sharepoint_discover_cli import discover
from .sharepoint_discovery import DiscoveryError, IDENTIFIER

LOG = logging.getLogger("onedrive_backup")


def stable_key(value: str) -> str:
    """Compute a stable key from a SharePoint identifier.

    Args:
        value: Stable site or document library ID.

    Returns:
        Lowercase hexadecimal SHA-256 digest.
    """
    if not IDENTIFIER.fullmatch(value):
        raise BackupError("INVALID_SHAREPOINT_ID")
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def library_mirror(
    cfg: dict[str, Any], site_id: str, drive_id: str
) -> Path:
    """Return a directory unique to the site and library.

    Args:
        cfg: Validated backup configuration.
        site_id: Stable Graph site ID.
        drive_id: Stable document library drive ID.

    Returns:
        Absolute mirror directory derived from the two IDs.
    """
    root = cfg["mirror_dir"] / "sharepoint"
    return root / stable_key(site_id) / stable_key(drive_id)


def inventory_libraries(
    report: dict[str, Any]
) -> list[dict[str, str]]:
    """Validate the inventory before any sync operation.

    Args:
        report: Complete result of the current Graph scan.

    Returns:
        Validated library IDs in stable order.
    """
    if report.get("complete") is not True or report.get("errors"):
        raise BackupError("DISCOVERY_INCOMPLETE")
    sites = report.get("sites")
    libraries = report.get("libraries")
    if not isinstance(sites, list) or not isinstance(libraries, list):
        raise BackupError("DISCOVERY_INVALID")
    site_ids = set()
    for site in sites:
        if not isinstance(site, dict):
            raise BackupError("DISCOVERY_INVALID")
        identifier = site.get("site_id")
        if not isinstance(identifier, str):
            raise BackupError("DISCOVERY_INVALID")
        stable_key(identifier)
        if identifier in site_ids or site.get("source_status") != "ok":
            raise BackupError("DISCOVERY_INCOMPLETE")
        site_ids.add(identifier)
    result: list[dict[str, str]] = []
    seen = set()
    for library in libraries:
        if not isinstance(library, dict):
            raise BackupError("DISCOVERY_INVALID")
        site_id = library.get("site_id")
        drive_id = library.get("drive_id")
        if not isinstance(site_id, str) or not isinstance(drive_id, str):
            raise BackupError("DISCOVERY_INVALID")
        stable_key(site_id)
        stable_key(drive_id)
        if (site_id, drive_id) in seen or site_id not in site_ids:
            raise BackupError("DISCOVERY_INVALID")
        if library.get("status") != "ok":
            raise BackupError("DISCOVERY_INCOMPLETE")
        seen.add((site_id, drive_id))
        result.append({"site_id": site_id, "drive_id": drive_id})
    if not result:
        raise BackupError("NO_DOCUMENT_LIBRARIES")
    return sorted(result, key=lambda row: (row["site_id"], row["drive_id"]))


def library_rclone(
    cfg: dict[str, Any], drive_id: str
) -> list[str]:
    """Select one Graph-discovered document library in rclone.

    Args:
        cfg: Validated local backup configuration.
        drive_id: Stable Graph drive identifier.

    Returns:
        rclone base arguments with a fixed drive selection.
    """
    stable_key(drive_id)
    if cfg["onedrive_remote"] != "onedrive:":
        raise BackupError("SHAREPOINT_REMOTE_MUST_BE_ROOT")
    return rclone_base(cfg) + [
        "--onedrive-drive-id", drive_id,
        "--onedrive-drive-type", "documentLibrary",
    ]


def check_library_source(
    cfg: dict[str, Any], drive_id: str
) -> None:
    """Reject an unexpectedly empty or malformed remote root.

    Args:
        cfg: Validated local backup configuration.
        drive_id: Stable Graph drive identifier.

    Returns:
        None. Raises BackupError for an unsafe source.
    """
    cmd = library_rclone(cfg, drive_id) + [
        "lsjson", "onedrive:", "--max-depth", "1"
    ]
    value = run_command(cmd, capture=True)
    try:
        entries = json.loads(value)
    except ValueError as exc:
        raise BackupError("SHAREPOINT_SOURCE_INVALID_JSON") from exc
    if not isinstance(entries, list):
        raise BackupError("SHAREPOINT_SOURCE_INVALID")
    if not entries and not cfg["allow_empty_source"]:
        raise BackupError("SHAREPOINT_LIBRARY_EMPTY")


def backup_libraries(
    cfg: dict[str, Any], report: dict[str, Any], *,
    dry_run: bool
) -> int:
    """Sync and snapshot each library; never prune on partial failures.

    Args:
        cfg: Validated local backup configuration.
        report: Discovery result from the current Graph scan.
        dry_run: When true, verify and print planned sync operations only.

    Returns:
        Number of libraries successfully processed.
    """
    libraries = inventory_libraries(report)
    assert_repository(cfg)
    count = 0
    for library in libraries:
        site_id = library["site_id"]
        drive_id = library["drive_id"]
        target = library_mirror(cfg, site_id, drive_id)
        LOG.info("Library %d/%d site_id=%s drive_id=%s",
                 count + 1, len(libraries), site_id, drive_id)
        check_library_source(cfg, drive_id)
        if not dry_run:
            target.mkdir(mode=0o700, parents=True, exist_ok=True)
        command = library_rclone(cfg, drive_id) + [
            "sync", "onedrive:", str(target),
            "--max-delete", str(cfg["max_delete"]),
            "--transfers", str(cfg["transfers"]),
            "--checkers", str(cfg["checkers"]),
            "--retries", "3", "--low-level-retries", "10",
            "--create-empty-src-dirs",
        ]
        if dry_run:
            command.append("--dry-run")
        run_command(command)
        if not dry_run:
            run_command(restic_base(cfg) + [
                "backup", str(target), "--tag", "sharepoint",
                "--tag", "site-" + stable_key(site_id),
                "--tag", "drive-" + stable_key(drive_id),
            ], restic_env(cfg))
        count += 1
    LOG.info("SharePoint libraries processed: %d/%d; dry_run=%s",
             count, len(libraries), dry_run)
    return count


def main(argv: list[str] | None = None) -> int:
    """Run discovery and a backup cycle under a global mutex.

    Args:
        argv: Optional CLI arguments for testing.

    Returns:
        Process exit status, zero only for a complete success.
    """
    parser = argparse.ArgumentParser(
        description="Read-only SharePoint document library backup"
    )
    parser.add_argument(
        "--config", type=Path,
        default=Path("/config/backup.json"),
    )
    parser.add_argument("--data", type=Path, default=Path("/data"))
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args(argv)
    configure_logging(None)
    try:
        if os.environ.get("ONEDRIVE_SCAFFOLD_MODE") == "1":
            raise BackupError("SCAFFOLD_ONLY")
        if not args.data.is_dir() or not args.data.is_mount():
            raise BackupError("STORAGE_NOT_MOUNTED")
        cfg = load_config(args.config)
        preflight(cfg)
        if cfg["required_mountpoint"] != args.data.resolve():
            raise BackupError("STORAGE_MOUNT_MISMATCH")
        with exclusive_lock(cfg["lock_file"]):
            assert_repository(cfg)
            report = discover(args.config, args.data, dry_run=args.dry_run)
            backup_libraries(cfg, report, dry_run=args.dry_run)
    except (BackupError, DiscoveryError, OSError) as exc:
        code = exc.code if isinstance(exc, DiscoveryError) else str(exc)
        LOG.error("SharePoint backup refused: %s", code)
        return 2
    except KeyboardInterrupt:
        LOG.error("SharePoint backup interrupted")
        return 130
    return 0


if __name__ == "__main__":
    sys.exit(main())
