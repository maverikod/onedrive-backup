#!/usr/bin/env bash
# Issue dual-use certificate using root CA already present on CAS; never commit keys.
set -Eeuo pipefail
umask 077
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
CA_DIR="$ROOT/mtls-certs/for-proxy/ca"
DEST="$ROOT/mtls-certs/for-proxy/issued"
NAME="onedrive-backup"
for part in ca.crt ca.key; do
  if [[ ! -f "$CA_DIR/$part" || -L "$CA_DIR/$part" ]]; then
    echo "Missing CA file: $part" >&2; exit 2
  fi
done
mkdir -p "$DEST"
chmod 0700 "$DEST"
if [[ -e "$DEST/$NAME.crt" || -e "$DEST/$NAME.key" ]]; then
  echo "Certificate or key already exists; refusing overwrite" >&2; exit 3
fi
trap 'if [[ ! -f "$DEST/$NAME.crt" ]]; then rm -f "$DEST/$NAME.csr" "$DEST/$NAME.key"; fi' EXIT
openssl req -new -newkey rsa:3072 -nodes -sha256 \
  -subj '/C=UA/O=OneDrive Backup/CN=onedrive-backup' \
  -addext 'subjectAltName=DNS:onedrive-backup,DNS:localhost,IP:127.0.0.1,IP:192.168.254.26' \
  -keyout "$DEST/$NAME.key" -out "$DEST/$NAME.csr"
cat > "$DEST/leaf.ext" <<'EOF'
basicConstraints=critical,CA:FALSE
keyUsage=critical,digitalSignature,keyEncipherment
extendedKeyUsage=serverAuth,clientAuth
subjectAltName=DNS:onedrive-backup,DNS:localhost,IP:127.0.0.1,IP:192.168.254.26
subjectKeyIdentifier=hash
authorityKeyIdentifier=keyid,issuer
EOF
serial="$(openssl rand -hex 16)"
openssl x509 -req -in "$DEST/$NAME.csr" -CA "$CA_DIR/ca.crt" \
  -CAkey "$CA_DIR/ca.key" -set_serial "0x$serial" \
  -out "$DEST/$NAME.crt" -days 365 -sha256 -extfile "$DEST/leaf.ext"
openssl verify -CAfile "$CA_DIR/ca.crt" -purpose sslserver "$DEST/$NAME.crt"
openssl verify -CAfile "$CA_DIR/ca.crt" -purpose sslclient "$DEST/$NAME.crt"
chmod 0600 "$DEST/$NAME.key" "$DEST/$NAME.csr"
chmod 0644 "$DEST/$NAME.crt" "$DEST/leaf.ext"
if id casuser >/dev/null 2>&1; then
  chown -R casuser:casgrp "$DEST"
fi
openssl x509 -in "$DEST/$NAME.crt" -noout -subject -issuer -dates
echo "Issued certificate for onedrive-backup."

