#!/usr/bin/env bash
# Disposable end-to-end mTLS smoke test. Never use generated test certificates in production.
set -Eeuo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
IMAGE="vasilyvz/onedrive-backup:$(tr -d ' \r\n' < "$ROOT/VERSION")"
ROOT_TMP="$(mktemp -d)"
NAME="odb-smoke-$$"
cleanup() {
  docker rm -f "$NAME" >/dev/null 2>&1 || true
  rm -rf "$ROOT_TMP"
}
trap cleanup EXIT
mkdir -p "$ROOT_TMP/config/certs" "$ROOT_TMP/data" "$ROOT_TMP/ca/newcerts"
openssl req -x509 -newkey rsa:2048 -sha256 -days 2 -nodes \
  -subj '/CN=Onedrive Test Root' \
  -keyout "$ROOT_TMP/ca/ca.key" -out "$ROOT_TMP/config/certs/ca.crt" >/dev/null 2>&1
openssl req -newkey rsa:2048 -sha256 -nodes -subj '/CN=localhost' \
  -keyout "$ROOT_TMP/config/certs/server.key" -out "$ROOT_TMP/server.csr" >/dev/null 2>&1
cat > "$ROOT_TMP/server.ext" <<'EXT'
subjectAltName=DNS:localhost,DNS:onedrive-backup,IP:127.0.0.1
extendedKeyUsage=serverAuth
keyUsage=digitalSignature,keyEncipherment
EXT
openssl x509 -req -in "$ROOT_TMP/server.csr" \
  -CA "$ROOT_TMP/config/certs/ca.crt" -CAkey "$ROOT_TMP/ca/ca.key" \
  -CAcreateserial -days 2 -sha256 -extfile "$ROOT_TMP/server.ext" \
  -out "$ROOT_TMP/config/certs/server.crt" >/dev/null 2>&1
openssl req -newkey rsa:2048 -sha256 -nodes -subj '/CN=Test Backup Client' \
  -keyout "$ROOT_TMP/client.key" -out "$ROOT_TMP/client.csr" >/dev/null 2>&1
cat > "$ROOT_TMP/client.ext" <<'EXT'
extendedKeyUsage=clientAuth
keyUsage=digitalSignature
EXT
openssl x509 -req -in "$ROOT_TMP/client.csr" -CA "$ROOT_TMP/config/certs/ca.crt" \
  -CAkey "$ROOT_TMP/ca/ca.key" -CAcreateserial -days 2 -sha256 \
  -extfile "$ROOT_TMP/client.ext" -out "$ROOT_TMP/client.crt" >/dev/null 2>&1
python3 - "$ROOT" "$ROOT_TMP/config" <<'PY'
import json,sys
from pathlib import Path
root=Path(sys.argv[1]); dest=Path(sys.argv[2])
cfg=json.loads((root/"config/server.json").read_text())
cfg["registration"]["enabled"]=False
cfg["registration"]["auto_on_startup"]=False
(dest/"server.json").write_text(json.dumps(cfg))
(dest/"backup.json").write_text((root/"config/backup.json").read_text())
PY
cp "$ROOT_TMP/config/certs/ca.crt" "$ROOT_TMP/config/certs/trust-bundle.pem"
cp "$ROOT_TMP/config/certs/ca.crt" "$ROOT_TMP/config/certs/proxy-ca.crt"
chmod -R 0755 "$ROOT_TMP"
chmod 0644 "$ROOT_TMP/config/certs/"*.key
# Interim API token: one disposable login:password line in a secrets directory (production keeps it
# mode 0600 owned by the service user); T = base64(login:password) is the X-API-Key header value.
mkdir -p "$ROOT_TMP/secrets"
printf 'smoke:%s\n' "$(openssl rand -hex 12)" > "$ROOT_TMP/secrets/api-credentials"
chmod 0755 "$ROOT_TMP/secrets"
chmod 0644 "$ROOT_TMP/secrets/api-credentials"
API_TOKEN="$(head -n 1 "$ROOT_TMP/secrets/api-credentials" | tr -d '\n' | base64 -w0)"
# Password setup is mandatory in the image. A disposable test-only hash is
# written after the bulk chmod so it keeps strict mode 0600.
PYTHONPATH="$ROOT/src" python3 - "$ROOT_TMP/config/admin-password.hash" <<'PY_AUTH_HASH'
import os
from pathlib import Path
import sys
from onedrive_api.admin_password import password_hash
out = Path(sys.argv[1])
out.write_text(password_hash("DisposableTestPasswordOnly2026!") + "\n")
out.chmod(0o600)
os.chown(out, 1000, 1000)
PY_AUTH_HASH
PORT="$(python3 - <<'PY'
import socket
s=socket.socket()
s.bind(("127.0.0.1",0))
print(s.getsockname()[1])
s.close()
PY
)"
docker run -d --name "$NAME" -p "127.0.0.1:$PORT:8050" \
  --mount "type=bind,source=$ROOT_TMP/config,target=/config,readonly" \
  --mount "type=bind,source=$ROOT_TMP/data,target=/data" \
  --mount "type=bind,source=$ROOT_TMP/secrets,target=/secrets,readonly" \
  "$IMAGE" >/dev/null
ready=0
for n in $(seq 1 35); do
  if curl -fsS --connect-timeout 1 --max-time 2 \
      --cacert "$ROOT_TMP/config/certs/ca.crt" \
      --cert "$ROOT_TMP/client.crt" --key "$ROOT_TMP/client.key" \
      "https://localhost:$PORT/health" > "$ROOT_TMP/reply" 2>/dev/null; then
      ready=1; break
  fi
  sleep 1
done
if [ "$ready" -ne 1 ]; then
  docker logs "$NAME" --tail 110 >&2 || true
  echo '[FAIL] mTLS health did not become available' >&2
  exit 1
fi
python3 - "$ROOT_TMP/reply" <<'PY'
import json,sys
j=json.load(open(sys.argv[1]))
assert j["status"]=="ok",j
PY
if curl -fsS --cacert "$ROOT_TMP/config/certs/ca.crt" \
     --max-time 5 "https://localhost:$PORT/health" >/dev/null 2>&1; then
  echo '[FAIL] mTLS accepted client without certificate' >&2
  exit 1
fi
RPC='{"jsonrpc":"2.0","method":"backup_snapshots","params":{},"id":1}'
# Without the token the gate answers 401; with it the command runs and the missing repository is 503.
http_code="$(curl -sS -o "$ROOT_TMP/error" -w '%{http_code}' \
  --cacert "$ROOT_TMP/config/certs/ca.crt" \
  --cert "$ROOT_TMP/client.crt" --key "$ROOT_TMP/client.key" \
  -X POST -H 'Content-Type: application/json' --data "$RPC" \
  --max-time 8 "https://localhost:$PORT/api/jsonrpc")"
[[ "$http_code" == 401 ]] || {
 echo "Unexpected tokenless JSON-RPC HTTP status: $http_code"; cat "$ROOT_TMP/error"; exit 1;
}
http_code="$(curl -sS -o "$ROOT_TMP/error" -w '%{http_code}' \
  --cacert "$ROOT_TMP/config/certs/ca.crt" \
  --cert "$ROOT_TMP/client.crt" --key "$ROOT_TMP/client.key" \
  -X POST -H 'Content-Type: application/json' -H "X-API-Key: $API_TOKEN" --data "$RPC" \
  --max-time 8 "https://localhost:$PORT/api/jsonrpc")"
[[ "$http_code" == 200 ]] || {
 echo "Unexpected snapshots HTTP status: $http_code"; cat "$ROOT_TMP/error"; exit 1;
}
python3 - "$ROOT_TMP/error" <<'PY_SNAP'
import json,sys
j=json.load(open(sys.argv[1]))
assert j["result"]["success"] is False and j["result"]["error"]["code"]==503,j
PY_SNAP

# Reject client certs from an untrusted CA; the proxy owns revocation policy.
openssl req -x509 -newkey rsa:2048 -sha256 -days 2 -nodes -subj '/CN=Untrusted Test Root' -keyout "$ROOT_TMP/untrusted-ca.key" -out "$ROOT_TMP/untrusted-ca.crt" >/dev/null 2>&1
openssl req -newkey rsa:2048 -sha256 -nodes -subj '/CN=Untrusted Client' -keyout "$ROOT_TMP/untrusted.key" -out "$ROOT_TMP/untrusted.csr" >/dev/null 2>&1
openssl x509 -req -in "$ROOT_TMP/untrusted.csr" -CA "$ROOT_TMP/untrusted-ca.crt" -CAkey "$ROOT_TMP/untrusted-ca.key" -CAcreateserial -days 2 -sha256 -extfile "$ROOT_TMP/client.ext" -out "$ROOT_TMP/untrusted.crt" >/dev/null 2>&1
if curl -fsS --cacert "$ROOT_TMP/config/certs/ca.crt" --cert "$ROOT_TMP/untrusted.crt" --key "$ROOT_TMP/untrusted.key" --connect-timeout 2 --max-time 5 "https://localhost:$PORT/health" >/dev/null 2>&1; then
  echo '[FAIL] mTLS accepted an untrusted client certificate' >&2
  exit 1
fi
echo '[PASS] mTLS handshake, mandatory trusted client cert, health 200, token gate 401, missing repo 503'
