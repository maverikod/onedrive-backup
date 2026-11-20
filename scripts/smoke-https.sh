#!/usr/bin/env bash
# Disposable end-to-end smoke test of the server-auth HTTPS listener. Never use generated test certificates in production.
# The transport is the mcp-proxy-adapter configuration alone (server.protocol https): no client certificate is requested,
# the service is open (auth off) and the scaffold answers the command error 503 for the empty backup repository.
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
mkdir -p "$ROOT_TMP/config/certs" "$ROOT_TMP/data" "$ROOT_TMP/ca" "$ROOT_TMP/secrets"
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
      "https://localhost:$PORT/health" > "$ROOT_TMP/reply" 2>/dev/null; then
      ready=1; break
  fi
  sleep 1
done
if [ "$ready" -ne 1 ]; then
  docker logs "$NAME" --tail 110 >&2 || true
  echo '[FAIL] HTTPS health did not become available without a client certificate' >&2
  exit 1
fi
python3 - "$ROOT_TMP/reply" <<'PY'
import json,sys
j=json.load(open(sys.argv[1]))
assert j["status"]=="ok",j
PY
# Plain HTTP to the TLS port is refused or closed with no content.
if [ -n "$(curl -sS --max-time 5 "http://localhost:$PORT/health" 2>/dev/null || true)" ]; then
  echo '[FAIL] the TLS port answered a plain HTTP request' >&2
  exit 1
fi
# A client that does not trust the project CA fails verification.
if curl -fsS --connect-timeout 2 --max-time 5 "https://localhost:$PORT/health" >/dev/null 2>&1; then
  echo '[FAIL] a client without the project CA completed the TLS handshake' >&2
  exit 1
fi
RPC='{"jsonrpc":"2.0","method":"backup_snapshots","params":{},"id":1}'
# The service is open: the command runs without any credential and the missing repository is the scaffold error 503.
http_code="$(curl -sS -o "$ROOT_TMP/error" -w '%{http_code}' \
  --cacert "$ROOT_TMP/config/certs/ca.crt" \
  -X POST -H 'Content-Type: application/json' --data "$RPC" \
  --max-time 8 "https://localhost:$PORT/api/jsonrpc")"
[[ "$http_code" == 200 ]] || {
 echo "Unexpected snapshots HTTP status: $http_code"; cat "$ROOT_TMP/error"; exit 1;
}
python3 - "$ROOT_TMP/error" <<'PY_SNAP'
import json,sys
j=json.load(open(sys.argv[1]))
assert j["result"]["success"] is False and j["result"]["error"]["code"]==503,j
PY_SNAP
echo '[PASS] server-auth HTTPS, no client certificate, plain HTTP refused, untrusting client fails, health 200, open service, missing repo 503'
