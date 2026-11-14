#!/usr/bin/env bash
# Production server runtime. Never pass credentials to Docker.
set -Eeuo pipefail
action="${1:-}"
image="${ONEDRIVE_IMAGE:-vasilyvz/onedrive-backup:0.3.1}"
name="${ONEDRIVE_CONTAINER:-onedrive-backup}"
network="${ONEDRIVE_NETWORK:-smart-assistant}"
config="${ONEDRIVE_CONFIG_DIR:-/etc/onedrive-backup}"
data="${ONEDRIVE_DATA_DIR:-/srv/backup/onedrive}"
fail() { echo "onedrive-backup-docker: $*" >&2; exit 1; }
case "$action" in
  stop)
    docker rm -f "$name" >/dev/null 2>&1 || true
    ;;
  status)
    docker inspect "$name" --format '{{.State.Status}} {{json .NetworkSettings.Ports}}'
    ;;
  ports)
    echo "Not published on host; internal endpoint: https://$name:8050 (network $network)"
    ;;
  start)
    for f in server.crt server.key ca.crt proxy-ca.crt trust-bundle.pem; do
      test -s "$config/certs/$f" || fail "Missing mTLS file: $f"
    done
    test -s "$config/admin-password.hash" || fail "Admin password hash missing; use sudo onedrive-backup-admin-password"
    test -s "$config/server.json" || fail "Missing server.json"
    test -s "$config/backup.json" || fail "Missing backup.json"
    test -d "$data" || fail "Missing backup data volume"
    docker network inspect "$network" >/dev/null || fail "Missing Docker network $network"
    docker image inspect "$image" >/dev/null || docker pull "$image"
    docker rm -f "$name" >/dev/null 2>&1 || true
    docker run -d --name "$name" --restart unless-stopped \
      --user "$(id -u onedrive-backup):$(id -g onedrive-backup)" \
      --network "$network" --network-alias "$name" \
      --security-opt no-new-privileges:true \
      --mount "type=bind,src=$config,dst=/config,readonly" \
      --mount "type=bind,src=$data,dst=/data" \
      "$image"
    ;;
  *) fail "Usage: docker-run.sh start|stop|status|ports" ;;
esac
