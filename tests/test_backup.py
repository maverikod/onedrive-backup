"""Fake-binary integration tests: no OneDrive/restic credentials required."""
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

SCRIPT = Path(__file__).resolve().parents[1] / "src" / "onedrive_backup.py"

MOCK_RCLONE = '''#!/usr/bin/env python3
import json, os, pathlib, shutil, sys
args=sys.argv[1:]
with open(os.environ['MOCK_CALLS'], 'a') as f: f.write('rclone '+json.dumps(args)+'\\n')
if 'lsjson' in args:
 if os.environ.get('MOCK_EMPTY') == '1': print('[]')
 else: print('[{"Name":"example.txt","IsDir":false}]')
 sys.exit(0)
if 'sync' in args:
 if os.environ.get('MOCK_RCLONE_FAIL') == '1': sys.exit(7)
 if '--dry-run' in args: sys.exit(0)
 dest=pathlib.Path(args[args.index('sync')+2]); dest.mkdir(parents=True, exist_ok=True)
 src=pathlib.Path(os.environ['MOCK_SOURCE'])
 for p in dest.rglob('*'):
  if p.is_file() and not (src / p.relative_to(dest)).exists(): p.unlink()
 for p in src.rglob('*'):
  if p.is_file():
   dst=dest/p.relative_to(src);dst.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(p,dst)
 sys.exit(0)
sys.exit(1)
'''
MOCK_RESTIC = '''#!/usr/bin/env python3
import os, pathlib, sys, json
args=sys.argv[1:]
with open(os.environ['MOCK_CALLS'], 'a') as f: f.write('restic '+json.dumps(args)+'\\n')
repo=pathlib.Path(os.environ['RESTIC_REPOSITORY'])
if args[0]=='init': repo.mkdir(parents=True,exist_ok=True); (repo/'config').write_text('ok'); sys.exit(0)
if args[:2]==['cat','config']:
 if (repo/'config').is_file(): print('ok'); sys.exit(0)
 sys.exit(10)
if args[0]=='backup':
 if os.environ.get('MOCK_RESTIC_FAIL')=='1': sys.exit(3)
 assert pathlib.Path(args[1]).exists()
 print('snapshot saved');sys.exit(0)
if args[0] in ('forget','check','snapshots'):
 print('ok');sys.exit(0)
sys.exit(1)
'''


class BackupIntegrationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.bin = self.root / "bin"
        self.bin.mkdir()
        for filename, body in (("rclone", MOCK_RCLONE), ("restic", MOCK_RESTIC)):
            binary = self.bin / filename
            binary.write_text(body)
            binary.chmod(0o755)
        self.source = self.root / "cloud"
        self.source.mkdir()
        (self.source / "a.txt").write_text("old")
        self.calls = self.root / "calls.log"
        self.rclone_conf = self.root / "rclone.conf"
        self.rclone_conf.write_text("[onedrive]\ntype=onedrive\n")
        self.password = self.root / "pw"
        self.password.write_text("secret")
        self.password.chmod(0o600)
        self.config = {
            "onedrive_remote": "onedrive:",
            "rclone_config": str(self.rclone_conf),
            "mirror_dir": str(self.root / "mirror"),
            "repository_dir": str(self.root / "repo"),
            "password_file": str(self.password),
            "lock_file": str(self.root / "state" / "backup.lock"),
            "log_file": str(self.root / "state" / "backup.log"),
            "required_mountpoint": None,
        }
        self.config_file = self.root / "config.json"
        self.set_config()

    def set_config(self):
        self.config_file.write_text(json.dumps(self.config))

    def run_script(self, cmd, **extra_env):
        env = os.environ.copy()
        env.update({"PATH": str(self.bin) + os.pathsep + env["PATH"],
                    "MOCK_SOURCE": str(self.source), "MOCK_CALLS": str(self.calls)})
        env.update(extra_env)
        return subprocess.run([sys.executable, str(SCRIPT), "--config", str(self.config_file), *cmd],
                              env=env, text=True, capture_output=True, check=False, timeout=12)

    def calls_text(self):
        return self.calls.read_text() if self.calls.exists() else ""

    def test_init_dry_run_backup_and_retention(self):
        self.assertEqual(self.run_script(["init"]).returncode, 0)
        self.assertEqual(self.run_script(["backup", "--dry-run"]).returncode, 0)
        self.assertFalse((self.root / "mirror").exists())
        self.assertNotIn('restic ["backup"', self.calls_text())
        result = self.run_script(["backup"])
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual((self.root / "mirror" / "a.txt").read_text(), "old")
        self.assertIn('restic ["backup"', self.calls_text())
        self.assertIn('restic ["forget"', self.calls_text())

    def test_error_from_rclone_does_not_create_snapshot(self):
        self.assertEqual(self.run_script(["init"]).returncode, 0)
        result = self.run_script(["backup"], MOCK_RCLONE_FAIL="1")
        self.assertNotEqual(result.returncode, 0)
        self.assertNotIn('restic ["backup"', self.calls_text())

    def test_empty_source_refused(self):
        self.assertEqual(self.run_script(["init"]).returncode, 0)
        result = self.run_script(["backup"], MOCK_EMPTY="1")
        self.assertNotEqual(result.returncode, 0)
        self.assertNotIn('"sync"', self.calls_text())
        self.assertNotIn('restic ["backup"', self.calls_text())

    def test_invalid_overlap_paths_refused(self):
        self.config["repository_dir"] = str(self.root / "mirror" / "repo")
        self.set_config()
        result = self.run_script(["init"])
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("не должны пересекаться", result.stdout)

    def test_missing_mount_prevents_writes(self):
        self.config["required_mountpoint"] = str(self.root / "not-mounted")
        self.config["log_file"] = str(self.root / "not-mounted" / "log" / "backup.log")
        self.set_config()
        result = self.run_script(["init"])
        self.assertNotEqual(result.returncode, 0)
        self.assertFalse((self.root / "not-mounted").exists())

    def test_failing_restic_does_not_prune(self):
        self.assertEqual(self.run_script(["init"]).returncode, 0)
        result = self.run_script(["backup"], MOCK_RESTIC_FAIL="1")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('restic ["backup"', self.calls_text())
        self.assertNotIn('restic ["forget"', self.calls_text())


if __name__ == "__main__":
    unittest.main()
