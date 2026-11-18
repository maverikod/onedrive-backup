#!/usr/bin/env bash
# Production server runtime. Never pass credentials to Docker.
set -Eeuo pipefail
action="${1:-}"
image="${ONEDRIVE_IMAGE:-$(cat /usr/lib/onedrive-backup/image-spec)}"
name="${ONEDRIVE_CONTAINER:-onedrive-backup}"
network="${ONEDRIVE_NETWORK:-smart-assistant}"
config="${ONEDRIVE_CONFIG_DIR:-/etc/onedrive-backup}"
data="${ONEDRIVE_DATA_DIR:-/srv/backup/onedrive}"
secrets="${ONEDRIVE_SECRET_DIR:-/var/lib/onedrive-backup/secrets}"
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
  discover)
    [[ "${2:-}" = "" || "${2:-}" = "--dry-run" ]] || fail "Unknown discover argument"
    mountpoint -q "/srv/backup" || fail "Backup disk not mounted"
    test -s "$secrets/rclone.conf" || fail "rclone.conf unavailable"
    docker inspect "$name" --format "{{.State.Running}}" | grep -qx true || fail "Container is not running"
    if [[ "${2:-}" = "--dry-run" ]]; then
      docker exec "$name" python -m onedrive_api.sharepoint_discover_cli --dry-run
    else
      docker exec "$name" python -m onedrive_api.sharepoint_discover_cli
    fi
    ;;
  init|check)
    [[ "$#" -eq 1 ]] || fail "Unexpected argument"
    mountpoint -q "/srv/backup" || fail "Backup disk not mounted"
    test -s "$secrets/rclone.conf" || fail "rclone.conf unavailable"
    test -s "$secrets/restic-password" || fail "restic-password unavailable"
    docker inspect "$name" --format '{{.State.Running}}' | grep -qx true || fail "Container is not running"
    docker exec "$name" sh -c '[ "$ONEDRIVE_SCAFFOLD_MODE" = 0 ]' || fail "Scaffold mode"
    docker exec "$name" python -m onedrive_backup --config /config/backup.json "$action"
    ;;
  backup)
    [[ "$#" -eq 1 || ( "$#" -eq 2 && "${2:-}" = "--dry-run" ) ]] || fail "Usage: backup [--dry-run]"
    mountpoint -q "/srv/backup" || fail "Backup disk not mounted"
    test -s "$secrets/rclone.conf" || fail "rclone.conf unavailable"
    test -s "$secrets/restic-password" || fail "restic-password unavailable"
    docker inspect "$name" --format '{{.State.Running}}' | grep -qx true || fail "Container is not running"
    docker exec "$name" sh -c '[ "$ONEDRIVE_SCAFFOLD_MODE" = 0 ]' || fail "Scaffold mode"
    docker exec "$name" python -m onedrive_api.sharepoint_backup "${@:2}"
    ;;
  start)
    for f in server.crt server.key ca.crt proxy-ca.crt trust-bundle.pem; do
      test -s "$config/certs/$f" || fail "Missing mTLS file: $f"
    done
    # Protect mounted application credentials from traversal or exposure.
    test -d "$secrets" && ! test -L "$secrets" || fail "Missing private secrets directory"
    test "$(stat -c %a "$secrets")" = 700 || fail "Secrets directory must be mode 0700"
    test "$(stat -c %u "$secrets")" = "$(id -u onedrive-backup)" || fail "Secrets directory owner invalid"
    # With absent credentials, password or disk, start restricted scaffold.
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
    if ! test -s "$secrets/rclone.conf" || ! test -s "$secrets/restic-password"; then
      scaffold=1
      echo "Backup credentials not ready: restricted scaffold"
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
      --mount "type=bind,src=$secrets,dst=/secrets,readonly" \
      "$image"
    ;;
  *) fail "Usage: docker-run.sh start|stop|status|ports|discover [--dry-run]|init|backup [--dry-run]|check" ;;
esac
