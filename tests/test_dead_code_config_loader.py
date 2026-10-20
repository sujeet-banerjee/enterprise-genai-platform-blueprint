"""Tests for issue #32: dead-code removal of ``ConfigLoader``.

The ad-hoc config reader was never wired into any service (every service reads
YAML through its own path-aware loader). It has been removed; this guard keeps it
from reappearing unnoticed.
"""

import importlib

import pytest


def test_config_loader_module_is_removed():
    with pytest.raises(ModuleNotFoundError):
        importlib.import_module("core.services.config_loader")


def test_no_source_file_references_config_loader():
    from pathlib import Path

    root = Path(__file__).resolve().parents[1]
    offenders = []
    for path in root.rglob("*.py"):
        if any(part in {".git", ".venv", "venv", "build", "dist"} for part in path.parts):
            continue
        if path.name == Path(__file__).name:
            continue
        if "ConfigLoader" in path.read_text(encoding="utf-8", errors="ignore"):
            offenders.append(str(path.relative_to(root)))
    assert offenders == [], f"ConfigLoader still referenced in: {offenders}"
