from __future__ import annotations

import os

import pytest


def pytest_collection_modifyitems(config, items):
    if os.environ.get("VERIFYPATCH_LIVE_PROVIDERS") == "1":
        return
    selected = []
    deselected = []
    for item in items:
        if "live_provider" in item.keywords:
            deselected.append(item)
        else:
            selected.append(item)
    if deselected:
        config.hook.pytest_deselected(items=deselected)
        items[:] = selected
