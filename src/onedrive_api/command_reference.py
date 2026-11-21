"""Canonical detailed descriptions for the OneDrive Backup MCP commands.

The same records drive help(cmdname=...) metadata and info command pages.
"""
from __future__ import annotations

from typing import Any
from .command_reference_catalog import CATALOG_REFERENCE
from .command_reference_core import CORE_REFERENCE
from .command_reference_exports import EXPORT_REFERENCE
from .command_reference_filter import FILTER_REFERENCE
from .command_reference_sharepoint import SHAREPOINT_REFERENCE

REFERENCE: dict[str, dict[str, Any]] = {
    **SHAREPOINT_REFERENCE,
    "help": CORE_REFERENCE["help"],
    **CATALOG_REFERENCE,
    **FILTER_REFERENCE,
    **EXPORT_REFERENCE,
    "info": CORE_REFERENCE["info"],
}


def command_metadata_for(cls: Any) -> dict[str, Any]:
    """Compose rich help metadata without altering JSON schema semantics.

    Returns:
        Detailed command metadata with parameters and examples.
    """
    record = REFERENCE.get(cls.name)
    if record is None:
        return {"parameters": cls._default_parameters_from_schema()}
    parameters = cls._default_parameters_from_schema()
    for name, description in record["parameters"].items():
        if name in parameters:
            parameters[name]["description"] = description
    return {
        "detailed_description": record["detailed_description"],
        "parameters": parameters,
        "return_value": record["return_value"],
        "usage_examples": record["usage_examples"],
        "error_cases": record["error_cases"],
        "best_practices": record["best_practices"],
    }
