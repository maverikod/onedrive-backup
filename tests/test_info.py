"""Regression tests for the paginated operational reference."""

from __future__ import annotations

import asyncio
import importlib.util
import json
from pathlib import Path
import sys
import types
import unittest
from unittest.mock import patch

REFERENCE = importlib.import_module("onedrive_api.command_reference").REFERENCE


ROOT = Path(__file__).resolve().parents[1]
INFO_PATH = ROOT / "src" / "onedrive_api" / "info_command.py"


class ReferenceContractTests(unittest.TestCase):
    """Exercise real info code with a small in-memory MCP adapter."""

    def setUp(self) -> None:
        """Load the production implementation without external dependencies."""

        class FakeCommand:
            @classmethod
            def get_schema(cls) -> dict:
                return {"type": "object", "properties": {}}

            @classmethod
            def _default_parameters_from_schema(cls) -> dict:
                props = cls.get_schema().get("properties", {})
                return {name: dict(spec) for name, spec in props.items()}

            @classmethod
            def metadata(cls) -> dict:
                return {"parameters": cls._default_parameters_from_schema()}

        class FakeResult:
            def __init__(self, success: bool, data=None):
                self.success = success
                self.data = data

        class FakeError:
            def __init__(self, message: str, code=400, **kwargs):
                self.success = False
                self.message = message
                self.code = code
                self.details = kwargs.get("details")

        class FakeRegistry:
            def __init__(self):
                self.commands = {}

            def get_all_commands(self):
                return self.commands

        registry = FakeRegistry()
        files = {}
        for name in (
            "backup_snapshots",
            "backup_list_files",
            "backup_prepare_download",
            "backup_download_status",
            "backup_delete_export",
            "backup_sites_list",
            "backup_libraries_list",
            "backup_discovery_status",
            "help",
        ):
            category = "backup"
            if not name.startswith("backup_"):
                category = "documentation"
            cls = type(
                name,
                (FakeCommand,),
                {
                    "name": name,
                    "descr": name + " description",
                    "category": category,
                    "version": "0.3.4",
                    "author": "OneDrive Backup",
                    "get_schema": classmethod(
                        lambda klass: {
                            "type": "object",
                            "properties": {
                                "limit": {
                                    "type": "integer",
                                    "default": 100,
                                }
                            },
                            "additionalProperties": False,
                        }
                    ),
                },
            )
            files[name] = cls

        stubs = {
            "mcp_proxy_adapter": types.ModuleType("mcp_proxy_adapter"),
            "mcp_proxy_adapter.commands": types.ModuleType(
                "mcp_proxy_adapter.commands"
            ),
        }
        for key, values in (
            ("base", {"Command": FakeCommand}),
            ("command_registry", {"registry": registry}),
            (
                "result",
                {
                    "CommandResult": FakeResult,
                    "ErrorResult": FakeError,
                },
            ),
        ):
            package = types.ModuleType("mcp_proxy_adapter.commands." + key)
            for field, value in values.items():
                setattr(package, field, value)
            stubs[package.__name__] = package

        name = "onedrive_api._info_contract_test"
        spec = importlib.util.spec_from_file_location(name, INFO_PATH)
        assert spec is not None and spec.loader is not None
        module = importlib.util.module_from_spec(spec)
        with patch.dict(sys.modules, stubs):
            spec.loader.exec_module(module)
        files["info"] = module.InfoCommand
        registry.commands = files
        self.module = module
        self.command = module.InfoCommand()

    def test_every_page_and_registered_command(self) -> None:
        """Check complete pages, the table of contents and navigation."""
        first = asyncio.run(self.command.execute(page=1))
        self.assertTrue(first.success)
        self.assertEqual(first.data["kind"], "toc")
        total = first.data["total_pages"]
        self.assertGreater(total, len(REFERENCE) + 1)
        found = set()
        for page in range(1, total + 1):
            result = asyncio.run(self.command.execute(page=page))
            self.assertTrue(result.success, (page, result))
            data = result.data
            self.assertEqual(data["page"], page)
            self.assertEqual(data["total_pages"], total)
            self.assertEqual(
                data["previous_page"],
                page - 1 if page > 1 else None,
            )
            self.assertEqual(
                data["next_page"],
                page + 1 if page < total else None,
            )
            self.assertFalse(data["truncated"])
            self.assertLessEqual(
                len(json.dumps(data, ensure_ascii=False).encode("utf-8")),
                self.module.MAX_PAGE_BYTES,
            )
            self.assertTrue(data["content"].strip())
            if data["kind"] == "command":
                found.add(data["title"])
                for heading in (
                    "Purpose",
                    "Arguments",
                    "Returned data",
                    "Examples",
                    "Best practices",
                ):
                    self.assertIn(heading, data["content"])
        self.assertEqual(found, set(self.module._registered()))

    def test_invalid_page_types_and_range(self) -> None:
        """Reject negative, noninteger and out-of-range page values."""
        first = asyncio.run(self.command.execute(page=1))
        last = first.data["total_pages"]
        for invalid in (0, -1, last + 1, True, "1", 1.5):
            with self.subTest(page=invalid):
                result = asyncio.run(self.command.execute(page=invalid))
                self.assertFalse(result.success)
                self.assertEqual(result.code, 400)

    def test_missing_manual_fails_closed(self) -> None:
        """Report a missing production manual without silent fallback."""
        absent = INFO_PATH.parent / "NONEXISTENT_MANUAL.md"
        with patch.object(self.module, "MANUAL_FILE", absent):
            result = asyncio.run(self.command.execute(page=1))
        self.assertFalse(result.success)
        self.assertEqual(result.code, 503)

    def test_canonical_metadata_is_complete(self) -> None:
        """Require a canonical entry for every registered command."""
        self.assertEqual(set(REFERENCE), set(self.module._registered()))
        for name, command in self.module._registered().items():
            with self.subTest(command=name):
                schema = command.get_schema()
                self.assertFalse(schema.get("additionalProperties", True))
                reference = REFERENCE[name]
                for field in (
                    "detailed_description",
                    "parameters",
                    "return_value",
                    "usage_examples",
                    "error_cases",
                    "best_practices",
                ):
                    self.assertIn(field, reference)


if __name__ == "__main__":
    unittest.main()
