"""Unit tests of the persistent run log and of the reason in the end record of runs.jsonl (matrix row PL20, RL1-RL5)."""

from __future__ import annotations

import importlib
import json
import logging
import os
import stat
import tempfile
import unittest
import uuid
from pathlib import Path

run_log = importlib.import_module("onedrive_api.run_log")
records = importlib.import_module("onedrive_api.run_records")
LOG = logging.getLogger("onedrive_backup")
SECRET = "SeCrEt12345"


class ScrubTests(unittest.TestCase):
    """The secret scrubbing and the bound of the reason."""

    def test_key_value_secret_is_hidden(self) -> None:
        """A secret-looking key keeps its name and loses its value."""
        text = run_log.scrub("open /x/access_token=%s.json failed; password: %s" % (SECRET, SECRET))
        self.assertNotIn(SECRET, text)
        self.assertIn("access_token=***", text)
        self.assertIn("password: ***", text)

    def test_bearer_is_hidden(self) -> None:
        """A bearer credential is hidden."""
        self.assertNotIn(SECRET, run_log.scrub("Authorization: Bearer %s" % SECRET))

    def test_plain_text_is_kept(self) -> None:
        """A text without a secret is unchanged."""
        self.assertEqual(run_log.scrub("STORAGE_NOT_MOUNTED"), "STORAGE_NOT_MOUNTED")

    def test_bounded_cuts_to_the_limit(self) -> None:
        """A long multi-line text becomes one line of at most 500 characters."""
        text = run_log.bounded("line one\n" + "x" * 900)
        self.assertEqual(len(text), 500)
        self.assertNotIn("\n", text)
        self.assertTrue(text.endswith("..."))


class RetentionTests(unittest.TestCase):
    """The retention of the run log directory."""

    def test_prune_removes_the_oldest_run_ids_with_their_rotated_files(self) -> None:
        """Twelve run ids with keep 10 leave the ten newest; a rotated sibling goes with its run id."""
        with tempfile.TemporaryDirectory() as box:
            folder = Path(box)
            ids = ["%08x-0000-4000-8000-000000000000" % index for index in range(12)]
            for index, run in enumerate(ids):
                for suffix in (".log", ".log.1") if index == 0 else (".log",):
                    path = folder / (run + suffix)
                    path.write_text("x", encoding="utf-8")
                    os.utime(path, (1000 + index, 1000 + index))
            (folder / "note.txt").write_text("keep", encoding="utf-8")
            removed = run_log.prune(folder, keep=10)
            left = sorted(path.name for path in folder.iterdir())
            self.assertEqual(removed, 3)
            self.assertEqual(len(left), 11)
            self.assertNotIn(ids[0] + ".log", left)
            self.assertNotIn(ids[1] + ".log", left)
            self.assertIn(ids[11] + ".log", left)
            self.assertIn("note.txt", left)


class RunLogTests(unittest.TestCase):
    """The run log file, its reason and its end record."""

    def test_failed_run_leaves_a_log_and_a_reason(self) -> None:
        """An ERROR logged while an exception is handled gives the reason; the log is private and scrubbed."""
        with tempfile.TemporaryDirectory() as box:
            run_id = str(uuid.uuid4())
            handler = run_log.open_run_log(box, run_id)
            self.assertIsNotNone(handler)
            try:
                try:
                    raise OSError("cannot open /x/access_token=%s.json" % SECRET)
                except OSError as exc:
                    LOG.error("SharePoint backup refused: %s", exc)
                run_log.freeze(handler)
                LOG.error("File index failed: later")
                reason = run_log.end_reason(handler, 2)
            finally:
                run_log.close_run_log(handler)
            assert reason is not None
            self.assertTrue(reason.startswith("OSError: SharePoint backup refused"))
            self.assertNotIn(SECRET, reason)
            self.assertLessEqual(len(reason), 500)
            logfile = Path(box) / "schedule" / "logs" / (run_id + ".log")
            text = logfile.read_text(encoding="utf-8")
            self.assertIn("SharePoint backup refused", text)
            self.assertIn("File index failed: later", text)
            self.assertNotIn(SECRET, text)
            self.assertEqual(stat.S_IMODE(logfile.stat().st_mode), 0o600)
            self.assertEqual(stat.S_IMODE(logfile.parent.stat().st_mode), 0o700)

    def test_success_has_no_reason_and_failure_without_error_has_a_fixed_text(self) -> None:
        """Exit code 0 gives None; a non-zero code with no logged error gives a fixed non-empty text."""
        self.assertIsNone(run_log.end_reason(None, 0))
        self.assertEqual(run_log.end_reason(None, 1), "exit code 1 without a logged error")

    def test_directory_is_made_only_outside_scaffold_mode_at_start(self) -> None:
        """The service start creates the directory; scaffold mode does not."""
        with tempfile.TemporaryDirectory() as box:
            os.environ["ONEDRIVE_SCAFFOLD_MODE"] = "1"
            try:
                self.assertFalse(run_log.ensure_logs_dir(box))
                self.assertFalse((Path(box) / "schedule" / "logs").exists())
            finally:
                del os.environ["ONEDRIVE_SCAFFOLD_MODE"]
            self.assertTrue(run_log.ensure_logs_dir(box))
            self.assertEqual(stat.S_IMODE((Path(box) / "schedule" / "logs").stat().st_mode), 0o700)


class EndRecordTests(unittest.TestCase):
    """The reason in the end line of runs.jsonl."""

    def test_reason_only_for_a_non_zero_exit(self) -> None:
        """The end line carries the reason for exit code 2 and none for exit code 0."""
        with tempfile.TemporaryDirectory() as box:
            recorder = records.RunRecorder(box)
            failed = recorder.start()
            recorder.end(failed, 2, "BackupError: STORAGE_NOT_MOUNTED")
            done = recorder.start()
            recorder.end(done, 0, "ignored")
            lines = [json.loads(line) for line in recorder.path.read_text(encoding="utf-8").splitlines()]
            ends = {item["run_id"]: item for item in lines if item["event"] == "end"}
            self.assertEqual(ends[failed]["reason"], "BackupError: STORAGE_NOT_MOUNTED")
            self.assertNotIn("reason", ends[done])
            self.assertEqual([run["status"] for run in records.load_runs(recorder.path)], ["refused", "ok"])


if __name__ == "__main__":
    unittest.main()
