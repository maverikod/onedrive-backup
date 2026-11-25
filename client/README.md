# onedrive-backup-client

Python client and the `odbcli` console command for the OneDrive Backup service (server-auth HTTPS).
The client is a thin wrapper over the `mcp-proxy-adapter` `JsonRpcClient` (no own TLS or HTTP transport); it
uses the server command API (`POST /api/jsonrpc`): one method per command (`help`, `info`, `backup_snapshots`,
`backup_list_files`, `backup_prepare_download`, `backup_download_status`, `backup_delete_export`,
`backup_sites_list`, `backup_libraries_list`, `backup_discovery_status`, `backup_download_begin`, the file filter
`filter_options`, `search_files`, `suggest_names` and the folder tree `folder_children`) plus `call`
and `raw_call`. `search_files` and `suggest_names` take the optional folder scope `site_id`, `drive_id`, `dir`,
`recursive`; `folder_children` lists the children of a site, library or folder with their file counts. The trusted CA
and server-name verification apply; the client certificate and key are optional,
all-or-none (both: mTLS, neither: HTTPS). The service is open for now; an optional `password` is sent as the
`X-API-Key` header when configured (`--password`, `ONEDRIVE_BACKUP_PASSWORD` or the `password` config key) and is never printed.

```bash
python3 -m pip install onedrive_backup_client-0.3.28-py3-none-any.whl
odbcli --config client.json snapshots
odbcli --config client.json files <snapshot_id>
odbcli --config client.json download <snapshot_id> --path Documents/file.pdf --output file.pdf
odbcli --config client.json download-link <export_id>
odbcli --config client.json fetch <export_id> --output snapshot.tar.gz
odbcli --config client.json folder-children --site-id <site> --drive-id <library> --dir <folder>
odbcli --config client.json search-files --site-id <site> --drive-id <library> --dir <folder> --recursive
odbcli --config client.json schedule-get
odbcli --config client.json schedule-set --file schedule.cron --expected-revision <revision> --dry-run
odbcli --config client.json schedule-status
odbcli --help
```

Downloads (`fetch`, `fetch_link`, `download`) verify the size and SHA-256 of the export and replace the output atomically.
