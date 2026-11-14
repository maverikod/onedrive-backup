#!/usr/bin/env bash
# Debian post-install bootstrap from /etc/default/onedrive-backup.
set -Eeuo pipefail
umask 077
[[ "$(id -u)" == 0 ]] || { echo "install-runtime: root required" >&2; exit 2; }
[[ -f /etc/default/onedrive-backup && ! -L /etc/default/onedrive-backup ]] || exit 2
. /etc/default/onedrive-backup
destination="$ONEDRIVE_CONFIG_DIR/certs"
cert="$ONEDRIVE_CERT_SOURCE"
key="$ONEDRIVE_KEY_SOURCE"
proxy_ca="$ONEDRIVE_PROXY_CA_SOURCE"
client_ca="$ONEDRIVE_CLIENT_CA_SOURCE"
for path in "$cert" "$key" "$proxy_ca" "$client_ca"; do
    [[ "$path" = /* ]] || { echo "install-runtime: TLS source path must be absolute" >&2; exit 2; }
    if [[ ! -s "$path" || ! -f "$path" || -L "$path" ]]; then
        echo "install-runtime: TLS file not available; configure source paths in /etc/default/onedrive-backup"
        exit 10
    fi
done
command -v openssl >/dev/null
openssl verify -CAfile "$proxy_ca" -purpose sslserver -verify_hostname onedrive-backup "$cert" >/dev/null
openssl verify -CAfile "$proxy_ca" -purpose sslclient "$cert" >/dev/null
python3 - "$cert" "$key" <<'PY_VERIFY'
import ssl,sys
ctx=ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
ctx.minimum_version=ssl.TLSVersion.TLSv1_2
ctx.load_cert_chain(sys.argv[1],sys.argv[2])
PY_VERIFY
install -d -m 0750 -o root -g onedrive-backup "$destination"
copy_cert() {
    local src="$1" dst="$2" tmp
    if [[ "$src" != "$dst" ]]; then
        tmp="$(mktemp "$destination/.install.XXXXXXXX")"
        install -m 0640 -o root -g onedrive-backup "$src" "$tmp"
        mv -f "$tmp" "$dst"
    fi
    chown root:onedrive-backup "$dst"
    chmod 0640 "$dst"
}
copy_cert "$cert" "$destination/server.crt"
copy_cert "$key" "$destination/server.key"
copy_cert "$proxy_ca" "$destination/proxy-ca.crt"
copy_cert "$client_ca" "$destination/ca.crt"
bundle="$(mktemp "$destination/.trust.XXXXXXXX")"
trap 'rm -f "$bundle"' EXIT
cat "$proxy_ca" > "$bundle"
printf '\n' >> "$bundle"
cat "$client_ca" >> "$bundle"
chown root:onedrive-backup "$bundle"
chmod 0640 "$bundle"
mv -f "$bundle" "$destination/trust-bundle.pem"
echo "install-runtime: server TLS materials verified and installed"

if ! command -v docker >/dev/null; then
    echo "install-runtime: Docker unavailable; image pull deferred"
    exit 11
fi
docker_config="$(mktemp -d)"
chmod 0700 "$docker_config"
trap 'rm -rf "$docker_config"' EXIT
export DOCKER_CONFIG="$docker_config"
# Docker Hub tokens are never printed and never installed into the package.
if [[ -e "$ONEDRIVE_CREDENTIALS_FILE" ]]; then
    python3 - "$ONEDRIVE_CREDENTIALS_FILE" <<'PY_LOGIN'
import os,stat,subprocess,sys
p=sys.argv[1]
s=os.lstat(p)
if not stat.S_ISREG(s.st_mode) or s.st_uid!=0 or stat.S_IMODE(s.st_mode)!=0o600:
    raise SystemExit("install-runtime: unsafe Docker Hub credentials file")
values={}
with open(p,encoding="utf-8") as f:
    for line in f:
        if "=" in line:
            k,v=line.strip().split("=",1)
            if k in ("DOCKER_USER","DOCKER_PAT"):
                values[k]=v.strip().strip('"')
pat=values.get("DOCKER_PAT","")
if pat:
    user=values.get("DOCKER_USER","")
    if not user: raise SystemExit("install-runtime: DOCKER_USER missing")
    result=subprocess.run(["docker","login","--username",user,"--password-stdin"],
                         input=pat+"\n",text=True,stdout=subprocess.DEVNULL,
                         stderr=subprocess.PIPE)
    if result.returncode:
        raise SystemExit("install-runtime: Docker Hub authentication failed")
PY_LOGIN
fi
if ! docker pull "$ONEDRIVE_IMAGE" >/dev/null; then
    docker image inspect "$ONEDRIVE_IMAGE" >/dev/null || {
        echo "install-runtime: required Docker image unavailable" >&2
        exit 12
    }
    echo "install-runtime: using local image after pull failure"
fi
echo "install-runtime: Docker image ready"
