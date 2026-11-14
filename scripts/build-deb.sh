#!/usr/bin/env bash
# Build the host install package for the production Docker image.
set -Eeuo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
VERSION="$(tr -d ' \r\n' < "$ROOT/VERSION")"
[[ "$VERSION" =~ ^[0-9]+\.[0-9]+\.[0-9]+([+~.-][a-zA-Z0-9.]+)?$ ]] || {
  echo "Invalid version: $VERSION" >&2; exit 2;
}
command -v dpkg-deb >/dev/null || { echo "dpkg-deb missing" >&2; exit 2; }
export SOURCE_DATE_EPOCH="${SOURCE_DATE_EPOCH:-1794614400}"
STAGING="$(mktemp -d)"
trap 'rm -rf "$STAGING"' EXIT
PKG="$STAGING/onedrive-backup"
mkdir -p "$PKG/DEBIAN" "$PKG/usr/bin" "$PKG/usr/lib/onedrive-backup" \
         "$PKG/usr/share/doc/onedrive-backup" "$PKG/usr/share/man/man8" \
         "$PKG/usr/share/onedrive-backup/client" "$PKG/etc/onedrive-backup" \
         "$PKG/lib/systemd/system"
install -m 0755 "$ROOT/packaging/onedrive-backup-docker" \
  "$PKG/usr/bin/onedrive-backup-docker"
install -m 0755 "$ROOT/packaging/onedrive-backup" "$PKG/usr/bin/onedrive-backup"
install -m 0755 "$ROOT/packaging/onedrive-backup-admin-password" "$PKG/usr/bin/onedrive-backup-admin-password"
install -d -m 0755 "$PKG/usr/lib/onedrive-backup/onedrive_api"
install -m 0755 "$ROOT/packaging/install-runtime.sh" "$PKG/usr/lib/onedrive-backup/install-runtime.sh"
install -m 0755 "$ROOT/packaging/docker-run.sh" "$PKG/usr/lib/onedrive-backup/docker-run.sh"
install -m 0644 "$ROOT/packaging/defaults" "$PKG/usr/share/onedrive-backup/defaults"
install -m 0644 "$ROOT/src/onedrive_api/__init__.py" "$PKG/usr/lib/onedrive-backup/onedrive_api/__init__.py"
install -m 0644 "$ROOT/src/onedrive_api/admin_password.py" "$PKG/usr/lib/onedrive-backup/onedrive_api/admin_password.py"
install -m 0644 "$ROOT/config/server.json" "$PKG/etc/onedrive-backup/server.json"
install -m 0644 "$ROOT/config/backup.json" "$PKG/etc/onedrive-backup/backup.json"
install -m 0644 "$ROOT/packaging/onedrive-backup-api.service" \
  "$PKG/lib/systemd/system/onedrive-backup-api.service"
install -m 0644 "$ROOT/packaging/onedrive-backup.service" \
  "$PKG/lib/systemd/system/onedrive-backup.service"
install -m 0644 "$ROOT/packaging/onedrive-backup.timer" \
  "$PKG/lib/systemd/system/onedrive-backup.timer"
install -m 0644 "$ROOT/README.md" "$PKG/usr/share/doc/onedrive-backup/README.md"
install -m 0644 "$ROOT/LICENSE" "$PKG/usr/share/doc/onedrive-backup/copyright"
install -m 0644 "$ROOT/CHANGELOG.md" "$PKG/usr/share/doc/onedrive-backup/CHANGELOG.md"
install -m 0644 "$ROOT/packaging/onedrive-backup.8" \
  "$PKG/usr/share/man/man8/onedrive-backup.8"
gzip -n -9 "$PKG/usr/share/man/man8/onedrive-backup.8"
for name in postinst prerm postrm; do
  install -m 0755 "$ROOT/packaging/$name" "$PKG/DEBIAN/$name"
done
printf '/etc/onedrive-backup/server.json\n/etc/onedrive-backup/backup.json\n' \
  > "$PKG/DEBIAN/conffiles"
printf '%s\n' "vasilyvz/onedrive-backup:$VERSION" \
  > "$PKG/usr/lib/onedrive-backup/image-spec"
for item in "$ROOT"/dist/client/onedrive_backup_client-"$VERSION"-*.whl; do
  if [[ -f "$item" ]]; then
    install -m 0644 "$item" "$PKG/usr/share/onedrive-backup/client/"
  fi
done
cat > "$PKG/DEBIAN/control" <<EOF
Package: onedrive-backup
Version: $VERSION
Architecture: all
Section: admin
Priority: optional
Maintainer: OneDrive Backup maintainers <maintainers@example.org>
Depends: docker.io | docker-ce | moby-engine, adduser, util-linux, ca-certificates, python3
Description: OneDrive Business backup API and Docker host controller
 Installs version-pinned Docker service, systemd timer, mTLS configuration,
 encrypted restic backup management, and host bootstrap tools. No credentials
 or server certificates are included in the Debian package.
EOF
mkdir -p "$ROOT/dist"
OUT="$ROOT/dist/onedrive-backup_${VERSION}_all.deb"
dpkg-deb --build --root-owner-group "$PKG" "$OUT"
sha256sum "$OUT" > "$OUT.sha256"
dpkg-deb --info "$OUT"
echo "Built $OUT"

