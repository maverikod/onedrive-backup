#!/usr/bin/env bash
# Deployment wrapper. On the first run on a host it sets the restic repository password; the Debian postinst then
# performs the deployment. Host paths can be overridden with ONEDRIVE_SECRET_DIR, ONEDRIVE_DATA_DIR and
# ONEDRIVE_DEFAULTS_FILE (the environment wins over the defaults file, the defaults file over the built-in default).
set -Eeuo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
VERSION="$(tr -d '[:space:]' < "$ROOT/VERSION")"
DEFAULTS_FILE="${ONEDRIVE_DEFAULTS_FILE:-/etc/default/onedrive-backup}"

fail() { echo "$1" >&2; exit "${2:-1}"; }

# A value of /etc/default/onedrive-backup, read as text (the file is never executed).
default_of() {
  [[ -f "$DEFAULTS_FILE" && ! -L "$DEFAULTS_FILE" ]] || return 0
  sed -n "s/^$1=//p" "$DEFAULTS_FILE" | tail -n 1 | tr -d '"'
}

[[ "$(id -u)" == 0 ]] || fail "deploy: root required" 2
command -v restic >/dev/null 2>&1 || fail "deploy: the restic command is not installed on this host; install the restic package first" 2

from_defaults_secret="$(default_of ONEDRIVE_SECRET_DIR)"
from_defaults_data="$(default_of ONEDRIVE_DATA_DIR)"
SECRET_DIR="${ONEDRIVE_SECRET_DIR:-${from_defaults_secret:-/var/lib/onedrive-backup/secrets}}"
DATA_DIR="${ONEDRIVE_DATA_DIR:-${from_defaults_data:-/srv/backup/onedrive}}"
PASSWORD_FILE="$SECRET_DIR/restic-password"
REPO="$DATA_DIR/restic-repo"
MSG_WRONG="deploy: the password does not open the existing restic repository; nothing was written"
MSG_NO_TTY="deploy: restic password file is missing and no terminal is available; run docker/deploy.sh interactively once to set the password"
MSG_NO_REPO="deploy: the restic password file exists but the repository $REPO does not; nothing was created; remove the password file and run docker/deploy.sh again to set both"
TMP_PASSWORD=""
trap 'rm -f "$TMP_PASSWORD"' EXIT

repo_exists() { [[ -f "$REPO/config" ]]; }

# Read one password without echo into the variable named by $1.
ask() {
  local value
  IFS= read -r -s -p "$2" value || fail "deploy: no password was entered; nothing was written"
  echo >&2
  printf -v "$1" '%s' "$value"
}

warn_copy() {
  echo "IMPORTANT: note this restic password and keep a copy of it OUTSIDE this host (password manager or safe)." >&2
  echo "Without the password the backups can never be restored; it is stored on this host only in the root-owned password file." >&2
}

# Store $1 as the restic password file: mode 0600, owner root, written atomically.
store_password() {
  [[ -d "$SECRET_DIR" ]] || install -d -m 0700 -o root -g root "$SECRET_DIR"
  TMP_PASSWORD="$(mktemp "$SECRET_DIR/.restic-password.XXXXXX")"
  chmod 0600 "$TMP_PASSWORD"
  chown root:root "$TMP_PASSWORD"
  printf '%s\n' "$1" > "$TMP_PASSWORD"
  mv -f "$TMP_PASSWORD" "$PASSWORD_FILE"
  TMP_PASSWORD=""
}

new_repo=0
if [[ -e "$PASSWORD_FILE" || -L "$PASSWORD_FILE" ]]; then
  [[ -f "$PASSWORD_FILE" && ! -L "$PASSWORD_FILE" && -s "$PASSWORD_FILE" ]] \
    || fail "deploy: the restic password file is not a non-empty regular file: $PASSWORD_FILE"
  repo_exists || fail "$MSG_NO_REPO"
else
  [[ -t 0 ]] || fail "$MSG_NO_TTY"
  if repo_exists; then
    ask password "Restic repository password: "
    [[ -n "$password" ]] || fail "deploy: an empty password is not allowed; nothing was written"
    RESTIC_PASSWORD="$password" restic -r "$REPO" cat config >/dev/null 2>&1 || fail "$MSG_WRONG"
  else
    warn_copy
    attempts=0
    while :; do
      ask password "New restic repository password: "
      ask again "Repeat the password: "
      if [[ -n "$password" && "$password" == "$again" ]]; then break; fi
      attempts=$((attempts + 1))
      [[ "$attempts" -lt 5 ]] || fail "deploy: the passwords did not match or were empty 5 times; nothing was written"
      echo "deploy: the passwords did not match or were empty; try again" >&2
    done
    new_repo=1
  fi
  store_password "$password"
  password=""; again=""
fi

# Debian postinst creates /etc/default on first install and preserves it later.
dpkg -i "$ROOT/dist/onedrive-backup_$VERSION""_all.deb"

# The service user and the data directory exist now: create the repository and hand it to the service user.
if [[ "$new_repo" == 1 ]]; then
  restic -r "$REPO" --password-file "$PASSWORD_FILE" init
  chown -R onedrive-backup:onedrive-backup "$REPO"
  echo "deploy: restic repository initialised: $REPO"
  warn_copy
fi
