"""Unit tests of the collision rules of colliding SharePoint files."""

from __future__ import annotations

import hashlib
import importlib
import json
import unicodedata
import unittest

names = importlib.import_module("onedrive_api.sharepoint_dupnames")


def row(path: str, item: str, size: int = 1, quickxor: str = "") -> dict:
    """Build a listing row of the form rclone lsjson -R --hash prints.

    Args:
        path: Folder-relative path.
        item: Graph item id.
        size: File size.
        quickxor: Optional hex quickXorHash.

    Returns:
        The listing row.
    """
    value = {"Path": path, "Name": path.rpartition("/")[2], "IsDir": False,
             "Size": size, "ID": "drive#" + item}
    if quickxor:
        value["Hashes"] = {"quickxor": quickxor}
    return value


class DuplicateNamesTests(unittest.TestCase):
    """Naming, collision keys and primary choice."""

    def test_key_joins_nfc_nfd_and_case(self) -> None:
        """NFC and NFD spellings and case variants share one key.

        Returns:
            None.
        """
        nfd = unicodedata.normalize("NFD", "Café.TXT")
        self.assertEqual(names.name_key(nfd), names.name_key("café.txt"))

    def test_stored_name_is_deterministic_and_extends_on_clash(self) -> None:
        """The name keeps the extension last and grows by four digits.

        Returns:
            None.
        """
        digest = hashlib.sha256(b"ID-1").hexdigest()
        first = names.stored_as("dir/Report.xlsx", "ID-1", set())
        self.assertEqual(first, "dir/Report.dup-" + digest[:8] + ".xlsx")
        longer = names.stored_as("dir/Report.xlsx", "ID-1",
                                 {names.name_key(first)})
        self.assertEqual(longer, "dir/Report.dup-" + digest[:12] + ".xlsx")
        self.assertEqual(names.stored_as("Plain", "ID-1", set()),
                         "Plain.dup-" + digest[:8])

    def test_reserved_names(self) -> None:
        """Only lowercase hex digits after .dup- make a name reserved.

        Returns:
            None.
        """
        self.assertTrue(names.is_reserved("a.dup-0123abcd.xlsx"))
        self.assertFalse(names.is_reserved("a.dup-0123ABCD.xlsx"))
        self.assertFalse(names.is_reserved("a.dup-0123.xlsx"))

    def test_groups_primary_and_listing(self) -> None:
        """Groups hold two or more rows; the tie falls to the smallest id.

        Returns:
            None.
        """
        files = [row("d/A.txt", "B"), row("d/a.TXT", "A"), row("d/c.txt", "C")]
        groups = names.collision_groups(files)
        self.assertEqual(len(groups), 1)
        self.assertEqual(names.item_id_of(names.pick_primary(
            groups[0], None, None)), "A")
        found, dirs = names.parse_listing(json.dumps(files))
        self.assertEqual((len(found), len(dirs)), (3, 0))
        with self.assertRaises(ValueError):
            names.parse_listing('[{"Name": "x"}]')

    def test_primary_by_hash(self) -> None:
        """The member equal to the mirrored file is the primary.

        Returns:
            None.
        """
        digest = "ab" * 20
        group = [row("d/a.txt", "A", 5, "cd" * 20),
                 row("d/A.txt", "Z", 7, digest)]
        self.assertEqual(
            names.item_id_of(names.pick_primary(group, 7, digest)), "Z")
