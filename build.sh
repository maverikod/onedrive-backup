#!/usr/bin/env bash
set -Eeuo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$ROOT"
VERSION="$(tr -d '[:space:]' < VERSION)"
IMAGE="vasilyvz/onedrive-backup:$VERSION"
STEP=preflight
trap 'rc=$?; if [ "$rc" -ne 0 ]; then echo "FAILED $STEP: $rc" >&2; fi' EXIT
STEP=tests
mkdir -p .test-run
TMPDIR="$ROOT/.test-run" PYTHONPATH=src python3 -m unittest discover -s tests -p 'test*.py' -v
rmdir .test-run 2>/dev/null || true
STEP=package-client
python3 -m venv .build-venv
.build-venv/bin/python -m pip install -q build twine
mkdir -p dist/client
.build-venv/bin/python -m build --sdist --wheel --outdir dist/client client
.build-venv/bin/python -m twine check --strict dist/client/*
STEP=docker-build
docker build -f docker/Dockerfile -t "$IMAGE" -t 'vasilyvz/onedrive-backup:latest' .
STEP=deb-build
bash scripts/build-deb.sh
STEP=registry-credentials
CREDENTIALS="$ROOT/.env"
if [ -f /etc/default/onedrive-backup ]; then
  VALUE="$(sed -n 's/^ONEDRIVE_CREDENTIALS_FILE=//p' /etc/default/onedrive-backup | head -1)"
  if [ -n "$VALUE" ]; then CREDENTIALS="$VALUE"; fi
fi
DOCKER_USER=''; DOCKER_PAT=''; PYPI_TOKEN=''; SKIP_PYPI=0
if [ -r "$CREDENTIALS" ]; then
  while IFS= read -r line || [ -n "$line" ]; do
    case "$line" in
      DOCKER_USER=*) DOCKER_USER="${line#DOCKER_USER=}" ;;
      DOCKER_PAT=*) DOCKER_PAT="${line#DOCKER_PAT=}" ;;
      PYPI_TOKEN=*) PYPI_TOKEN="${line#PYPI_TOKEN=}" ;;
      dontpubpypi=*) SKIP_PYPI=1 ;;
    esac
  done < "$CREDENTIALS"
fi
DOCKER_USER="${DOCKER_USER#\"}"; DOCKER_USER="${DOCKER_USER%\"}"
DOCKER_PAT="${DOCKER_PAT#\"}"; DOCKER_PAT="${DOCKER_PAT%\"}"
PYPI_TOKEN="${PYPI_TOKEN#\"}"; PYPI_TOKEN="${PYPI_TOKEN%\"}"
if [ -n "$DOCKER_PAT" ]; then
  : "${DOCKER_USER:?DOCKER_USER missing}"
  printf '%s\n' "$DOCKER_PAT" | docker login -u "$DOCKER_USER" --password-stdin >/dev/null
fi
unset DOCKER_USER DOCKER_PAT
STEP=docker-push
docker push "$IMAGE"
docker push 'vasilyvz/onedrive-backup:latest'
STEP=pypi
if [ "$SKIP_PYPI" -eq 0 ] && [ -n "$PYPI_TOKEN" ]; then
  if ! TWINE_USERNAME=__token__ TWINE_PASSWORD="$PYPI_TOKEN" .build-venv/bin/python -m twine upload --non-interactive dist/client/*; then
    echo 'PyPI upload failed: client remains available locally' >&2
  fi
else
  echo 'PyPI credentials unavailable: client built locally only'
fi
unset PYPI_TOKEN
if [ "$(id -u)" -eq 0 ]; then
  STEP=deploy
  if ! bash docker/deploy.sh; then
    echo '[DEFERRED] Production container not started; TLS certificates and mounted storage required' >&2
  fi
fi
echo 'Release finished. For later deployment: sudo bash docker/deploy.sh'
