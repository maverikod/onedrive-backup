#!/usr/bin/env bash
# Thin convenience wrapper. Debian postinst performs deployment.
set -Eeuo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
VERSION="$(tr -d '[:space:]' < "$ROOT/VERSION")"
[[ "$(id -u)" == 0 ]] || { echo "deploy: root required" >&2; exit 2; }
# Debian postinst creates /etc/default on first install and preserves it later.
dpkg -i "$ROOT/dist/onedrive-backup_$VERSION""_all.deb"
