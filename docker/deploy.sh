#!/usr/bin/env bash
# Production deployment. Copy project-root release credentials to root-only host file.
set -Eeuo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SOURCE="$ROOT/.env"
DEST_DIR="/var/lib/onedrive-backup/credentials"
DEST="$DEST_DIR/.env"
DEFAULT="/etc/default/onedrive-backup"

[[ "$(id -u)" == "0" ]] || { echo "deploy: root required" >&2; exit 2; }
[[ -s "$SOURCE" && -f "$SOURCE" && ! -L "$SOURCE" ]] || {
    echo "deploy: .env is missing (or unsafe) in project root" >&2; exit 2;
}
# Prevent casual reads of the credential source in this Git checkout.
chmod 0600 "$SOURCE"
install -d -m 0700 -o root -g root "$DEST_DIR"
TMP="$(mktemp "$DEST_DIR/.import.XXXXXXXX")"
trap 'rm -f "$TMP"' EXIT
install -m 0600 -o root -g root "$SOURCE" "$TMP"
mv -f "$TMP" "$DEST"

# The /etc/default file is a public pointer and public runtime settings only.
VERSION="$(tr -d ' \r\n' < "$ROOT/VERSION")"
install -d -m 0755 /etc/default
cat > "$DEFAULT" <<DEFAULT_END
ONEDRIVE_CREDENTIALS_FILE=$DEST
ONEDRIVE_IMAGE=vasilyvz/onedrive-backup:$VERSION
ONEDRIVE_CONTAINER=onedrive-backup
ONEDRIVE_NETWORK=smart-assistant
ONEDRIVE_HOST_PORT=8050
ONEDRIVE_CONFIG_DIR=/etc/onedrive-backup
ONEDRIVE_DATA_DIR=/srv/backup/onedrive
ONEDRIVE_SECRET_DIR=/var/lib/onedrive-backup/secrets
DEFAULT_END
chmod 0644 "$DEFAULT"
chown root:root "$DEFAULT"

# Authenticate Docker Hub only in this transient process; never pass PAT to container.
DOCKER_USER=""
DOCKER_PAT=""
while IFS= read -r line || [[ -n "$line" ]]; do
    case "$line" in
        DOCKER_USER=*) DOCKER_USER="${line#DOCKER_USER=}" ;;
        DOCKER_PAT=*) DOCKER_PAT="${line#DOCKER_PAT=}" ;;
    esac
done < "$DEST"
DOCKER_USER="${DOCKER_USER%\"}"; DOCKER_USER="${DOCKER_USER#\"}"
DOCKER_PAT="${DOCKER_PAT%\"}"; DOCKER_PAT="${DOCKER_PAT#\"}"
if [[ -n "$DOCKER_PAT" ]]; then
    [[ -n "$DOCKER_USER" ]] || { echo "deploy: missing DOCKER_USER" >&2; exit 2; }
    printf '%s\n' "$DOCKER_PAT" | docker login --username "$DOCKER_USER" --password-stdin >/dev/null
fi
unset DOCKER_USER DOCKER_PAT

# Install package from this release. Preserves conffiles and user's backup data.
PACKAGE="$ROOT/dist/onedrive-backup_${VERSION}_all.deb"
[[ -f "$PACKAGE" ]] || { echo "deploy: Debian package missing: $PACKAGE" >&2; exit 2; }
dpkg -i "$PACKAGE"

# Don't start a non-mTLS server before real certs and the backup volume exist.
missing=0
for f in server.crt server.key ca.crt ca.crl; do
    [[ -s "/etc/onedrive-backup/certs/$f" ]] || { echo "deploy: pending certificate: $f"; missing=1; }
done
if ! mountpoint -q /srv/backup; then
    echo "deploy: /srv/backup must be a mounted backup filesystem before starting"
    missing=1
fi
if (( missing )); then
    echo "deploy: package installed and credentials staged; production API NOT started (mTLS fail-closed)"
    exit 3
fi
systemctl daemon-reload
systemctl enable --now onedrive-backup-api.service
/usr/bin/onedrive-backup-docker status
/usr/bin/onedrive-backup-docker ports

