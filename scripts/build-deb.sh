#!/usr/bin/env bash
set -Eeuo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
VERSION="$(tr -d ' \r\n' < "$ROOT/VERSION")"
if ! [[ "$VERSION" =~ ^[0-9]+\.[0-9]+\.[0-9]+([+~.-][a-zA-Z0-9.]+)?$ ]]; then
  echo "Invalid version in VERSION" >&2; exit 2
fi
for tool in dpkg-deb install mktemp; do command -v "$tool" >/dev/null || { echo "Missing: $tool" >&2; exit 2; }; done
BUILD="$(mktemp -d)"
trap 'rm -rf "$BUILD"' EXIT
STAGE="$BUILD/onedrive-backup"
DEST="$ROOT/dist/onedrive-backup_${VERSION}_all.deb"
install -d -m 0755 "$STAGE/DEBIAN" "$STAGE/usr/bin" "$STAGE/usr/lib/onedrive-backup" \
 "$STAGE/etc/onedrive-backup" "$STAGE/lib/systemd/system" \
 "$STAGE/usr/share/doc/onedrive-backup" "$STAGE/usr/share/man/man8"
install -m 0755 "$ROOT/src/onedrive_backup.py" "$STAGE/usr/lib/onedrive-backup/onedrive_backup.py"
install -m 0755 "$ROOT/packaging/onedrive-backup" "$STAGE/usr/bin/onedrive-backup"
install -m 0644 "$ROOT/packaging/config.json" "$STAGE/etc/onedrive-backup/config.json"
install -m 0644 "$ROOT/packaging/onedrive-backup.service" "$STAGE/lib/systemd/system/onedrive-backup.service"
install -m 0644 "$ROOT/packaging/onedrive-backup.timer" "$STAGE/lib/systemd/system/onedrive-backup.timer"
install -m 0644 "$ROOT/README.md" "$STAGE/usr/share/doc/onedrive-backup/README.md"
install -m 0644 "$ROOT/LICENSE" "$STAGE/usr/share/doc/onedrive-backup/copyright"
install -m 0644 "$ROOT/CHANGELOG.md" "$STAGE/usr/share/doc/onedrive-backup/CHANGELOG.md"
install -m 0644 "$ROOT/packaging/onedrive-backup.8" "$STAGE/usr/share/man/man8/onedrive-backup.8"
gzip -n -9 "$STAGE/usr/share/man/man8/onedrive-backup.8"
for script in postinst prerm postrm; do install -m 0755 "$ROOT/packaging/$script" "$STAGE/DEBIAN/$script"; done
printf '/etc/onedrive-backup/config.json\n' > "$STAGE/DEBIAN/conffiles"
cat > "$STAGE/DEBIAN/control" <<EOF_CONTROL
Package: onedrive-backup
Version: $VERSION
Section: admin
Priority: optional
Architecture: all
Maintainer: OneDrive Backup maintainers <maintainers@example.org>
Depends: python3 (>= 3.9), rclone, restic, adduser
Description: Encrypted and versioned backup of Microsoft OneDrive Business
 Downloads OneDrive files to a local read-only-source mirror using rclone,
 then stores encrypted versioned snapshots using restic. Installs a
 systemd service, a disabled-by-default daily timer and safety checks.
EOF_CONTROL
mkdir -p "$ROOT/dist"
dpkg-deb --build --root-owner-group "$STAGE" "$DEST"
sha256sum "$DEST" | tee "$DEST.sha256"
dpkg-deb --info "$DEST"
echo "Built: $DEST"
