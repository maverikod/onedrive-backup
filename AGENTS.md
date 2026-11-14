# OneDrive Backup — project and code standards

- Production-only service, no dev instance and no insecure HTTP fallback.
- One source of version: VERSION. Docker image, Debian package and client
  must use the identical release version.
- CAS project ID: f6130c8b-1fde-4a35-bdae-e857dfbd6555.
  Git remote: git@github.com:maverikod/onedrive-backup.git, branch cas.
- Inspect changes before writing. Git staging/commit/push only via CAS Git commands.
- The single authoritative verification entrypoint is python -m pipeline.
  After image build, run python -m pipeline smoke_mtls.
- Release entrypoint build.sh: tests, client wheel/sdist, Docker image,
  versioned Debian package, Docker Hub, PyPI if authorized or local wheel.
- Production deploy entrypoint docker/deploy.sh. Never launch an insecure
  service when certificates or backup mount are unavailable.
- The local .env is ignored by Git and Docker. Deployment copies it to
  /var/lib/onedrive-backup/credentials/.env on HOST (0600). The public
  /etc/default/onedrive-backup contains only its pathname and nonsecret options.
- mTLS uses trusted CA and one server/client certificate pair; revocation policy is managed by MCP Proxy. FastAPI is restricted to the internal Docker network.
  Real certificates are never committed or included in build artifacts.
- Proxy registration is automatic using mcp-proxy:3004 on smart-assistant.
  Data volume /srv/backup/onedrive must be backed by mounted /srv/backup.
- The remote API permits read-only browsing and bounded temporary exports
  identified by opaque IDs; no arbitrary file downloads or adapter admin RPCs.
- Python client exposes the complete application REST surface and verifies
  downloaded file size and SHA256 before atomically replacing the output.
- Stop on test errors and report them. All deployments are fail-closed.

