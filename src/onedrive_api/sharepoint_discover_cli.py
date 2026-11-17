"""Private operator CLI for SharePoint Online Graph discovery.

Usage inside a configured mTLS service container:
python -m onedrive_api.sharepoint_discover_cli
"""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import sys
from typing import Any

from .sharepoint_discovery import (
    DiscoveryError,
    EntraCredentials,
    GraphClient,
    SharePointDiscovery,
    SharePointInventory,
)


def discover(
    config_path: str | Path, data_directory: str | Path,
    *, dry_run: bool = False
) -> dict[str, Any]:
    """Refresh SharePoint inventory without modifying source libraries.

    Args:
        config_path: Absolute backup.json path from the container.
        data_directory: Mounted backup data directory.
        dry_run: If true, never persist discovery results.

    Returns:
        Full or explicitly incomplete inventory report.
    """
    if os.environ.get("ONEDRIVE_SCAFFOLD_MODE") == "1":
        raise DiscoveryError("SCAFFOLD_ONLY")
    data_dir = Path(data_directory)
    if not data_dir.is_mount() or not data_dir.is_dir():
        raise DiscoveryError("STORAGE_NOT_MOUNTED")
    try:
        config = json.loads(Path(config_path).read_text(encoding="utf-8"))
    except (ValueError, OSError) as exc:
        raise DiscoveryError("BACKUP_CONFIG_NOT_AVAILABLE") from exc
    if not isinstance(config, dict):
        raise DiscoveryError("BACKUP_CONFIG_INVALID")
    secret_path = config.get("rclone_config")
    if not isinstance(secret_path, str):
        raise DiscoveryError("RCLONE_CONFIG_PATH_INVALID")
    conf = Path(secret_path)
    if not conf.is_absolute() or not conf.is_relative_to("/secrets"):
        raise DiscoveryError("RCLONE_CONFIG_PATH_UNSAFE")
    credentials = EntraCredentials.from_rclone(conf)
    graph = GraphClient(credentials)
    report = SharePointDiscovery(graph).scan()
    if not dry_run:
        SharePointInventory(data_dir / "sharepoint").record(report)
    return report


def main(argv: list[str] | None = None) -> int:
    """Run a restricted Graph inventory command for local operators.

    Args:
        argv: Optional command-line argument list.

    Returns:
        Exit code: zero when complete, nonzero on partial/error.
    """
    parser = argparse.ArgumentParser(
        description="Read-only SharePoint library discovery"
    )
    parser.add_argument(
        "--backup-config", default="/config/backup.json"
    )
    parser.add_argument("--data", default="/data")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args(argv)
    try:
        report = discover(
            args.backup_config, args.data, dry_run=args.dry_run
        )
    except DiscoveryError as exc:
        print(
            json.dumps({"complete": False, "error": exc.code}),
            file=sys.stderr,
        )
        return 2
    summary = {
        "complete": report["complete"],
        "checked_at": report["checked_at"],
        "coverage": report["coverage"],
        "errors": report["errors"],
    }
    print(json.dumps(summary, ensure_ascii=False))
    return 0 if report["complete"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
