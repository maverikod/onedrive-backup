# onedrive-backup-client

Python client and the `odbcli` console command for the OneDrive Backup mTLS server.
The client is a thin wrapper over the `mcp-proxy-adapter` `JsonRpcClient` (no own TLS or HTTP transport); it
uses the server command API (`POST /api/jsonrpc`): one method per command (`help`, `info`, `backup_snapshots`,
`backup_list_files`, `backup_prepare_download`, `backup_download_status`, `backup_delete_export`,
`backup_sites_list`, `backup_libraries_list`, `backup_discovery_status`, `backup_download_begin`) plus `call`
and `raw_call`. Trusted CA, server-name verification and the client certificate are mandatory.
Authentication: login and password (token base64(login:password)) or a ready token.

```bash
python3 -m pip install onedrive_backup_client-0.3.11-py3-none-any.whl
odbcli --config client.json snapshots
odbcli --config client.json files <snapshot_id>
odbcli --config client.json download <snapshot_id> --path Documents/file.pdf --output file.pdf
odbcli --config client.json download-link <export_id>
odbcli --config client.json fetch <export_id> --output snapshot.tar.gz
odbcli --help
```

Downloads (`fetch`, `fetch_link`, `download`) verify the size and SHA-256 of the export and replace the output atomically.
