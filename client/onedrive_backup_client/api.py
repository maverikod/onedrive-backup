'''Python client of the OneDrive Backup command API: a thin wrapper over the mcp-proxy-adapter JsonRpcClient.

The package owns no transport. Every command goes through JsonRpcClient.execute_command_unified (JSON-RPC over
server-auth HTTPS, POST /api/jsonrpc), the adapter transfer service moves downloads (/api/transfer/downloads), and
the temporary uuid4 link /downloads/<export_id>/<filename> is read through the HTTP client of the adapter.
The service is open: a configured password is sent as the X-API-Key header, none is sent otherwise. A client
certificate and its key are optional, all-or-none: with both the adapter client uses mTLS, without them HTTPS.
A downloaded file is verified (size and SHA256 of the export metadata) before it atomically replaces the output.
'''

from __future__ import annotations

import asyncio
import hashlib
import os
import tempfile
from pathlib import Path
from typing import Any, Awaitable, Callable, Optional
from urllib.parse import urlsplit

from mcp_proxy_adapter.client.jsonrpc_client.client import JsonRpcClient
from mcp_proxy_adapter.client.jsonrpc_client.exceptions import (
    ClientAuthenticationError as AdapterAuthenticationError,
    ClientError as AdapterError,
    ClientRemoteResponseError,
)

from .commands import CommandMethods
from .errors import ClientAuthenticationError, ClientError

TOKEN_HEADER = 'X-API-Key'
CHUNK = 1024 * 1024
PARTIAL_SUFFIX = '.part'


def _unpack(result: Any) -> Any:
    '''Return the data of a command result or raise the command error (success false).

    Args:
        result: The result object of the adapter.

    Returns:
        The data of the result.

    Raises:
        ClientError: The result is malformed or reports success false.
    '''
    if not isinstance(result, dict):
        raise ClientError('Malformed command result: ' + type(result).__name__)
    if result.get('success') is False:
        raw_error = result.get('error')
        error = raw_error if isinstance(raw_error, dict) else {}
        raise ClientError(str(error.get('message', 'command failed')), code=error.get('code'), data=error.get('data'))
    return result.get('data', result)


def _remote(exc: ClientRemoteResponseError) -> ClientError:
    '''Map an in-band JSON-RPC error of the adapter to a ClientError with code and data.

    Args:
        exc: The adapter error.

    Returns:
        The client error.
    '''
    details = exc.details if isinstance(exc.details, dict) else {}
    return ClientError(str(exc), code=details.get('code'), data=details.get('data'))


def _unlink(path: Path) -> None:
    '''Remove a temporary file when it exists.

    Args:
        path: The file.
    '''
    try:
        path.unlink()
    except FileNotFoundError:
        pass


def _digest(path: Path) -> tuple[int, str]:
    '''Return (size, sha256 hex) of a file read in chunks.

    Args:
        path: The file.

    Returns:
        The size in bytes and the lowercase hex SHA-256.
    '''
    sha, size = hashlib.sha256(), 0
    with open(path, 'rb') as handle:
        while True:
            block = handle.read(CHUNK)
            if not block:
                break
            sha.update(block)
            size += len(block)
    return size, sha.hexdigest()


class BackupClient(CommandMethods):
    '''Every command of the server as a method (CommandMethods), plus call, raw_call and the verified downloads.

    Attributes:
        url: The service URL without a trailing slash.
        ca: The CA certificate path or None.
        cert: The client certificate path (mTLS) or None.
        key: The client key path (mTLS) or None.
        timeout: The timeout of one operation in seconds.
        _token: The optional password sent as X-API-Key.
    '''

    def __init__(self, url: str, ca: Optional[str] = None, cert: Optional[str] = None, key: Optional[str] = None,
                 timeout: int = 180, password: Optional[str] = None) -> None:
        '''Validate the connection settings; nothing is sent.

        Args:
            url: The https URL of the service.
            ca: The CA certificate path, or None.
            cert: The client certificate path (all-or-none with key), or None.
            key: The client key path (all-or-none with cert), or None.
            timeout: The timeout of one operation in seconds.
            password: The optional password sent as the X-API-Key header, or None.
        '''
        parts = urlsplit(url or '')
        if parts.scheme != 'https' or not parts.hostname:
            raise ClientError('TLS is mandatory: URL must be https://host[:port]')
        if bool(cert) != bool(key):
            raise ClientError('cert and key are all-or-none: give both for mTLS or neither for HTTPS')
        self.url = url.rstrip('/')
        self.ca = str(ca) if ca else None
        self.cert: Optional[str] = str(cert) if cert and key else None
        self.key: Optional[str] = str(key) if cert and key else None
        self.timeout = timeout
        self._host, self._port = parts.hostname, parts.port or 443
        self._token: Optional[str] = password or None

    def __repr__(self) -> str:
        '''Describe the client without the password.

        Returns:
            The text.
        '''
        return 'BackupClient(url=%r, authenticated=%s)' % (self.url, self._token is not None)

    # transport: one JsonRpcClient per operation

    def _rpc(self) -> JsonRpcClient:
        '''Build the adapter client of one operation.

        Returns:
            The adapter client.
        '''
        return JsonRpcClient(
            protocol='mtls' if self.cert else 'https', host=self._host, port=self._port,
            token_header=TOKEN_HEADER if self._token else None, token=self._token,
            cert=self.cert, key=self.key, ca=self.ca, timeout=float(self.timeout))

    def _run(self, work: Callable[[JsonRpcClient], Awaitable[Any]]) -> Any:
        '''Run one coroutine with a fresh adapter client; map every adapter failure to a ClientError.

        Args:
            work: The coroutine function that receives the adapter client.

        Returns:
            Whatever the coroutine returns.
        '''
        async def runner() -> Any:
            rpc = self._rpc()
            try:
                return await work(rpc)
            finally:
                await rpc.close()
        try:
            return asyncio.run(runner())
        except AdapterAuthenticationError as exc:
            raise ClientAuthenticationError(str(exc), code=401) from exc
        except ClientRemoteResponseError as exc:
            raise _remote(exc) from exc
        except AdapterError as exc:
            raise ClientError(str(exc)) from exc
        except (OSError, ValueError) as exc:
            raise ClientError('%s: %s' % (type(exc).__name__, exc)) from exc

    @staticmethod
    async def _execute(rpc: JsonRpcClient, command: str, params: dict) -> Any:
        '''Run one command through the adapter client.

        Args:
            rpc: The adapter client.
            command: The command name.
            params: The parameter map.

        Returns:
            The data of the result.
        '''
        out = await rpc.execute_command_unified(command, params, expect_queue=False)
        return _unpack(out.get('result') if isinstance(out, dict) else None)

    # generic access

    def call(self, command: str, params: Optional[dict] = None) -> Any:
        '''Run any registered command; return its data or raise ClientError.

        Args:
            command: The command name.
            params: The parameter map or None.

        Returns:
            The data of the command result.
        '''
        if not isinstance(command, str) or not command:
            raise ClientError('command must be a non-empty string', code=-32602, data={'violation': 'type'})
        sent = {} if params is None else params
        if not isinstance(sent, dict):
            raise ClientError('params must be an object', code=-32602, data={'violation': 'type'})
        return self._run(lambda rpc: self._execute(rpc, command, sent))

    def raw_call(self, command: str, params_map: dict) -> Any:
        '''Send the parameter map unchanged (no client-side check) and report the server verdict.

        Args:
            command: The command name.
            params_map: The parameter map sent as it is.

        Returns:
            The data of the command result.
        '''
        async def send(rpc: JsonRpcClient) -> Any:
            envelope = await rpc.raw_parameter_call(command, params_map)
            if 'error' in envelope:
                error = envelope['error'] if isinstance(envelope['error'], dict) else {}
                raise ClientError(str(error.get('message', 'error')), code=error.get('code'), data=error.get('data'))
            return _unpack(envelope.get('result'))
        return self._run(send)

    # verified downloads

    @staticmethod
    def _destination(output: Any, overwrite: bool) -> Path:
        '''Resolve the output path and refuse an existing file unless overwrite is set.

        Args:
            output: The destination path.
            overwrite: True replaces an existing output.

        Returns:
            The resolved path.
        '''
        destination = Path(output).expanduser().resolve()
        if destination.exists() and not overwrite:
            raise ClientError('Output exists; use overwrite to replace it')
        return destination

    @staticmethod
    def _temp_path(destination: Path) -> Path:
        '''Create a temporary file next to the destination.

        Args:
            destination: The destination path.

        Returns:
            The temporary file.
        '''
        destination.parent.mkdir(parents=True, exist_ok=True)
        handle, name = tempfile.mkstemp(prefix='.onedrive-download-', dir=str(destination.parent))
        os.close(handle)
        return Path(name)

    @staticmethod
    def _commit(work: Path, destination: Path, meta: dict, overwrite: bool) -> None:
        '''Verify size and SHA256 against the export metadata, then replace the output atomically.

        Args:
            work: The downloaded temporary file.
            destination: The final path.
            meta: The export metadata with size_bytes and sha256.
            overwrite: True replaces an existing output.
        '''
        size, digest = _digest(work)
        if size != meta.get('size_bytes') or digest != meta.get('sha256'):
            raise ClientError('Download integrity mismatch: SHA256/size')
        if destination.exists() and not overwrite:
            raise ClientError('Output already exists')
        os.replace(work, destination)

    def download_link(self, export_id: str) -> str:
        '''Return the absolute temporary uuid4 link of a staged export.

        Args:
            export_id: The export.

        Returns:
            The link.
        '''
        link = self.backup_download_status(export_id).get('url')
        if not link:
            raise ClientError('The export has no download link (expired?)')
        return self.url + link

    def fetch(self, export_id: str, output: Any, *, overwrite: bool = False, delete_after: bool = False) -> Path:
        '''Download a staged export through the adapter transfer service (backup_download_begin).

        Args:
            export_id: The export.
            output: The destination path.
            overwrite: True replaces an existing output.
            delete_after: True deletes the export after a verified download.

        Returns:
            The saved path.
        '''
        destination = self._destination(output, overwrite)
        meta = self.backup_download_status(export_id)
        begin = self.backup_download_begin(export_id)
        if begin.get('checksum_value') != meta.get('sha256') or begin.get('size_bytes') != meta.get('size_bytes'):
            raise ClientError('The transfer session differs from the export metadata')
        work = self._temp_path(destination)
        try:
            async def pull(rpc: JsonRpcClient) -> None:
                await rpc.download_file(begin['transfer_id'], str(work))
            self._run(pull)
            self._commit(work, destination, meta, overwrite)
        finally:
            _unlink(work)
            _unlink(Path(str(work) + PARTIAL_SUFFIX))
        if delete_after:
            self.backup_delete_export(export_id)
        return destination

    def fetch_link(self, export_id: str, output: Any, *, overwrite: bool = False, delete_after: bool = False) -> Path:
        '''Download a staged export by its temporary link, with the same verification.

        Args:
            export_id: The export.
            output: The destination path.
            overwrite: True replaces an existing output.
            delete_after: True deletes the export after a verified download.

        Returns:
            The saved path.
        '''
        destination = self._destination(output, overwrite)
        meta = self.backup_download_status(export_id)
        link = meta.get('url')
        if not link:
            raise ClientError('The export has no download link (expired?)')
        work = self._temp_path(destination)
        try:
            async def pull(rpc: JsonRpcClient) -> None:
                http = await rpc.get_async_http_client()
                headers = {TOKEN_HEADER: self._token} if self._token else {}
                async with http.stream('GET', rpc.base_url + link, headers=headers) as response:
                    if response.status_code != 200:
                        raise ClientError('Download link refused: HTTP %d' % response.status_code, code=response.status_code)
                    with open(work, 'wb') as out:
                        async for block in response.aiter_bytes(CHUNK):
                            out.write(block)
            self._run(pull)
            self._commit(work, destination, meta, overwrite)
        finally:
            _unlink(work)
        if delete_after:
            self.backup_delete_export(export_id)
        return destination

    def download(self, snapshot_id: str, output: Any, file_path: Optional[str] = None, *,
                 overwrite: bool = False, delete_after: bool = True) -> Path:
        '''Prepare an export of a snapshot (or one file) and fetch it through the transfer service.

        Args:
            snapshot_id: The snapshot.
            output: The destination path.
            file_path: The file inside the snapshot, or None for the whole snapshot.
            overwrite: True replaces an existing output.
            delete_after: True deletes the export after the download.

        Returns:
            The saved path.
        '''
        destination = self._destination(output, overwrite)
        export_id = self.backup_prepare_download(snapshot_id, file_path)['export_id']
        try:
            saved = self.fetch(export_id, destination, overwrite=overwrite)
        except BaseException:
            if delete_after:
                try:
                    self.backup_delete_export(export_id)
                except ClientError:
                    pass
            raise
        if delete_after:
            self.backup_delete_export(export_id)
        return saved
