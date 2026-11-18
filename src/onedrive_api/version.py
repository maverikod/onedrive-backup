"""Runtime access to the release version: the VERSION file is the single source."""

from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path

VERSION_FILE_ENV = "ONEDRIVE_BACKUP_VERSION_FILE"


def _candidates() -> list[Path]:
    """Return VERSION locations: explicit override, image layout, repository layout."""
    here = Path(__file__).resolve()
    found: list[Path] = []
    override = os.environ.get(VERSION_FILE_ENV)
    if override:
        found.append(Path(override))
    found.append(here.parents[1] / "VERSION")
    found.append(here.parents[2] / "VERSION")
    return found


@lru_cache(maxsize=1)
def read_version() -> str:
    """Return the content of the VERSION file; fail closed when it is missing or empty."""
    for path in _candidates():
        if path.is_file():
            text = path.read_text(encoding="utf-8").strip()
            if text:
                return text
    raise RuntimeError("VERSION file not found or empty; searched: " + ", ".join(str(p) for p in _candidates()))
