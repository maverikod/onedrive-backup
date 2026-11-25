"""Unit tests of the dates of the backups: snapshot attributes, date scope and collapse (matrix 10.22.2)."""

from __future__ import annotations

import importlib
import json
from pathlib import Path
import tempfile
from typing import Any
import unittest

attrs = importlib.import_module("onedrive_api.snapshot_attrs")
scope = importlib.import_module("onedrive_api.date_scope")
indexing = importlib.import_module("onedrive_api.file_index")
collapse = importlib.import_module("onedrive_api.file_collapse")
match = importlib.import_module("onedrive_api.name_match")
tree = importlib.import_module("onedrive_api.folder_tree")
base = importlib.import_module("onedrive_api.sharepoint_base")

RUN = "4196b9cc-e6f8-4006-8c7f-b54b20b85eb1"
SITE = tree.digest("S1")
ROWS = [
    {"snapshot_id": "a", "time_utc": "2026-11-20T10:00:00.000000Z", "site_key": SITE, "drive_key": "d1"},
    {"snapshot_id": "b", "time_utc": "2026-11-21T10:00:00.000000Z", "site_key": SITE, "drive_key": "d1"},
    {"snapshot_id": "c", "time_utc": "2026-11-20T11:00:00.000000Z", "site_key": SITE, "drive_key": "d2"},
]


def _row(name: str, size: int, mtime: str) -> tuple[str, str, str, str, int, str, int]:
    """Build one file row of the index.

    Args:
        name: The file name.
        size: The size.
        mtime: The modification time.

    Returns:
        The tuple add_snapshot takes.
    """
    return ("", name, match.key(name), name, size, mtime, 0)


def _day(stamp: str) -> str:
    """Return the date part of a stamp.

    Args:
        stamp: The UTC stamp.

    Returns:
        The date.
    """
    return stamp[:10]


class AttributeTests(unittest.TestCase):
    """The tags and the words of the snapshot attributes."""

    def test_trigger_words_and_tags(self) -> None:
        """schedule and catchup are scheduled, another word manual, none unknown.

        Returns:
            None.
        """
        self.assertEqual(attrs.trigger_word("schedule"), "scheduled")
        self.assertEqual(attrs.trigger_word("cli"), "manual")
        self.assertEqual(attrs.trigger_word(None), "unknown")
        self.assertEqual(attrs.run_tags("r-1", "schedule"), ["type-full", "trigger-scheduled", "run-r-1"])

    def test_tags_are_read_back(self) -> None:
        """Three tags give the attributes with source tag; a missing tag gives none.

        Returns:
            None.
        """
        found = attrs.from_tags(["sharepoint", "type-full", "trigger-manual", "run-r-2"])
        self.assertEqual(found, {"backup_type": "full", "trigger": "manual", "run_id": "r-2", "type_source": "tag"})
        self.assertIsNone(attrs.from_tags(["sharepoint", "type-full"]))


class BackfillTests(unittest.TestCase):
    """The migration and the backfill of the index."""

    def test_record_derived_and_tag(self) -> None:
        """A snapshot inside a run window takes the run, the others one legacy run per cluster; tags win.

        Returns:
            None.
        """
        with tempfile.TemporaryDirectory() as data:
            runs = Path(data) / "schedule"
            runs.mkdir()
            start = {"event": "start", "run_id": RUN, "started_at": "2026-11-22T23:07:49Z", "trigger": "schedule"}
            end = {"event": "end", "run_id": RUN, "finished_at": "2026-11-22T23:39:41Z", "exit_code": 0}
            (runs / "runs.jsonl").write_text(json.dumps(start) + "\n" + json.dumps(end) + "\n", encoding="utf-8")
            index = indexing.FileIndex(data)
            rows = [_row("a.txt", 1, "m")]
            index.add_snapshot("s1", "2026-11-19T10:00:00.000000Z", "k", "d", rows)
            index.add_snapshot("s2", "2026-11-19T10:30:00.000000Z", "k", "e", rows)
            index.add_snapshot("s3", "2026-11-22T23:20:00.000000Z", "k", "d", rows)
            tagged = {"backup_type": "full", "trigger": "manual", "run_id": "r-9", "type_source": "tag"}
            index.add_snapshot("s4", "2026-11-23T10:00:00.000000Z", "k", "d", rows, tagged)
            found = {row["snapshot_id"]: row for row in index.snapshots()}
            self.assertEqual(found["s1"]["run_id"], "legacy-20261119T100000Z")
            self.assertEqual(found["s2"]["run_id"], "legacy-20261119T100000Z")
            self.assertEqual((found["s1"]["trigger"], found["s1"]["type_source"]), ("unknown", "derived"))
            third = found["s3"]
            self.assertEqual((third["run_id"], third["trigger"], third["type_source"]), (RUN, "scheduled", "record"))
            self.assertEqual((found["s4"]["run_id"], found["s4"]["type_source"]), ("r-9", "tag"))


class ScopeTests(unittest.TestCase):
    """The selection of the snapshots."""

    def test_latest_all_and_dates(self) -> None:
        """latest takes the newest snapshot of every library, all every snapshot, dates the days.

        Returns:
            None.
        """
        empty = tree.Scope()
        latest = scope.select(ROWS, empty, [], [], None, _day)
        self.assertEqual([row["snapshot_id"] for row in latest.rows], ["b", "c"])
        want = {"mode": "latest", "dates": ["2026-11-20", "2026-11-21"], "snapshot_count": 2}
        self.assertEqual(latest.date_scope, want)
        every = scope.select(ROWS, empty, [], [], "all", _day)
        self.assertEqual(every.date_scope["snapshot_count"], 3)
        one = scope.select(ROWS, empty, [], ["2026-11-20", "2025-01-01"], None, _day)
        self.assertEqual(one.date_scope["mode"], "dates")
        self.assertEqual([item["code"] for item in one.warnings], ["NO_SNAPSHOT_FOR_DATE"])
        unknown = scope.select(ROWS, empty, ["nope"], [], None, _day)
        self.assertEqual((unknown.date_scope["snapshot_count"], unknown.warnings[0]["code"]), (0, "UNKNOWN_SITE_ID"))

    def test_errors_carry_the_item(self) -> None:
        """A scope conflict and a bad date answer a coded error with the field and the index.

        Returns:
            None.
        """
        with self.assertRaises(base.DiscoveryError) as raised:
            scope.check_date_scope(["2026-11-20"], "all")
        self.assertEqual(raised.exception.code, "INVALID_DATE_SCOPE")
        self.assertEqual(raised.exception.details["fields"], ["dates", "dates_mode"])
        with self.assertRaises(base.DiscoveryError) as bad:
            scope.check_dates(["2026-11-20", "2026-02-30"])
        self.assertEqual((bad.exception.details["index"], bad.exception.details["expected"]), (1, "YYYY-MM-DD"))


class CollapseTests(unittest.TestCase):
    """The collapsed search."""

    def test_version_and_file(self) -> None:
        """A file seen unchanged in two snapshots is one version, a changed one two versions of one file.

        Returns:
            None.
        """
        with tempfile.TemporaryDirectory() as data:
            index = indexing.FileIndex(data)
            first = [_row("a.txt", 1, "m1"), _row("b.txt", 5, "m")]
            second = [_row("a.txt", 1, "m1"), _row("b.txt", 6, "m2")]
            index.add_snapshot("s1", "2026-11-19T10:00:00.000000Z", "k", "d", first)
            index.add_snapshot("s2", "2026-11-20T10:00:00.000000Z", "k", "d", second)
            pattern = match.parse_pattern("")
            ids = ["s1", "s2"]

            def read(mode: str, order: str) -> tuple[int, list[dict[str, Any]]]:
                """Read the first ten rows of one collapse.

                Args:
                    mode: none, version or file.
                    order: The order_by key.

                Returns:
                    The total and the rows.
                """
                return collapse.search_rows(index, ids, pattern, [], 10, 0, None, mode, order)

            self.assertEqual(read("none", "name")[0], 4)
            total, rows = read("version", "name")
            self.assertEqual((total, [row["snapshot_count"] for row in rows]), (3, [2, 1, 1]))
            total, rows = read("file", "size")
            found = [(row["name"], row["version_count"], row["snapshot_id"]) for row in rows]
            self.assertEqual((total, found), (2, [("b.txt", 2, "s2"), ("a.txt", 1, "s2")]))


if __name__ == "__main__":
    unittest.main()
