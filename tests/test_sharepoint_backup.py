"""Contract tests for multi-library backup without a live source."""

from __future__ import annotations

import importlib
from pathlib import Path
import tempfile
import unittest
from unittest import mock

backup = importlib.import_module("onedrive_api.sharepoint_backup")


class SharePointBackupTests(unittest.TestCase):
    """Verify safe source selection and snapshot boundaries."""

    def setUp(self) -> None:
        """Create an isolated local mirror configuration.

        Returns:
            None.
        """
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.cfg = {
            "mirror_dir": self.root / "mirror",
            "repository_dir": self.root / "repo",
            "rclone_bin": "rclone",
            "restic_bin": "restic",
            "rclone_config": self.root / "rclone.conf",
            "password_file": self.root / "password",
            "onedrive_remote": "onedrive:",
            "max_delete": 100,
            "transfers": 4,
            "checkers": 8,
            "allow_empty_source": False,
        }
        self.report = {
            "complete": True,
            "errors": [],
            "sites": [
                {"site_id": "host,1,2", "source_status": "ok"},
                {"site_id": "host,3,4", "source_status": "ok"},
            ],
            "libraries": [
                {"site_id": "host,1,2", "drive_id": "drive-A",
                 "status": "ok", "display_name": "Documents"},
                {"site_id": "host,3,4", "drive_id": "drive-A",
                 "status": "ok", "display_name": "Documents"},
                {"site_id": "host,1,2", "drive_id": "drive-B",
                 "status": "ok", "display_name": "Documents"},
            ],
        }
        self.calls: list[list[str]] = []

    def fake_run(
        self, command: list[str], env: dict[str, str] | None = None,
        *, capture: bool = False
    ) -> str:
        """Simulate a nonempty remote for each library.

        Args:
            command: Simulated command and arguments.
            env: Optional process environment.
            capture: Whether stdout would be collected.

        Returns:
            JSON for lsjson, otherwise an empty string.
        """
        self.calls.append([str(value) for value in command])
        if "lsjson" in command:
            return '[{"Name":"file.txt","IsDir":false}]'
        return ""

    def invoke(self, *, dry_run: bool = False) -> int:
        """Run with a simulated initialised repository.

        Args:
            dry_run: Whether to simulate modifications only.

        Returns:
            Number of verified library operations.
        """
        with (
            mock.patch.object(backup, "assert_repository"),
            mock.patch.object(backup, "run_command",
                              side_effect=self.fake_run),
        ):
            return backup.backup_libraries(
                self.cfg, self.report, dry_run=dry_run
            )

    def test_stable_mirror_paths_and_distinct_snapshots(self) -> None:
        """Identical drive IDs in different sites never share a mirror.

        Returns:
            None.
        """
        self.assertEqual(self.invoke(), 3)
        first = backup.library_mirror(self.cfg, "host,1,2", "drive-A")
        second = backup.library_mirror(self.cfg, "host,3,4", "drive-A")
        self.assertNotEqual(first, second)
        self.assertTrue(first.is_dir())
        self.assertTrue(second.is_dir())
        syncs = [c for c in self.calls if "sync" in c]
        snapshots = [c for c in self.calls if "backup" in c]
        self.assertEqual(len(syncs), 3)
        self.assertEqual(len(snapshots), 3)
        self.assertEqual(len({c[c.index("sync") + 2] for c in syncs}), 3)
        for call in syncs:
            self.assertIn("--onedrive-drive-id", call)
            self.assertIn("--onedrive-drive-type", call)
            self.assertIn("documentLibrary", call)
            self.assertIn("--max-delete", call)
        for call in snapshots:
            self.assertIn("sharepoint", call)
            self.assertTrue(any(v.startswith("site-") for v in call))
            self.assertTrue(any(v.startswith("drive-") for v in call))
        self.assertFalse(any("forget" in c or "prune" in c
                             for c in self.calls))

    def test_dry_run_does_not_modify_mirror_or_restic(self) -> None:
        """Dry run checks all libraries without creating directories.

        Returns:
            None.
        """
        self.assertEqual(self.invoke(dry_run=True), 3)
        self.assertFalse((self.root / "mirror").exists())
        self.assertEqual(len([c for c in self.calls if "sync" in c]), 3)
        self.assertTrue(all("--dry-run" in c
                            for c in self.calls if "sync" in c))
        self.assertFalse(any("backup" in c for c in self.calls))

    def test_incomplete_discovery_has_no_side_effects(self) -> None:
        """Partial Graph coverage prevents any source or archive command.

        Returns:
            None.
        """
        self.report["complete"] = False
        with mock.patch.object(backup, "assert_repository") as repo:
            with self.assertRaises(backup.BackupError):
                backup.backup_libraries(
                    self.cfg, self.report, dry_run=False
                )
            repo.assert_not_called()
        self.assertFalse(self.calls)

    def test_duplicate_drive_in_same_site_is_invalid(self) -> None:
        """Duplicate identifiers cannot silently overwrite a mirror.

        Returns:
            None.
        """
        libraries = self.report["libraries"]
        assert isinstance(libraries, list)
        libraries.append(dict(libraries[0]))
        with self.assertRaises(backup.BackupError):
            backup.inventory_libraries(self.report)

    def test_empty_library_refuses_sync(self) -> None:
        """Empty remote never erases an existing local mirror.

        Returns:
            None.
        """
        with (
            mock.patch.object(backup, "assert_repository"),
            mock.patch.object(backup, "run_command",
                              return_value="[]") as runner,
        ):
            with self.assertRaises(backup.BackupError):
                backup.backup_libraries(self.cfg, self.report,
                                        dry_run=False)
            self.assertEqual(runner.call_count, 1)
        self.assertFalse((self.root / "mirror").exists())

    def test_failed_library_prevents_later_snapshots(self) -> None:
        """A failed sync stops the job before retention or later libraries.

        Returns:
            None.
        """
        def failed(command, env=None, *, capture=False):
            self.calls.append(command)
            if "lsjson" in command:
                return '[{"Name":"file.txt"}]'
            if "sync" in command:
                raise backup.BackupError("RCLONE_FAILED")
            return ""

        with (
            mock.patch.object(backup, "assert_repository"),
            mock.patch.object(backup, "run_command",
                              side_effect=failed),
        ):
            with self.assertRaises(backup.BackupError):
                backup.backup_libraries(self.cfg, self.report,
                                        dry_run=False)
        self.assertFalse(any("backup" in c or "forget" in c
                             for c in self.calls))

    def test_bad_drive_and_legacy_remote_are_rejected(self) -> None:
        """Identifiers cannot inject rclone arguments or remote paths.

        Returns:
            None.
        """
        with self.assertRaises(backup.BackupError):
            backup.library_rclone(self.cfg, "../unsafe")
        self.cfg["onedrive_remote"] = "onedrive:SubFolder"
        with self.assertRaises(backup.BackupError):
            backup.library_rclone(self.cfg, "drive-A")

    def test_scaffold_cli_is_fail_closed(self) -> None:
        """Scaffold never opens repositories or begins discovery.

        Returns:
            None.
        """
        with mock.patch.dict("os.environ", {"ONEDRIVE_SCAFFOLD_MODE": "1"}):
            with mock.patch.object(backup, "discover") as discovery:
                result = backup.main(["--dry-run"])
                self.assertEqual(result, 2)
                discovery.assert_not_called()


if __name__ == "__main__":
    unittest.main()
