"""mTLS client with verified certificate chain and streamed downloads."""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import ssl
import tempfile
from urllib import error, parse, request


class ClientError(Exception):
    """Backup API connection, protocol or integrity failure."""


class BackupClient:
    """Every published REST operation (including bounded export downloads)."""

    def __init__(self, url: str, ca: str, cert: str, key: str,
                 timeout: int = 180) -> None:
        self.url = url.rstrip("/")
        if not self.url.startswith("https://"):
            raise ClientError("TLS is mandatory: URL must start with https://")
        self.timeout = timeout
        context = ssl.create_default_context(cafile=ca)
        context.minimum_version = ssl.TLSVersion.TLSv1_2
        context.load_cert_chain(certfile=cert, keyfile=key)
        context.check_hostname = True
        self.context = context

    def _request(self, method: str, path: str, payload: dict | None = None):
        data = None if payload is None else json.dumps(payload).encode("utf-8")
        req = request.Request(
            self.url + path, data=data, method=method,
            headers={"Content-Type": "application/json", "Accept": "application/json"},
        )
        try:
            return request.urlopen(req, context=self.context, timeout=self.timeout)
        except error.HTTPError as exc:
            body = exc.read(2048).decode("utf-8", "replace")
            raise ClientError("HTTP " + str(exc.code) + ": " + body) from exc
        except (OSError, ssl.SSLError) as exc:
            raise ClientError("HTTPS connection failed: " + str(exc)) from exc

    def _json(self, method: str, path: str, payload: dict | None = None) -> dict:
        with self._request(method, path, payload) as resp:
            value = json.load(resp)
        if not isinstance(value, dict):
            raise ClientError("Expected JSON object from backup API")
        return value

    def health(self) -> dict:
        return self._json("GET", "/api/v1/health")

    def snapshots(self, limit: int = 100) -> dict:
        return self._json("GET", "/api/v1/snapshots?" +
                          parse.urlencode({"limit": limit}))

    def files(self, snapshot_id: str, prefix: str = "", offset: int = 0,
              limit: int = 1000) -> dict:
        url = "/api/v1/snapshots/" + parse.quote(snapshot_id, safe="") + "/files?"
        return self._json("GET", url +
                          parse.urlencode({"prefix": prefix, "offset": offset, "limit": limit}))

    def prepare(self, snapshot_id: str, file_path: str | None = None) -> dict:
        return self._json("POST", "/api/v1/exports",
                          {"snapshot_id": snapshot_id, "file_path": file_path})

    def status(self, export_id: str) -> dict:
        return self._json("GET", "/api/v1/exports/" +
                          parse.quote(export_id, safe="") + "/status")

    def delete(self, export_id: str) -> dict:
        return self._json("DELETE", "/api/v1/exports/" +
                          parse.quote(export_id, safe=""))

    def fetch(self, export_id: str, output: str | Path,
              *, overwrite: bool = False, delete_after: bool = False) -> Path:
        """Stream to a temporary file, verify SHA256, rename atomically."""
        destination = Path(output).expanduser().resolve()
        if destination.exists() and not overwrite:
            raise ClientError("Output exists; use --force to overwrite")
        meta = self.status(export_id)
        destination.parent.mkdir(parents=True, exist_ok=True)
        work_path: Path | None = None
        total = 0
        digest = hashlib.sha256()
        try:
            with tempfile.NamedTemporaryFile(
                prefix=".onedrive-download-", dir=destination.parent, delete=False
            ) as fp:
                work_path = Path(fp.name)
                with self._request("GET", "/api/v1/exports/" +
                                   parse.quote(export_id, safe="")) as response:
                    while True:
                        chunk = response.read(1024 * 1024)
                        if not chunk:
                            break
                        fp.write(chunk)
                        digest.update(chunk)
                        total += len(chunk)
            if total != meta["size_bytes"] or digest.hexdigest() != meta["sha256"]:
                raise ClientError("Download integrity mismatch: SHA256/size")
            if destination.exists() and not overwrite:
                raise ClientError("Output already exists")
            os.replace(work_path, destination)
            work_path = None
        finally:
            if work_path is not None:
                work_path.unlink(missing_ok=True)
        if delete_after:
            self.delete(export_id)
        return destination

    def download(self, snapshot_id: str, output: str | Path,
                 file_path: str | None = None, *, overwrite: bool = False,
                 delete_after: bool = True) -> Path:
        meta = self.prepare(snapshot_id, file_path)
        return self.fetch(meta["export_id"], output,
                          overwrite=overwrite, delete_after=delete_after)

