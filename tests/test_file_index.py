"""Unit tests of the file name filter: name grammar, stored copy parsing and the SQLite name index (matrix 10.19)."""

from __future__ import annotations

import importlib
import tempfile
import unittest

match = importlib.import_module("onedrive_api.name_match")
indexing = importlib.import_module("onedrive_api.file_index")
build = importlib.import_module("onedrive_api.file_index_build")


class NamePatternTests(unittest.TestCase):
    """The grammar of the name part."""

    def test_contains_and_anchored(self) -> None:
        """No star is a contains match, a star anchors the pattern at both ends."""
        self.assertEqual(match.parse_pattern(" АКТ ").like, "%акт%")
        self.assertEqual(match.parse_pattern("a*b").like, "a%b")
        self.assertTrue(match.parse_pattern("*").empty)
        self.assertTrue(match.parse_pattern("").empty)

    def test_escapes_and_literals(self) -> None:
        """Backslash-star is a literal star; percent, underscore and question mark are literal."""
        self.assertEqual(match.parse_pattern("a\\*b").like, "%a*b%")
        self.assertEqual(match.parse_pattern("100%_x?").like, "%100\\%\\_x?%")

    def test_refusals(self) -> None:
        """Too many stars, a control character and a long text are refused."""
        for bad in ("a*" * 9, "\u0001", "q" * 129, 5):
            with self.assertRaises(match.PatternError):
                match.parse_pattern(bad)

    def test_key_ignores_case_and_normalisation(self) -> None:
        """The key is casefold of NFC."""
        self.assertEqual(match.key("Акт"), match.key("аКТ"))
        self.assertEqual(match.key("é"), match.key("é"))

    def test_stored_copy_names(self) -> None:
        """A stored copy is shown with the original name; digits are returned."""
        self.assertEqual(match.split_stored("report.dup-0123abcd.pdf"), ("report.pdf", "0123abcd"))
        self.assertEqual(match.split_stored("a.b.dup-0123abcd0123.tar"), ("a.b.tar", "0123abcd0123"))
        self.assertEqual(match.split_stored("noext.dup-0123abcd"), ("noext", "0123abcd"))
        self.assertEqual(match.split_stored("plain.pdf"), ("plain.pdf", ""))


class IndexTests(unittest.TestCase):
    """The persistent index."""

    def test_time_is_normalised(self) -> None:
        """Restic time stamps become UTC with six digits."""
        self.assertEqual(indexing.utc_time("2026-11-21T14:47:52.123456789+02:00"), "2026-11-21T12:47:52.123456Z")
        self.assertEqual(indexing.utc_time("2026-11-21T12:47:52Z"), "2026-11-21T12:47:52.000000Z")

    def test_copies_are_numbered_in_digit_order(self) -> None:
        """Copies of one name get 1, 2, ... in ascending order of their digits."""
        late = ("d", "a.pdf", "bbbbbbbb", "a.dup-bbbbbbbb.pdf", 1, "m")
        early = ("d", "a.pdf", "aaaaaaaa", "a.dup-aaaaaaaa.pdf", 2, "m")
        rows = list(build._numbered([late, early]))
        self.assertEqual([(row[3], row[6]) for row in rows], [("a.dup-aaaaaaaa.pdf", 1), ("a.dup-bbbbbbbb.pdf", 2)])

    def test_add_search_suggest(self) -> None:
        """A snapshot is indexed once; search and suggestions follow the name rules and the order."""
        name = "Акт.pdf"
        first = ("x", name, match.key(name), name, 5, "m", 0)
        second = ("", "b.txt", "b.txt", "b.txt", 1, "m", 0)
        with tempfile.TemporaryDirectory() as tmp:
            index = indexing.FileIndex(tmp)
            self.assertEqual(index.add_snapshot("s1", "2026-11-21T10:00:00.000000Z", "k", "d", [first, second]), 2)
            self.assertEqual(index.add_snapshot("s1", "2026-11-21T10:00:00.000000Z", "k", "d", [first, second]), 0)
            self.assertEqual(index.add_snapshot("s2", "2026-11-22T10:00:00.000000Z", "k", "d", [first]), 1)
            total, rows = index.search(["s1", "s2"], match.parse_pattern("акт*"), ["k"], 10, 0)
            self.assertEqual(total, 2)
            self.assertEqual([row["snapshot_id"] for row in rows], ["s2", "s1"])
            self.assertEqual(index.search(["s1"], match.parse_pattern("*.txt"), ["k"], 10, 0)[0], 1)
            self.assertEqual(index.search(["s1"], match.parse_pattern("txt*"), ["k"], 10, 0)[0], 0)
            self.assertEqual(index.suggest(["s1", "s2"], match.parse_pattern("ак"), 10), ([name], False))
            self.assertEqual(index.suggest([], match.parse_pattern("ab"), 10), ([], False))


if __name__ == "__main__":
    unittest.main()
