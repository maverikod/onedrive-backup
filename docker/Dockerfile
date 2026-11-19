FROM python:3.12-slim-bookworm
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 \
    ONEDRIVE_BACKUP_CONFIG=/config/backup.json ONEDRIVE_BACKUP_DATA=/data
RUN apt-get update && apt-get install -y --no-install-recommends \
    ca-certificates restic rclone tini \
 && rm -rf /var/lib/apt/lists/*
COPY docker/requirements-server.txt /tmp/requirements-server.txt
RUN python -m pip install --no-cache-dir -r /tmp/requirements-server.txt
COPY src/onedrive_backup.py /opt/onedrive-backup/onedrive_backup.py
COPY src/onedrive_api/ /opt/onedrive-backup/onedrive_api/
COPY VERSION /opt/onedrive-backup/VERSION
RUN groupadd -g 1000 onedriveagent && useradd -u 1000 -g onedriveagent -s /usr/sbin/nologin -M onedriveagent \
    && mkdir -p /config /data /secrets \
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

