"""Unit tests of the folder scope and the folder tree counts over the file name index (matrix 10.21)."""

from __future__ import annotations

import importlib
import tempfile
import unittest

tree = importlib.import_module("onedrive_api.folder_tree")
indexing = importlib.import_module("onedrive_api.file_index")
match = importlib.import_module("onedrive_api.name_match")
base = importlib.import_module("onedrive_api.sharepoint_base")

STAMP = "2026-11-21T10:00:00.000000Z"
FILES = (
    ("", "root.txt"), ("a", "a1.txt"), ("a/b", "b1.txt"), ("a/b", "b2.txt"), ("c", "c1.txt"),
)


def _row(folder: str, name: str) -> tuple:
    """Build one index row of a file.

    Args:
        folder: The folder of the file.
        name: The file name.

    Returns:
        The tuple (dir, name, name_key, stored, size, mtime, copy_index).
    """
    return (folder, name, name, name, 1, STAMP, 0)


class ScopeTests(unittest.TestCase):
    """The scope chain and the folder grammar."""

    def _code(self, *args: object) -> tuple:
        """Parse a scope that must be refused.

        Args:
            args: The scope parameters.

        Returns:
            The error code and its details.
        """
        with self.assertRaises(base.DiscoveryError) as caught:
            tree.parse_scope(*args)
        return caught.exception.code, caught.exception.details

    def test_chain_is_checked_before_values(self) -> None:
        """A missing parent is INVALID_FOLDER_SCOPE with the missing fields, whatever the values are."""
        self.assertEqual(self._code(None, "d", None, None), ("INVALID_FOLDER_SCOPE", {"fields": ["site_id"]}))
        self.assertEqual(self._code("s", None, "a//b", None), ("INVALID_FOLDER_SCOPE", {"fields": ["drive_id"]}))
        self.assertEqual(self._code("s", None, None, True)[0], "INVALID_FOLDER_SCOPE")

    def test_values(self) -> None:
        """Malformed ids and folders have their own codes."""
        self.assertEqual(self._code("a b", None, None, None)[0], "INVALID_SITE_ID")
        self.assertEqual(self._code("s", "a b", None, None)[0], "INVALID_DRIVE_ID")
        for bad in ("/a", "a/", "a//b", "a/./b", "a/../b", "a\u0001b", "x" * 256, "/".join(["s"] * 65), "a" * 1025):
            self.assertEqual(self._code("s", "d", bad, None)[0], "INVALID_DIR", bad[:20])

    def test_rows(self) -> None:
        """The folder restriction follows the address."""
        self.assertIsNone(tree.parse_scope(None, None, None, None).rows())
        self.assertEqual(tree.parse_scope("s", "d", None, None).rows(), ("", False))
        self.assertEqual(tree.parse_scope("s", "d", "a/b", True).rows(), ("a/b", True))


class TreeTests(unittest.TestCase):
    """Children, counts and folder searches computed from the dir column."""

    def test_counts_and_scope_search(self) -> None:
        """Children, subtree counts and direct counts agree with the folder searches; file_dir exists."""
        with tempfile.TemporaryDirectory() as tmp:
            index = indexing.FileIndex(tmp)
            index.add_snapshot("s1", STAMP, "k", "d", [_row(*item) for item in FILES])
            every = match.parse_pattern("")
            self.assertEqual(sorted(tree.folder_counts(index, ["s1"], every, "")), [("a", 3, 1), ("c", 1, 1)])
            self.assertEqual(tree.folder_counts(index, ["s1"], every, "a"), [("b", 2, 2)])
            self.assertEqual(tree.folder_counts(index, ["s1"], every, "a/b"), [])
            self.assertEqual(tree.snapshot_counts(index, ["s1"], every), {"s1": (5, 1)})
            self.assertEqual(tree.snapshot_counts(index, ["s1"], match.parse_pattern("zz")), {})
            for folder, total in ((("", False), 1), (("", True), 5), (("a", False), 1), (("a", True), 3), (("a/b", True), 2)):
                self.assertEqual(index.search(["s1"], every, ["k"], 10, 0, folder)[0], total, folder)
            self.assertEqual(index.suggest(["s1"], match.parse_pattern("b"), 10, ("a/b", False))[0], ["b1.txt", "b2.txt"])
            conn = index.connect()
            try:
                columns = [row[2] for row in conn.execute("PRAGMA index_info(file_dir)")]
            finally:
                conn.close()
            self.assertEqual(columns, ["snapshot_id", "dir"])


if __name__ == "__main__":
    unittest.main()
