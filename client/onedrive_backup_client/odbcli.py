'''odbcli: the console command of the OneDrive Backup client, built on onedrive_backup_client.BackupClient.

It never talks to the server on its own: every subcommand calls the Python client, which is a thin wrapper over the
mcp-proxy-adapter JsonRpcClient. One subcommand per server command (help, info, snapshots, files, prepare, status,
delete, sites, libraries, discovery-status, download-begin, filter-options, search-files, suggest-names) with all its
arguments, plus health, fetch, download, call and download-link. stdout is JSON only. Exit codes: 0 success, 1 server
refusal or authentication failure, 2 usage error, 3 connection or local failure.

Connection options come before the subcommand and can also be given as ODBCLI_URL, ODBCLI_CA, ODBCLI_CERT,
ODBCLI_KEY, ODBCLI_TIMEOUT and ODBCLI_PASSWORD (or ONEDRIVE_BACKUP_PASSWORD), or in the JSON file of --config
(default ~/.config/onedrive-backup/client.json). Only the URL is required; the CA is optional, the client
certificate and key are optional all-or-none (both: mTLS, neither: HTTPS) and the password is optional (it is sent
as X-API-Key when set and never printed).
'''

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Any, Optional

from .api import BackupClient
from .errors import ClientError

SETTINGS = ('url', 'ca', 'cert', 'key', 'timeout', 'password')
REQUIRED = ('url',)
DEFAULT_CONFIG = Path.home() / '.config' / 'onedrive-backup' / 'client.json'


class _RemovedOption(argparse.Action):
    """A connection option that no longer exists (login, token): refuse it as an unrecognized argument, whatever follows."""

    def __call__(self, parser, namespace, values, option_string=None):
        parser.error('unrecognized arguments: %s' % option_string)


def _filters(sub: argparse.ArgumentParser, dates: bool = True) -> None:
    '''Add the site and date filter arguments of the filter commands to a subparser.'''
    sub.add_argument('--site-id', action='append', dest='site_ids', help='ticked site id; repeat for several sites')
    if dates:
        sub.add_argument('--date', action='append', dest='dates', help='ticked backup date YYYY-MM-DD; repeatable')


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog='odbcli', description='Command line of the OneDrive Backup service; JSON on stdout.')
    parser.add_argument('--config', help='JSON file with url, ca, cert, key, timeout or password')
    parser.add_argument('--url', help='service URL https://host:port')
    parser.add_argument('--ca', help='CA certificate that signed the server certificate')
    parser.add_argument('--cert', help='client certificate (mTLS); optional, all-or-none with --key')
    parser.add_argument('--key', help='client private key (mTLS); optional, all-or-none with --cert')
    parser.add_argument('--timeout', type=int, help='request timeout in seconds')
    parser.add_argument('--password', help='optional password, sent as X-API-Key when the service requires one')
    for removed in ('--login', '--token'):
        parser.add_argument(removed, action=_RemovedOption, nargs='?', help=argparse.SUPPRESS)
    cmds = parser.add_subparsers(dest='command', required=True)
    cmds.add_parser('help', help='server command help').add_argument('cmdname', nargs='?', help='command to describe')
    cmds.add_parser('info', help='server information').add_argument('--page', type=int, help='page number')
    cmds.add_parser('snapshots', help='list snapshots').add_argument('--limit', type=int, help='maximum items')
    sub = cmds.add_parser('files', help='list files of a snapshot')
    sub.add_argument('snapshot_id')
    sub.add_argument('--prefix', help='path prefix')
    sub.add_argument('--offset', type=int)
    sub.add_argument('--limit', type=int)
    sub = cmds.add_parser('prepare', help='stage an export of a snapshot or one file')
    sub.add_argument('snapshot_id')
    sub.add_argument('--path', help='file path inside the snapshot (file_path); the whole snapshot without it')
    cmds.add_parser('status', help='metadata of a staged export').add_argument('export_id')
    cmds.add_parser('delete', help='delete a staged export').add_argument('export_id')
    sub = cmds.add_parser('sites', help='list SharePoint sites')
    sub.add_argument('--limit', type=int)
    sub.add_argument('--offset', type=int)
    sub.add_argument('--query', help='site name filter')
    sub = cmds.add_parser('libraries', help='list document libraries of a site')
    sub.add_argument('site_id')
    sub.add_argument('--limit', type=int)
    sub.add_argument('--offset', type=int)
    cmds.add_parser('discovery-status', help='state of the SharePoint inventory')
    _filters(cmds.add_parser('filter-options', help='sites with backups and backup dates of the ticked sites'), dates=False)
    sub = cmds.add_parser('search-files', help='search files by site, backup date and name part (a star is a wildcard)')
    _filters(sub)
    sub.add_argument('--name-part', default='', help='name part: no star contains, a star anchors the pattern')
    sub.add_argument('--limit', type=int, default=100, help='page size 1..500')
    sub.add_argument('--offset', type=int, default=0, help='rows to skip')
    sub = cmds.add_parser('suggest-names', help='suggest file names for the typed text (2+ characters besides stars)')
    sub.add_argument('--text', required=True, help='typed text')
    _filters(sub)
    sub.add_argument('--limit', type=int, default=10, help='maximum names 1..20')
    cmds.add_parser('health', help='probe the service with help')
    sub = cmds.add_parser('fetch', help='download a staged export through the transfer service')
    sub.add_argument('export_id')
    sub.add_argument('--output', required=True, help='destination file')
    sub.add_argument('--force', action='store_true', help='replace an existing output')
    sub.add_argument('--delete-after', action='store_true', help='delete the export after a verified download')
    sub = cmds.add_parser('download', help='prepare, fetch and delete the export of a snapshot or one file')
    sub.add_argument('snapshot_id')
    sub.add_argument('--output', required=True, help='destination file')
    sub.add_argument('--path', help='file path inside the snapshot (file_path)')
    sub.add_argument('--force', action='store_true', help='replace an existing output')
    sub.add_argument('--keep-export', action='store_true', help='keep the staged export after the download')
    sub = cmds.add_parser('call', help='run any server command with a JSON parameter map')
    sub.add_argument('command_name', metavar='command', help='server command name')
    sub.add_argument('--params-json', default='{}', help='JSON object with the parameters')
    cmds.add_parser('download-link', help='print the temporary download link of a staged export').add_argument('export_id')
    cmds.add_parser('download-begin', help='register a transfer session of a staged export').add_argument('export_id')
    return parser


def _config(parser: argparse.ArgumentParser, path: Optional[str]) -> dict:
    given = path is not None
    target = Path(path).expanduser() if path is not None else DEFAULT_CONFIG
    if not target.is_file():
        if given:
            parser.error('config file not found: ' + str(target))
        return {}
    try:
        data = json.loads(target.read_text(encoding='utf-8'))
    except (OSError, ValueError) as exc:
        parser.error('config file unreadable: %s' % exc)
    if not isinstance(data, dict):
        parser.error('config file must hold a JSON object')
    return data


def _client(parser: argparse.ArgumentParser, args: argparse.Namespace) -> BackupClient:
    config = _config(parser, args.config)
    values: dict = {}
    for name in SETTINGS:
        values[name] = getattr(args, name) or os.environ.get('ODBCLI_' + name.upper()) or config.get(name)
    values['password'] = values['password'] or os.environ.get('ONEDRIVE_BACKUP_PASSWORD')
    missing = [name for name in REQUIRED if not values[name]]
    if missing:
        parser.error('missing connection settings: ' + ', '.join('--' + name for name in missing))
    try:
        values['timeout'] = int(values['timeout'] or 180)
    except (TypeError, ValueError):
        parser.error('timeout must be an integer')
    try:
        return BackupClient(**values)
    except ClientError as exc:
        parser.error(str(exc))


def _params(parser: argparse.ArgumentParser, text: str) -> dict:
    try:
        value = json.loads(text)
    except ValueError as exc:
        parser.error('--params-json is not valid JSON: %s' % exc)
    if not isinstance(value, dict):
        parser.error('--params-json must be a JSON object')
    return value


def _execute(client: BackupClient, args: argparse.Namespace, params: dict) -> Any:
    command = args.command
    if command == 'help':
        return client.help(args.cmdname)
    if command == 'health':
        return client.help()
    if command == 'info':
        return client.info(args.page)
    if command == 'snapshots':
        return client.backup_snapshots(args.limit)
    if command == 'files':
        return client.backup_list_files(args.snapshot_id, args.prefix, args.offset, args.limit)
    if command == 'prepare':
        return client.backup_prepare_download(args.snapshot_id, args.path)
    if command == 'status':
        return client.backup_download_status(args.export_id)
    if command == 'delete':
        return client.backup_delete_export(args.export_id)
    if command == 'sites':
        return client.backup_sites_list(args.limit, args.offset, args.query)
    if command == 'libraries':
        return client.backup_libraries_list(args.site_id, args.limit, args.offset)
    if command == 'discovery-status':
        return client.backup_discovery_status()
    if command == 'filter-options':
        return client.filter_options(args.site_ids)
    if command == 'search-files':
        return client.search_files(args.site_ids, args.dates, args.name_part, args.limit, args.offset)
    if command == 'suggest-names':
        return client.suggest_names(args.text, args.site_ids, args.dates, args.limit)
    if command == 'download-begin':
        return client.backup_download_begin(args.export_id)
    if command == 'download-link':
        return {'export_id': args.export_id, 'url': client.download_link(args.export_id)}
    if command == 'call':
        return client.call(args.command_name, params)
    if command == 'fetch':
        saved = client.fetch(args.export_id, args.output, overwrite=args.force, delete_after=args.delete_after)
    else:
        saved = client.download(args.snapshot_id, args.output, args.path, overwrite=args.force,
                                delete_after=not args.keep_export)
    return {'saved': str(saved), 'size_bytes': saved.stat().st_size}


def _failure(exc: ClientError) -> str:
    text = 'odbcli: ' + str(exc)
    if exc.code is not None and str(exc.code) not in text:
        text += ' (code %s)' % exc.code
    if isinstance(exc.data, dict) and exc.data:
        text += ' data=' + json.dumps(exc.data, ensure_ascii=False, sort_keys=True)[:400]
    return text


def main(argv: Optional[list] = None) -> int:
    parser = _parser()
    args = parser.parse_args(argv)
    params = _params(parser, args.params_json) if args.command == 'call' else {}
    client = _client(parser, args)
    try:
        result = _execute(client, args, params)
    except ClientError as exc:
        print(_failure(exc), file=sys.stderr)
        return 1 if exc.code is not None or type(exc).__name__ == 'ClientAuthenticationError' else 3
    print(json.dumps(result, indent=2, ensure_ascii=False))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
