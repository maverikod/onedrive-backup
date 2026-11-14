#!/usr/bin/env bash
# Production server runtime. Never pass credentials to Docker.
set -Eeuo pipefail
action="${1:-}"
image="${ONEDRIVE_IMAGE:-vasilyvz/onedrive-backup:0.3.3}"
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
    # With an absent password and/or mount, start only a restricted scaffold.
    scaffold=0
    if ! test -s "$config/admin-password.hash"; then
      scaffold=1
      echo "Admin password unset: UI authentication will remain locked"
    fi
    if ! mountpoint -q "/srv/backup"; then
      scaffold=1
      data="$ONEDRIVE_SCAFFOLD_DATA_DIR"
      install -d -m 0700 -o onedrive-backup -g onedrive-backup "$data"
      echo "Backup disk not mounted: using empty scaffold data"
    fi
    test -s "$config/server.json" || fail "Missing server.json"
    test -s "$config/backup.json" || fail "Missing backup.json"
    test -d "$data" || fail "Missing backup data volume"
    docker network inspect "$network" >/dev/null || fail "Missing Docker network $network"
    docker image inspect "$image" >/dev/null || docker pull "$image"
    docker rm -f "$name" >/dev/null 2>&1 || true
    docker run -d --name "$name" --restart unless-stopped       --env "ONEDRIVE_SCAFFOLD_MODE=$scaffold" \
      --user "$(id -u onedrive-backup):$(id -g onedrive-backup)" \
      --network "$network" --network-alias "$name" \
      --security-opt no-new-privileges:true \
      --mount "type=bind,src=$config,dst=/config,readonly" \
      --mount "type=bind,src=$data,dst=/data" \
      "$image"
    ;;
  *) fail "Usage: docker-run.sh start|stop|status|ports" ;;
esac
