"""Console interface covering all backup REST endpoints."""

from __future__ import annotations

import argparse
import json
import ssl
from pathlib import Path
import sys

from .api import BackupClient, ClientError


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="onedrive-backup-client")
    parser.add_argument("--config",
                        default=str(Path.home() / ".config/onedrive-backup/client.json"))
    cmds = parser.add_subparsers(dest="command", required=True)
    cmds.add_parser("health")
    snaps = cmds.add_parser("snapshots")
    snaps.add_argument("--limit", type=int, default=100)
    files = cmds.add_parser("files")
    files.add_argument("snapshot_id")
    files.add_argument("--prefix", default="")
    files.add_argument("--limit", type=int, default=1000)
    files.add_argument("--offset", type=int, default=0)
    prepare = cmds.add_parser("prepare")
    prepare.add_argument("snapshot_id")
    prepare.add_argument("--path")
    status = cmds.add_parser("status")
    status.add_argument("export_id")
    delete = cmds.add_parser("delete")
    delete.add_argument("export_id")
    fetch = cmds.add_parser("fetch")
    fetch.add_argument("export_id")
    fetch.add_argument("--output", required=True)
    fetch.add_argument("--force", action="store_true")
    download = cmds.add_parser("download")
    download.add_argument("snapshot_id")
    download.add_argument("--path")
    download.add_argument("--output", required=True)
    download.add_argument("--force", action="store_true")
    args = parser.parse_args(argv)
    try:
        config = json.loads(Path(args.config).expanduser().read_text(encoding="utf-8"))
        client = BackupClient(
            url=config["url"], ca=config["ca"],
            cert=config["cert"], key=config["key"], timeout=config.get("timeout", 180),
        )
        if args.command == "health":
            result = client.health()
        elif args.command == "snapshots":
            result = client.snapshots(args.limit)
        elif args.command == "files":
            result = client.files(args.snapshot_id, args.prefix, args.offset, args.limit)
        elif args.command == "prepare":
            result = client.prepare(args.snapshot_id, args.path)
        elif args.command == "status":
            result = client.status(args.export_id)
        elif args.command == "delete":
            result = client.delete(args.export_id)
        elif args.command == "fetch":
            result = {"saved": str(client.fetch(args.export_id, args.output,
                                                  overwrite=args.force))}
        else:
            result = {"saved": str(client.download(
                args.snapshot_id, args.output, file_path=args.path,
                overwrite=args.force))}
        print(json.dumps(result, indent=2, ensure_ascii=False))
        return 0
    except (ClientError, OSError, KeyError, ValueError, ssl.SSLError) as exc:
        print("onedrive-backup-client: " + str(exc), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())

