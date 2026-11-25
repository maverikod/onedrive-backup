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
from .sharepoint_dupnames import EXCLUDE_PATTERN, scan_library
from .sharepoint_duplicates import empty_record, keep_duplicates

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
) -> bool:
    """Read the remote root and report whether it lists any entry.

    Args:
        cfg: Validated local backup configuration.
        drive_id: Stable Graph drive identifier.

    Returns:
        True when the root lists at least one entry, False for an empty root.
        Raises BackupError for a malformed source answer.
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
    return bool(entries)


def library_has_backup(target: Path) -> bool:
    """Tell whether the library was synced and snapshotted before.

    A mirror is created only by a completed sync that is followed by a
    snapshot, so a mirror that holds entries marks a library with history.

    Args:
        target: Mirror directory of the library.

    Returns:
        True when the mirror directory exists and is not empty.
    """
    return target.is_dir() and any(target.iterdir())


def sync_library(
    cfg: dict[str, Any], site_id: str, drive_id: str, target: Path, *,
    dry_run: bool
) -> dict[str, Any]:
    """Scan, sync, keep the duplicate copies and snapshot one library.

    Order: read-only scan, rclone sync (which never deletes a stored copy),
    fetch of every extra of a collision group, restic backup of the mirror.

    Args:
        cfg: Validated local backup configuration.
        site_id: Stable Graph site ID.
        drive_id: Stable document library drive ID.
        target: Mirror directory of the library.
        dry_run: When true, only plan the sync and change nothing.

    Returns:
        Run record fields of the library: outcome "ok" or
        "duplicate_incomplete", error (first error code or None),
        duplicates and duplicate_summary. Raises BackupError when rclone or
        restic fails.
    """
    base = library_rclone(cfg, drive_id)
    scan = scan_library(run_command, base)
    if not dry_run:
        target.mkdir(mode=0o700, parents=True, exist_ok=True)
    command = base + [
        "sync", "onedrive:", str(target),
        "--max-delete", str(cfg["max_delete"]),
        "--transfers", str(cfg["transfers"]),
        "--checkers", str(cfg["checkers"]),
        "--retries", "3", "--low-level-retries", "10",
        "--create-empty-src-dirs", "--exclude", EXCLUDE_PATTERN,
    ]
    if dry_run:
        command.append("--dry-run")
    run_command(command)
    record = keep_duplicates(cfg, run_command, drive_id, target, scan,
                             dry_run=dry_run)
    errors = record.pop("errors")
    record["outcome"] = "duplicate_incomplete" if errors else "ok"
    record["error"] = errors[0] if errors else None
    if not dry_run:
        run_command(restic_base(cfg) + [
            "backup", str(target), "--tag", "sharepoint",
            "--tag", "site-" + stable_key(site_id),
            "--tag", "drive-" + stable_key(drive_id),
        ], restic_env(cfg))
    return record


def backup_libraries(
    cfg: dict[str, Any], report: dict[str, Any], *,
    dry_run: bool
) -> dict[str, Any]:
    """Sync and snapshot each library; never prune on partial failures.

    An empty library that was never backed up is skipped (outcome "empty").
    A library that has a mirror but is now empty is not synced, so the mirror
    and the snapshots stay intact, and an error is recorded (outcome
    "source_emptied"). Colliding files are all kept (see sync_library); a
    library whose extra copy could not be stored with verified integrity gets
    outcome "duplicate_incomplete", which is an error library. Neither case
    stops the run. Any other failure still raises BackupError.
    allow_empty_source=true syncs an empty source as before, under the
    unchanged max_delete protection.

    Args:
        cfg: Validated local backup configuration.
        report: Discovery result from the current Graph scan.
        dry_run: When true, verify and print planned sync operations only.

    Returns:
        Run record {"status": "ok" | "partial" | "failed", "libraries":
        [{"site_id", "drive_id", "outcome": "ok" | "empty" |
        "source_emptied" | "duplicate_incomplete", "error": None | code,
        "duplicates": [...], "duplicate_summary": {...}}]}. The status is
        "ok" when no library recorded an error (kept and verified duplicates
        are no error, they are listed and logged as warnings), "partial" when
        an error and a handled library coexist, "failed" when every library
        recorded an error.
    """
    libraries = inventory_libraries(report)
    assert_repository(cfg)
    results: list[dict[str, Any]] = []
    for number, library in enumerate(libraries, 1):
        site_id = library["site_id"]
        drive_id = library["drive_id"]
        target = library_mirror(cfg, site_id, drive_id)
        LOG.info("Library %d/%d site_id=%s drive_id=%s",
                 number, len(libraries), site_id, drive_id)
        row: dict[str, Any] = {"site_id": site_id, "drive_id": drive_id,
                               "outcome": "ok", "error": None}
        row.update(empty_record())
        if not check_library_source(cfg, drive_id) \
                and not cfg["allow_empty_source"]:
            if library_has_backup(target):
                row["outcome"] = "source_emptied"
                row["error"] = "SHAREPOINT_LIBRARY_EMPTY"
                LOG.error("Library site_id=%s drive_id=%s is empty but has "
                          "a backup; not synced, mirror and snapshots kept: "
                          "%s", site_id, drive_id, row["error"])
            else:
                row["outcome"] = "empty"
                LOG.info("Library site_id=%s drive_id=%s is empty and was "
                         "never backed up; skipped", site_id, drive_id)
        if row["outcome"] == "ok":
            try:
                row.update(sync_library(cfg, site_id, drive_id, target, dry_run=dry_run))
            except (BackupError, OSError) as exc:
                row["outcome"] = "failed"
                row["error"] = "LIBRARY_COMMAND_FAILED"
                row["detail"] = str(exc)
                LOG.error("library site_id=%s drive_id=%s failed: %s", site_id, drive_id, exc)
        results.append(row)
    failed = sum(1 for row in results if row["error"])
    status = "ok" if not failed else (
        "failed" if failed == len(results) else "partial")
    LOG.info("SharePoint libraries handled: %d/%d, errors=%d, status=%s; "
             "dry_run=%s", len(results) - failed, len(results), failed,
             status, dry_run)
    names = {
        str(item.get("drive_id")): str(item.get("display_name") or item.get("name") or "") for item in report["libraries"]
    }
    failures = [
        "%s (%s): %s" % (names.get(row["drive_id"]) or row["drive_id"], row["drive_id"], row.get("detail") or row["error"])
        for row in results
        if row["error"]
    ]
    record: dict[str, Any] = {"status": status, "libraries": results}
    if failures:
        record["failures"] = failures
    return record


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
    phase = "guard"
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
            phase = "discovery"
            report = discover(args.config, args.data, dry_run=args.dry_run)
            record = backup_libraries(cfg, report, dry_run=args.dry_run)
            if record["status"] != "ok":
                detail = "; ".join(record.get("failures") or []) or "a library recorded an error"
                LOG.error("library: SharePoint backup finished with errors (%s): %s", record["status"], detail)
                return 1
    except (BackupError, DiscoveryError, OSError) as exc:
        code = exc.code if isinstance(exc, DiscoveryError) else str(exc)
        refused = phase == "guard"
        LOG.error("%s: SharePoint backup %s: %s", phase, "refused" if refused else "stopped", code)
        return 2 if refused else 1
    except KeyboardInterrupt:
        LOG.error("SharePoint backup interrupted")
        return 130
    return 0


if __name__ == "__main__":
    sys.exit(main())
