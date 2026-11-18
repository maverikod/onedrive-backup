'''Client and odbcli tests without external services: the adapter JsonRpcClient is replaced by a fake.'''

from __future__ import annotations

import contextlib
import hashlib
import io
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'client'))
from mcp_proxy_adapter.client.jsonrpc_client.exceptions import ClientAuthenticationError as AdapterAuth
from mcp_proxy_adapter.client.jsonrpc_client.exceptions import ClientRemoteResponseError
from onedrive_backup_client import BackupClient, ClientAuthenticationError, ClientError, odbcli

PAYLOAD = b'hello from an encrypted snapshot'
META = {'export_id': 'a' * 32, 'filename': 'f.bin', 'size_bytes': len(PAYLOAD),
        'sha256': hashlib.sha256(PAYLOAD).hexdigest(), 'url': '/downloads/' + 'a' * 32 + '/f.bin'}


class FakeRpc:
    '''Stands in for JsonRpcClient: records commands, answers from a table, writes the transfer payload.'''

    def __init__(self, answers=None, payload=PAYLOAD, fail=None):
        self.answers, self.payload, self.fail, self.calls = answers or {}, payload, fail, []
        self.base_url = 'https://onedrive-backup:8050'

    async def execute_command_unified(self, command, params=None, **options):
        self.calls.append((command, dict(params or {}), options))
        if self.fail is not None:
            raise self.fail
        return {'mode': 'immediate', 'result': self.answers[command]}

    async def raw_parameter_call(self, command, params):
        self.calls.append((command, dict(params), {'raw': True}))
        return self.answers[command]

    async def download_file(self, transfer_id, destination):
        self.calls.append(('download_file', {'transfer_id': transfer_id}, {}))
        Path(destination).write_bytes(self.payload)

    async def close(self):
        return None


def make(rpc, **extra):
    client = BackupClient('https://onedrive-backup:8050', 'ca', 'cert', 'key', 5, **extra)
    patcher = patch.object(BackupClient, '_rpc', return_value=rpc)
    patcher.start()
    return client, patcher


def ok(data):
    return {'success': True, 'data': data}


class ClientTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.dest = Path(self.tmp.name) / 'download.bin'
        self.begin = {'transfer_id': 't1', 'size_bytes': META['size_bytes'], 'checksum_value': META['sha256']}

    def client(self, rpc, **extra):
        client, patcher = make(rpc, **extra)
        self.addCleanup(patcher.stop)
        return client

    def test_url_must_be_https(self):
        with self.assertRaisesRegex(ClientError, 'TLS is mandatory'):
            BackupClient('http://localhost:8050', 'ca', 'cert', 'key')

    def test_mtls_material_is_mandatory(self):
        with self.assertRaisesRegex(ClientError, 'mTLS is mandatory'):
            BackupClient('https://onedrive-backup:8050', '', 'cert', 'key')

    def test_login_and_password_form_the_token(self):
        client = BackupClient('https://h:1', 'ca', 'cert', 'key', login='user', password='secret')
        self.assertEqual(client._token, 'dXNlcjpzZWNyZXQ=')
        self.assertNotIn('secret', repr(client))
        with self.assertRaises(ClientError):
            BackupClient('https://h:1', 'ca', 'cert', 'key', login='user')
        with self.assertRaises(ClientError):
            BackupClient('https://h:1', 'ca', 'cert', 'key', login='a:b', password='x')
        self.assertEqual(BackupClient('https://h:1', 'ca', 'cert', 'key', token='ready')._token, 'ready')

    def test_methods_send_only_supplied_parameters(self):
        rpc = FakeRpc({'backup_list_files': ok({'items': []})})
        self.assertEqual(self.client(rpc).backup_list_files('abcdef12', prefix='dir', limit=5), {'items': []})
        self.assertEqual(rpc.calls[0][:2], ('backup_list_files', {'snapshot_id': 'abcdef12', 'prefix': 'dir', 'limit': 5}))
        self.assertIs(rpc.calls[0][2]['expect_queue'], False)

    def test_command_error_carries_code(self):
        rpc = FakeRpc({'backup_snapshots': {'success': False, 'error': {'code': 503, 'message': 'scaffold'}}})
        with self.assertRaises(ClientError) as raised:
            self.client(rpc).backup_snapshots()
        self.assertEqual(raised.exception.code, 503)

    def test_rpc_error_carries_code_and_violation(self):
        failure = ClientRemoteResponseError('JSON-RPC error', details={'code': -32602, 'data': {'violation': 'unknown'}})
        with self.assertRaises(ClientError) as raised:
            self.client(FakeRpc(fail=failure)).call('help', {'no_such': 1})
        self.assertEqual((raised.exception.code, raised.exception.data['violation']), (-32602, 'unknown'))

    def test_401_is_authentication_error(self):
        with self.assertRaises(ClientAuthenticationError):
            self.client(FakeRpc(fail=AdapterAuth('HTTP 401'))).help()

    def test_raw_call_reports_error_envelope(self):
        envelope = {'error': {'code': -32602, 'message': 'bad', 'data': {'violation': 'type'}}}
        with self.assertRaises(ClientError) as raised:
            self.client(FakeRpc({'help': envelope})).raw_call('help', {'cmdname': 5})
        self.assertEqual((raised.exception.code, raised.exception.data['violation']), (-32602, 'type'))

    def test_call_rejects_non_object_params(self):
        with self.assertRaises(ClientError):
            self.client(FakeRpc()).call('help', ['x'])

    def test_correct_download_verified_and_deleted(self):
        rpc = FakeRpc({'backup_download_status': ok(META), 'backup_download_begin': ok(self.begin),
                       'backup_delete_export': ok({'deleted': True})})
        result = self.client(rpc).fetch(META['export_id'], self.dest, delete_after=True)
        self.assertEqual(result, self.dest)
        self.assertEqual(self.dest.read_bytes(), PAYLOAD)
        self.assertEqual(rpc.calls[-1][0], 'backup_delete_export')
        self.assertEqual(sorted(p.name for p in self.dest.parent.iterdir()), ['download.bin'])

    def test_corrupt_download_refused_and_temp_erased(self):
        rpc = FakeRpc({'backup_download_status': ok(META), 'backup_download_begin': ok(self.begin)}, payload=b'bad')
        with self.assertRaisesRegex(ClientError, 'integrity mismatch'):
            self.client(rpc).fetch(META['export_id'], self.dest)
        self.assertEqual(list(self.dest.parent.iterdir()), [])

    def test_existing_target_preserved_before_any_call(self):
        self.dest.write_bytes(b'keep')
        rpc = FakeRpc()
        with self.assertRaisesRegex(ClientError, 'exists'):
            self.client(rpc).fetch(META['export_id'], self.dest)
        self.assertEqual(self.dest.read_bytes(), b'keep')
        self.assertEqual(rpc.calls, [])

    def test_overwrite_replaces_atomically(self):
        self.dest.write_bytes(b'old')
        rpc = FakeRpc({'backup_download_status': ok(META), 'backup_download_begin': ok(self.begin)})
        self.client(rpc).fetch(META['export_id'], self.dest, overwrite=True)
        self.assertEqual(self.dest.read_bytes(), PAYLOAD)

    def test_download_prepares_fetches_and_deletes(self):
        rpc = FakeRpc({'backup_prepare_download': ok(META), 'backup_download_status': ok(META),
                       'backup_download_begin': ok(self.begin), 'backup_delete_export': ok({'deleted': True})})
        self.client(rpc).download('abcdef12', self.dest, 'dir/f.bin')
        self.assertEqual([c[0] for c in rpc.calls],
                         ['backup_prepare_download', 'backup_download_status', 'backup_download_begin',
                          'download_file', 'backup_delete_export'])
        self.assertEqual(rpc.calls[0][1], {'snapshot_id': 'abcdef12', 'file_path': 'dir/f.bin'})

    def test_download_link_is_absolute(self):
        rpc = FakeRpc({'backup_download_status': ok(META)})
        self.assertEqual(self.client(rpc).download_link(META['export_id']),
                         'https://onedrive-backup:8050/downloads/' + 'a' * 32 + '/f.bin')


class OdbcliTests(unittest.TestCase):
    def run_cli(self, *argv):
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            try:
                code = odbcli.main(list(argv))
            except SystemExit as exc:
                code = exc.code
        return code, out.getvalue(), err.getvalue()

    CONN = ('--url', 'https://h:1', '--ca', 'ca', '--cert', 'cert', '--key', 'key', '--login', 'u', '--password', 'p')

    def test_usage_errors_exit_2(self):
        self.assertEqual(self.run_cli('files')[0], 2)
        self.assertEqual(self.run_cli('status', '--no-such-option')[0], 2)
        self.assertEqual(self.run_cli(*self.CONN, 'call', 'help', '--params-json', 'not json')[0], 2)
        self.assertEqual(self.run_cli('snapshots')[0], 2)

    def test_success_prints_json(self):
        with patch.object(BackupClient, 'backup_snapshots', return_value={'items': [], 'count': 0}):
            code, out, err = self.run_cli(*self.CONN, 'snapshots', '--limit', '3')
        self.assertEqual((code, json.loads(out), err), (0, {'items': [], 'count': 0}, ''))

    def test_server_refusal_exits_1_and_hides_secrets(self):
        failure = ClientError('Unknown export identifier', code=404)
        with patch.object(BackupClient, 'backup_download_begin', side_effect=failure):
            code, out, err = self.run_cli(*self.CONN, 'download-begin', '0' * 32)
        self.assertEqual((code, out), (1, ''))
        self.assertIn('404', err)
        self.assertNotIn('dTpw', err)

    def test_authentication_failure_exits_1(self):
        with patch.object(BackupClient, 'help', side_effect=ClientAuthenticationError('HTTP 401', code=401)):
            self.assertEqual(self.run_cli(*self.CONN, 'help')[0], 1)

    def test_local_failure_exits_3(self):
        with patch.object(BackupClient, 'fetch', side_effect=ClientError('Output exists')):
            self.assertEqual(self.run_cli(*self.CONN, 'fetch', '0' * 32, '--output', 'x')[0], 3)

    def test_every_server_command_has_a_subcommand(self):
        text = io.StringIO()
        with contextlib.redirect_stdout(text), self.assertRaises(SystemExit):
            odbcli.main(['--help'])
        for name in ('help', 'info', 'snapshots', 'files', 'prepare', 'status', 'delete', 'sites', 'libraries',
                     'discovery-status', 'download-begin', 'health', 'fetch', 'download', 'call', 'download-link'):
            self.assertIn(name, text.getvalue())


if __name__ == '__main__':
    unittest.main()
