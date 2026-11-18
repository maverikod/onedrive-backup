# onedrive-backup-client

Standard-library-only Python API and CLI for the OneDrive Backup mTLS server.
TLS server-name verification and trusted client certificates are mandatory. CRL policy is enforced at the proxy.
Use `onedrive-backup-client --help` for all operations.

```bash
python3 -m pip install onedrive_backup_client-0.3.9-py3-none-any.whl
onedrive-backup-client --config client.json snapshots
onedrive-backup-client --config client.json files <snapshot_id>
onedrive-backup-client --config client.json download <snapshot_id> --path Documents/file.pdf --output file.pdf
onedrive-backup-client --config client.json download <snapshot_id> --output snapshot.tar.gz
```

