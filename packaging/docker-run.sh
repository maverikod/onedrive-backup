#!/usr/bin/env bash
# Production server runtime. Never pass credentials to Docker.
set -Eeuo pipefail
action="${1:-}"
image="${ONEDRIVE_IMAGE:-$(cat /usr/lib/onedrive-backup/image-spec)}"
name="${ONEDRIVE_CONTAINER:-onedrive-backup}"
network="${ONEDRIVE_NETWORK:-smart-assistant}"
config="${ONEDRIVE_CONFIG_DIR:-/etc/onedrive-backup}"
archive=/srv/archive
data="${ONEDRIVE_DATA_DIR:-/srv/archive/onedrive-backup}"
secrets="${ONEDRIVE_SECRET_DIR:-/var/lib/onedrive-backup/secrets}"
state="${ONEDRIVE_RCLONE_STATE_DIR:-/var/lib/onedrive-backup/rclone-state}"
fail() { echo "onedrive-backup-docker: $*" >&2; exit 1; }
# Describe the filesystem that holds $1 (or its nearest existing parent) for a refusal message.
fs_describe() {
  local probe="$1" line="" target="" source=""
  while [[ ! -e "$probe" && "$probe" != / ]]; do probe="$(dirname "$probe")"; done
  line="$(findmnt -n -o TARGET,SOURCE -T "$probe" 2>/dev/null | head -n 1 || true)"
  read -r target source <<<"$line" || true
  if [[ -z "$target" ]]; then
    echo "an unknown filesystem"
  elif [[ "$target" = / ]]; then
    echo "the root filesystem (${source:-unknown device})"
  else
    echo "the filesystem ${source:-unknown device} mounted at $target"
  fi
}
# Filesystem guard (decision D9): the data directory must lie on the mounted /srv/archive filesystem. A refusal is a
# refusal; it never degrades into the restricted scaffold.
check_archive_fs() {
  local mreal real target
  mreal="$(realpath -m "$archive")"
  real="$(realpath -m "$data")"
  findmnt -n -M "$archive" >/dev/null 2>&1 \
    || fail "$archive is not mounted: the data directory $real is on $(fs_describe "$real"); it must be on the mounted $archive filesystem"
  [[ -e "$data" ]] || fail "Host data directory does not exist: $data"
  target="$(findmnt -n -o TARGET -T "$data" 2>/dev/null | head -n 1 || true)"
  case "$target" in
    "$archive"|"$archive"/*|"$mreal"|"$mreal"/*) ;;
    *) fail "the data directory $real is not on the $archive filesystem: it is on $(fs_describe "$real")" ;;
  esac
  case "$real" in
    "$mreal"|"$mreal"/*) ;;
    *) fail "the data directory $real is not on the $archive filesystem: it is on $(fs_describe "$real")" ;;
  esac
}
# The host backup directory is a plain directory owned by the service user on the mounted archive filesystem; whether /data
# is a mount point is checked inside the container. Every cause has its own refusal text.
check_data_dir() {
  local mode
  check_archive_fs
  [[ -e "$data" ]] || fail "Host data directory does not exist: $data"
  [[ -d "$data" && ! -L "$data" ]] || fail "Host data path is not a plain directory: $data"
  [[ "$(stat -c %u "$data")" = "$(id -u onedrive-backup)" ]] || fail "Host data directory is not owned by onedrive-backup: $data"
  mode="$(stat -c %a "$data")"
  (( (8#$mode & 8#200) != 0 )) || fail "Host data directory is not writable by its owner: $data"
  (( (8#$mode & 8#002) == 0 )) || fail "Host data directory is world-writable: $data"
}
# rclone state (decision D10): rclone refreshes its OAuth token in its configuration file, so the service works on a writable
# copy in its own state directory; the original under $secrets stays read-only.
check_state_dir() {
  [[ -d "$state" && ! -L "$state" ]] || fail "rclone state directory is missing or not a plain directory: $state"
  [[ "$(stat -c %a "$state")" = 700 ]] || fail "rclone state directory must be mode 0700: $state"
  [[ "$(stat -c %u "$state")" = "$(id -u onedrive-backup)" ]] || fail "rclone state directory owner invalid: $state"
}
check_state_copy() {
  local copy="$state/rclone.conf"
  [[ -e "$copy" || -L "$copy" ]] || return 0
  [[ -f "$copy" && ! -L "$copy" ]] || fail "rclone state copy is not a plain file: $copy"
  [[ "$(stat -c %a "$copy")" = 600 ]] || fail "rclone state copy must be mode 0600: $copy"
  [[ "$(stat -c %u "$copy")" = "$(id -u onedrive-backup)" ]] || fail "rclone state copy owner invalid: $copy"
}
# Seed the copy from the original when it is absent, empty or older than the original; otherwise keep it, so a token
# refreshed by rclone survives a restart. The copy appears by renaming a temporary file of the state directory.
seed_rclone_state() {
  local src="$secrets/rclone.conf" copy="$state/rclone.conf" tmp
  [[ -s "$src" ]] || return 0
  if [[ -s "$copy" && ! "$src" -nt "$copy" ]]; then return 0; fi
  tmp="$(mktemp "$state/.rclone.conf.XXXXXX")" || fail "rclone state directory is not writable: $state"
  if ! { cat "$src" >"$tmp" && chmod 0600 "$tmp" && chown "$(id -u onedrive-backup):$(id -g onedrive-backup)" "$tmp" \
         && mv -f "$tmp" "$copy"; }; then
    rm -f "$tmp"
    fail "rclone state copy could not be written: $copy"
  fi
}
require_state_copy() {
  [[ -f "$state/rclone.conf" && ! -L "$state/rclone.conf" && -s "$state/rclone.conf" ]] \
    || fail "rclone state copy unavailable: $state/rclone.conf"
}
case "$action" in
  stop)
    docker rm -f "$name" >/dev/null 2>&1 || true
    ;;
  status)
    docker inspect "$name" --format '{{.State.Status}} {{json .NetworkSettings.Ports}}'
    ;;
  ports)
    echo "Published on the LAN: https://<host>:8443 -> container port 8050; internal endpoint: https://$name:8050 (network $network)"
    ;;
  discover)
    [[ "${2:-}" = "" || "${2:-}" = "--dry-run" ]] || fail "Unknown discover argument"
    check_data_dir
    test -s "$secrets/rclone.conf" || fail "rclone.conf unavailable"
    require_state_copy
    docker inspect "$name" --format "{{.State.Running}}" | grep -qx true || fail "Container is not running"
    if [[ "${2:-}" = "--dry-run" ]]; then
      docker exec "$name" python -m onedrive_api.sharepoint_discover_cli --dry-run
    else
      docker exec "$name" python -m onedrive_api.sharepoint_discover_cli
    fi
    ;;
  init|check)
    [[ "$#" -eq 1 ]] || fail "Unexpected argument"
    check_data_dir
    test -s "$secrets/rclone.conf" || fail "rclone.conf unavailable"
    test -s "$secrets/restic-password" || fail "restic-password unavailable"
    require_state_copy
    docker inspect "$name" --format '{{.State.Running}}' | grep -qx true || fail "Container is not running"
    docker exec "$name" sh -c '[ "$ONEDRIVE_SCAFFOLD_MODE" = 0 ]' || fail "Scaffold mode"
    docker exec "$name" python -m onedrive_backup --config /config/backup.json "$action"
    ;;
  backup)
    [[ "$#" -eq 1 || ( "$#" -eq 2 && "${2:-}" = "--dry-run" ) ]] || fail "Usage: backup [--dry-run]"
    check_data_dir
    test -s "$secrets/rclone.conf" || fail "rclone.conf unavailable"
    test -s "$secrets/restic-password" || fail "restic-password unavailable"
    require_state_copy
    docker inspect "$name" --format '{{.State.Running}}' | grep -qx true || fail "Container is not running"
    docker exec "$name" sh -c '[ "$ONEDRIVE_SCAFFOLD_MODE" = 0 ]' || fail "Scaffold mode"
    docker exec "$name" python -m onedrive_api.backup_run "${@:2}"
    ;;
  start)
    # Server-auth HTTPS needs only the server certificate and key; the CA and trust-bundle files stay provisioned for the
    # later switch to mTLS but are not required.
    for f in server.crt server.key; do
      test -s "$config/certs/$f" || fail "Missing TLS file: $f"
    done
    # Protect mounted application credentials from traversal or exposure.
    test -d "$secrets" && ! test -L "$secrets" || fail "Missing private secrets directory"
    test "$(stat -c %a "$secrets")" = 700 || fail "Secrets directory must be mode 0700"
    test "$(stat -c %u "$secrets")" = "$(id -u onedrive-backup)" || fail "Secrets directory owner invalid"
    # With absent credentials, start restricted scaffold.
    scaffold=0
    # Fail closed: a missing or unsafe host data directory, or one that is not on the mounted archive filesystem, never
    # degrades into scaffold data.
    check_data_dir
    check_state_dir
    if ! test -s "$secrets/rclone.conf" || ! test -s "$secrets/restic-password"; then
      scaffold=1
      echo "Backup credentials not ready: restricted scaffold"
    fi
    seed_rclone_state
    check_state_copy
    test -s "$config/server.json" || fail "Missing server.json"
    test -s "$config/backup.json" || fail "Missing backup.json"
    docker network inspect "$network" >/dev/null || fail "Missing Docker network $network"
    docker image inspect "$image" >/dev/null || docker pull "$image"
    docker rm -f "$name" >/dev/null 2>&1 || true
    docker run -d --name "$name" --restart unless-stopped       --env "ONEDRIVE_SCAFFOLD_MODE=$scaffold" \
      --user "$(id -u onedrive-backup):$(id -g onedrive-backup)" \
      --network "$network" --network-alias "$name" \
      --publish "8443:8050" \
      --security-opt no-new-privileges:true \
      --mount "type=bind,src=$config,dst=/config,readonly" \
      --mount "type=bind,src=$data,dst=/data" \
      --mount "type=bind,src=$secrets,dst=/secrets,readonly" \
      --mount "type=bind,src=$state,dst=/rclone-state" \
      "$image"
    ;;
  *) fail "Usage: docker-run.sh start|stop|status|ports|discover [--dry-run]|init|backup [--dry-run]|check" ;;
esac
