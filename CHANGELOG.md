## 0.3.3 — MCP Proxy method discovery
- Restore the restricted GET /commands endpoint required for proxy registration.
- Continue filtering all privileged filesystem, admin, and transfer endpoints.
- Verify the real production container registers successfully in MCP Proxy.
- Exclude generated, root-owned client/build from syntax verification.
- Clean disposable build directories after successful release and allow Debian first-time installation without a pre-existing /etc/default file.

## 0.3.2 — Debian-owned deployment and proxy registration
- Debian postinst installs certificates using paths from /etc/default and checks TLS before deployment.
- Debian package now installs its required docker-run.sh runtime helper; build failures no longer hide deployment failures.
- Docker Hub credentials read from a root-only external file, never packaged.
- Restricted internal FastAPI scaffold can register without an admin password, OneDrive credentials, or backup disk.
- Browser login and backup operations are blocked while in scaffold mode.

## 0.3.1 — internal network and delegated CRL (2026-11-14)
- Remove CRL validation and CRL file requirements from server, client, and deployment; delegate revocation handling to MCP Proxy.
- Keep mandatory mTLS trust validation for internal FastAPI and certificate-verified proxy registration.
- Remove host port publication: API/UI reachable only on the smart-assistant Docker network.
- Update mTLS smoke test, config contract, client configuration, and operational documentation.
- Exclude Python bytecode and old-version wheels from release artifacts.

## 0.3.0
- Dual-use CN=onedrive-backup certificate signed by MCP Proxy CA, used for registration and server TLS.
- FastAPI web dashboard, admin login via independent password hash file and protected session.
- Certificate preflight and mTLS certificate import from local mtls-certs directory.
- Debian password setup CLI and browser API regression tests.

# Changelog

## 0.1.1 — 2026-11-14
- Fix Debian 12/Ubuntu system-user creation: explicit nologin shell.
- Document noexec /tmp handling in CAS test sandbox.

## 0.1.0 — 2026-11-14
- First Debian package for Ubuntu/Debian with system user, systemd service/timer and safe configuration.
- OneDrive Business OAuth via rclone, encrypted restic snapshots, integrity checks, dry-run and retention.
- Integration tests with mock rclone/restic; package validation.

## 0.2.0 — mTLS production API
- Containerized API on mcp-proxy-adapter 8.11.15.
- Read-only backup browsing and temporary exports; streaming download client.
- Certificate revocation checks on server and client.
- Docker Hub image, Debian package, systemd and client distribution.
- Smart Assistant proxy registration and one verified pipeline.
