"""Fail-closed, read-only Microsoft SharePoint Online discovery.

Enumerate site collections and document libraries with app-only Graph access.
Incomplete scans never replace the last known complete inventory.
The implementation lives in the sharepoint_base, sharepoint_graph, sharepoint_scan and
sharepoint_inventory modules; this module keeps the public import path.
"""

from __future__ import annotations

from .sharepoint_base import (
    GRAPH_ROOT,
    GUID,
    IDENTIFIER,
    MAX_ITEMS,
    MAX_PAGES,
    MAX_RESPONSE_BYTES,
    DiscoveryError,
    EntraCredentials,
)
from .sharepoint_graph import GraphClient, _http_request
from .sharepoint_inventory import SharePointInventory
from .sharepoint_scan import SharePointDiscovery

__all__ = [
    "GRAPH_ROOT",
    "GUID",
    "IDENTIFIER",
    "MAX_ITEMS",
    "MAX_PAGES",
    "MAX_RESPONSE_BYTES",
    "DiscoveryError",
    "EntraCredentials",
    "GraphClient",
    "SharePointDiscovery",
    "SharePointInventory",
    "_http_request",
]
