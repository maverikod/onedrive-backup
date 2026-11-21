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

from .errors import ClientAuthenticationError, ClientError

TOKEN_HEADER = 'X-API-Key'
CHUNK = 1024 * 1024
PARTIAL_SUFFIX = '.part'


def _unpack(result: Any) -> Any:
    '''Return the data of a command result or raise the command error (success false).'''
    if not isinstance(result, dict):
        raise ClientError('Malformed command result: ' + type(result).__name__)
    if result.get('success') is False:
        raw_error = result.get('error')
        error = raw_error if isinstance(raw_error, dict) else {}
        raise ClientError(str(error.get('message', 'command failed')), code=error.get('code'), data=error.get('data'))
    return result.get('data', result)


def _remote(exc: ClientRemoteResponseError) -> ClientError:
    '''Map an in-band JSON-RPC error of the adapter to a ClientError with code and data.'''
    details = exc.details if isinstance(exc.details, dict) else {}
    return ClientError(str(exc), code=details.get('code'), data=details.get('data'))


def _unlink(path: Path) -> None:
    '''Remove a temporary file when it exists.'''
    try:
        path.unlink()
    except FileNotFoundError:
        pass


def _digest(path: Path) -> tuple[int, str]:
    '''Return (size, sha256 hex) of a file read in chunks.'''
    sha, size = hashlib.sha256(), 0
    with open(path, 'rb') as handle:
        while True:
            block = handle.read(CHUNK)
            if not block:
                break
            sha.update(block)
            size += len(block)
    return size, sha.hexdigest()


class BackupClient:
    '''Every command of the server as a method, plus call, raw_call and the verified downloads.'''

    def __init__(self, url: str, ca: Optional[str] = None, cert: Optional[str] = None, key: Optional[str] = None,
                 timeout: int = 180, password: Optional[str] = None) -> None:
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
        return 'BackupClient(url=%r, authenticated=%s)' % (self.url, self._token is not None)

    # transport: one JsonRpcClient per operation

    def _rpc(self) -> JsonRpcClient:
        return JsonRpcClient(
            protocol='mtls' if self.cert else 'https', host=self._host, port=self._port,
            token_header=TOKEN_HEADER if self._token else None, token=self._token,
            cert=self.cert, key=self.key, ca=self.ca, timeout=float(self.timeout))

    def _run(self, work: Callable[[JsonRpcClient], Awaitable[Any]]) -> Any:
        '''Run one coroutine with a fresh adapter client; map every adapter failure to a ClientError.'''
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
        out = await rpc.execute_command_unified(command, params, expect_queue=False)
        return _unpack(out.get('result') if isinstance(out, dict) else None)

    # generic access

    def call(self, command: str, params: Optional[dict] = None) -> Any:
        '''Run any registered command; return its data or raise ClientError.'''
        if not isinstance(command, str) or not command:
            raise ClientError('command must be a non-empty string', code=-32602, data={'violation': 'type'})
        sent = {} if params is None else params
        if not isinstance(sent, dict):
            raise ClientError('params must be an object', code=-32602, data={'violation': 'type'})
        return self._run(lambda rpc: self._execute(rpc, command, sent))

    def raw_call(self, command: str, params_map: dict) -> Any:
        '''Send the parameter map unchanged (no client-side check) and report the server verdict.'''
        async def send(rpc: JsonRpcClient) -> Any:
            envelope = await rpc.raw_parameter_call(command, params_map)
            if 'error' in envelope:
                error = envelope['error'] if isinstance(envelope['error'], dict) else {}
                raise ClientError(str(error.get('message', 'error')), code=error.get('code'), data=error.get('data'))
            return _unpack(envelope.get('result'))
        return self._run(send)

    def _command(self, command: str, **params: Any) -> Any:
        return self.call(command, {k: v for k, v in params.items() if v is not None})

    # one method per server command, named like the command

    def help(self, cmdname: Optional[str] = None) -> Any:
        return self._command('help', cmdname=cmdname)

    def info(self, page: Optional[int] = None) -> Any:
        return self._command('info', page=page)

    def backup_snapshots(self, limit: Optional[int] = None) -> Any:
        return self._command('backup_snapshots', limit=limit)

    def backup_list_files(self, snapshot_id: str, prefix: Optional[str] = None, offset: Optional[int] = None,
                          limit: Optional[int] = None) -> Any:
        return self._command('backup_list_files', snapshot_id=snapshot_id, prefix=prefix, offset=offset, limit=limit)

    def backup_prepare_download(self, snapshot_id: str, file_path: Optional[str] = None) -> Any:
        return self._command('backup_prepare_download', snapshot_id=snapshot_id, file_path=file_path)

    def backup_download_status(self, export_id: str) -> Any:
        return self._command('backup_download_status', export_id=export_id)

    def backup_delete_export(self, export_id: str) -> Any:
        return self._command('backup_delete_export', export_id=export_id)

    def backup_sites_list(self, limit: Optional[int] = None, offset: Optional[int] = None,
                          query: Optional[str] = None) -> Any:
        return self._command('backup_sites_list', limit=limit, offset=offset, query=query)

    def backup_libraries_list(self, site_id: str, limit: Optional[int] = None, offset: Optional[int] = None) -> Any:
        return self._command('backup_libraries_list', site_id=site_id, limit=limit, offset=offset)

    def backup_discovery_status(self) -> Any:
        return self._command('backup_discovery_status')

    def backup_download_begin(self, export_id: str) -> Any:
        return self._command('backup_download_begin', export_id=export_id)

    def filter_options(self, site_ids: Optional[list] = None) -> Any:
        '''Sites that have indexed snapshots and the backup dates of the ticked sites (backup_filter_options).'''
        return self._command('backup_filter_options', site_ids=site_ids)

    def search_files(self, site_ids: Optional[list] = None, dates: Optional[list] = None, name_part: str = '',
                     limit: int = 100, offset: int = 0) -> Any:
        '''Files of the ticked sites and dates whose name matches, star is a wildcard (backup_search_files).'''
        return self._command('backup_search_files', site_ids=site_ids or None, dates=dates or None,
                             name_part=name_part or None, limit=limit, offset=offset)

    def suggest_names(self, text: str, site_ids: Optional[list] = None, dates: Optional[list] = None,
                      limit: int = 10) -> Any:
        '''Distinct file names for the autocomplete list (backup_suggest_names).'''
        return self._command('backup_suggest_names', text=text, site_ids=site_ids or None, dates=dates or None, limit=limit)

    # verified downloads

    @staticmethod
    def _destination(output: Any, overwrite: bool) -> Path:
        destination = Path(output).expanduser().resolve()
        if destination.exists() and not overwrite:
            raise ClientError('Output exists; use overwrite to replace it')
        return destination

    @staticmethod
    def _temp_path(destination: Path) -> Path:
        destination.parent.mkdir(parents=True, exist_ok=True)
        handle, name = tempfile.mkstemp(prefix='.onedrive-download-', dir=str(destination.parent))
        os.close(handle)
        return Path(name)

    @staticmethod
    def _commit(work: Path, destination: Path, meta: dict, overwrite: bool) -> None:
        '''Verify size and SHA256 against the export metadata, then replace the output atomically.'''
        size, digest = _digest(work)
        if size != meta.get('size_bytes') or digest != meta.get('sha256'):
            raise ClientError('Download integrity mismatch: SHA256/size')
        if destination.exists() and not overwrite:
            raise ClientError('Output already exists')
        os.replace(work, destination)

    def download_link(self, export_id: str) -> str:
        '''Return the absolute temporary uuid4 link of a staged export.'''
        link = self.backup_download_status(export_id).get('url')
        if not link:
            raise ClientError('The export has no download link (expired?)')
        return self.url + link

    def fetch(self, export_id: str, output: Any, *, overwrite: bool = False, delete_after: bool = False) -> Path:
        '''Download a staged export through the adapter transfer service (backup_download_begin).'''
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
        '''Download a staged export by its temporary link, with the same verification.'''
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
        '''Prepare an export of a snapshot (or one file) and fetch it through the transfer service.'''
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
