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
# A single CN=onedrive-backup dual-purpose leaf is issued by proxy CA.
# Import it as BOTH server identity and proxy registration client identity.
# Trust CA for inbound client authentication (separate from proxy CA).
CERT_SOURCE="$ROOT/mtls-certs"
PROXY_CA="$CERT_SOURCE/for-proxy/ca/ca.crt"
LEAF="$CERT_SOURCE/for-proxy/issued"
if [ -d "$CERT_SOURCE" ]; then
    for item in "$LEAF/onedrive-backup.crt" "$LEAF/onedrive-backup.key" \
                "$PROXY_CA" "$CERT_SOURCE/cacert.pem"; do
        [[ -s "$item" && -f "$item" && ! -L "$item" ]] || {
            echo "deploy: missing/invalid certificate material: $item" >&2; exit 3;
        }
    done
    command -v openssl >/dev/null || { echo "deploy: openssl missing" >&2; exit 3; }
    # Verify both extended key usages against the proxy's own root CA.
    openssl verify -CAfile "$PROXY_CA" -purpose sslserver "$LEAF/onedrive-backup.crt" >/dev/null
    openssl verify -CAfile "$PROXY_CA" -purpose sslclient "$LEAF/onedrive-backup.crt" >/dev/null
    python3 - "$LEAF/onedrive-backup.crt" "$LEAF/onedrive-backup.key" <<'PY_TLS_CHECK'
import ssl
import sys
ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
ctx.minimum_version = ssl.TLSVersion.TLSv1_2
ctx.load_cert_chain(sys.argv[1], sys.argv[2])
PY_TLS_CHECK
    install -d -m 0750 -o root -g onedrive-backup /etc/onedrive-backup/certs
    install -m 0640 -o root -g onedrive-backup "$LEAF/onedrive-backup.crt" \
        /etc/onedrive-backup/certs/server.crt
    install -m 0640 -o root -g onedrive-backup "$LEAF/onedrive-backup.key" \
        /etc/onedrive-backup/certs/server.key
    install -m 0640 -o root -g onedrive-backup "$PROXY_CA" \
        /etc/onedrive-backup/certs/proxy-ca.crt
    # The adapter validates the server certificate against server.ssl.ca;
    # both proxy CA (issuer of our server certificate) and legacy client CA
    # remain trusted for internal mTLS clients. Revocation is proxy-managed.
    BUNDLE_TMP="$(mktemp /etc/onedrive-backup/certs/.bundle.XXXXXXXX)"
    cat "$PROXY_CA" > "$BUNDLE_TMP"
    printf '\n' >> "$BUNDLE_TMP"
    cat "$CERT_SOURCE/cacert.pem" >> "$BUNDLE_TMP"
    chmod 0640 "$BUNDLE_TMP"
    chown root:onedrive-backup "$BUNDLE_TMP"
    mv -f "$BUNDLE_TMP" /etc/onedrive-backup/certs/trust-bundle.pem
    install -m 0640 -o root -g onedrive-backup "$CERT_SOURCE/cacert.pem" \
        /etc/onedrive-backup/certs/ca.crt
fi

# Don't start a non-mTLS server before real certs and the backup volume exist.
missing=0
if [ ! -s /etc/onedrive-backup/admin-password.hash ]; then
    echo "deploy: configure admin account with sudo onedrive-backup-admin-password"
    missing=1
fi
for f in server.crt server.key ca.crt proxy-ca.crt trust-bundle.pem; do
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

