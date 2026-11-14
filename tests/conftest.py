from __future__ import annotations

import uuid
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parent.parent


def pytest_configure(config):
    sys_path = str(PROJECT_ROOT)
    import sys

    if sys_path not in sys.path:
        sys.path.insert(0, sys_path)


def pytest_collection_modifyitems(items):
    """Default unknown tests to unit; integration tests must opt in explicitly."""
    for item in items:
        if "integration" in item.keywords:
            item.add_marker(pytest.mark.integration)
