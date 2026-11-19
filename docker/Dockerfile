# rclone: the Debian package is too old (v1.60.1 has no OneDrive client_credentials flow, which arrived in v1.69.0).
# Install the official release, pinned by version and verified against the published SHA256SUMS of that release.
# The build arguments must not start with RCLONE_: rclone reads RCLONE_<FLAG> environment variables.
ARG OFFICIAL_RCLONE_VERSION=1.76.0
ARG OFFICIAL_RCLONE_SHA256=b00f00b3266c3764413afe599d3ec316f6f43b3e0ea8a0bc1d186d2133e46df7

FROM python:3.12-slim-bookworm AS rclone-fetch
ARG OFFICIAL_RCLONE_VERSION
ARG OFFICIAL_RCLONE_SHA256
RUN apt-get update && apt-get install -y --no-install-recommends ca-certificates curl unzip \
 && rm -rf /var/lib/apt/lists/*
RUN set -eu; \
    zip="rclone-v${OFFICIAL_RCLONE_VERSION}-linux-amd64.zip"; \
    base="https://downloads.rclone.org/v${OFFICIAL_RCLONE_VERSION}"; \
    cd /tmp; \
    curl -fsSLO "${base}/${zip}"; \
    curl -fsSL -o SHA256SUMS "${base}/SHA256SUMS"; \
    grep " ${zip}\$" SHA256SUMS > zip.sha256; \
    test "$(wc -l < zip.sha256)" = 1; \
    sha256sum -c zip.sha256; \
    echo "${OFFICIAL_RCLONE_SHA256}  ${zip}" | sha256sum -c -; \
    unzip -j "${zip}" "rclone-v${OFFICIAL_RCLONE_VERSION}-linux-amd64/rclone" -d /out; \
    chmod 0755 /out/rclone; \
    /out/rclone version

FROM python:3.12-slim-bookworm
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 \
    ONEDRIVE_BACKUP_CONFIG=/config/backup.json ONEDRIVE_BACKUP_DATA=/data
RUN apt-get update && apt-get install -y --no-install-recommends \
    ca-certificates restic tini \
 && rm -rf /var/lib/apt/lists/*
COPY --from=rclone-fetch /out/rclone /usr/bin/rclone
COPY docker/requirements-server.txt /tmp/requirements-server.txt
RUN python -m pip install --no-cache-dir -r /tmp/requirements-server.txt
COPY src/onedrive_backup.py /opt/onedrive-backup/onedrive_backup.py
COPY src/onedrive_api/ /opt/onedrive-backup/onedrive_api/
COPY VERSION /opt/onedrive-backup/VERSION
RUN groupadd -g 1000 onedriveagent && useradd -u 1000 -g onedriveagent -s /usr/sbin/nologin -M onedriveagent \
    && mkdir -p /config /data /secrets /rclone-state \
    && chmod 755 /opt/onedrive-backup
WORKDIR /opt/onedrive-backup
ENV PYTHONPATH=/opt/onedrive-backup
# The container runs as the host service uid, which has no passwd entry, so HOME is / and restic would try
# to create /.cache. Point restic (and rclone through XDG) at a cache directory the service user can create.
ENV RESTIC_CACHE_DIR=/tmp/restic-cache XDG_CACHE_HOME=/tmp/cache
USER 1000:1000
EXPOSE 8050
ENTRYPOINT ["/usr/bin/tini", "--"]
CMD ["python", "-m", "onedrive_api.server", "--config", "/config/server.json", "--backup-config", "/config/backup.json", "--data", "/data"]
