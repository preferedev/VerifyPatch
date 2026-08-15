"""VerifyPatch pytest plugin. PYTEST_DONT_REWRITE"""

from __future__ import annotations

import json
import os
from typing import Any

import pytest

from verifypatch.plugin_env import PLUGIN_ACTIVE_ENV, PLUGIN_OUT_ENV

_REPORTS: dict[str, dict[str, Any]] = {}
_NODE_FILES: dict[str, str | None] = {}


def _active() -> bool:
    return bool(os.environ.get(PLUGIN_OUT_ENV) or os.environ.get(PLUGIN_ACTIVE_ENV))


def pytest_collection_finish(session: pytest.Session) -> None:
    if not _active():
        return
    _NODE_FILES.clear()
    _REPORTS.clear()
    for item in session.items:
        path = None
        if hasattr(item, "path"):
            path = str(item.path)
        elif hasattr(item, "fspath"):
            path = str(item.fspath)
        _NODE_FILES[item.nodeid] = path


def pytest_runtest_setup(item: pytest.Item) -> None:
    if not _active():
        return
    try:
        import coverage
    except ImportError:
        return
    cov = coverage.Coverage.current()
    if cov is not None:
        cov.switch_context(item.nodeid)


@pytest.hookimpl(hookwrapper=True)
def pytest_runtest_teardown(item: pytest.Item, nextitem: pytest.Item | None):
    if not _active():
        yield
        return
    yield
    try:
        import coverage
    except ImportError:
        return
    cov = coverage.Coverage.current()
    if cov is not None:
        cov.switch_context("")


def pytest_runtest_logreport(report: pytest.TestReport) -> None:
    if not _active():
        return
    rec = _REPORTS.setdefault(
        report.nodeid,
        {"setup": None, "call": None, "teardown": None},
    )
    rec[report.when] = {
        "outcome": report.outcome,
        "wasxfail": bool(getattr(report, "wasxfail", False)),
    }


def _normalize_outcome(rec: dict[str, Any]) -> str:
    setup = rec.get("setup") or {}
    call = rec.get("call") or {}
    teardown = rec.get("teardown") or {}
    if setup.get("outcome") == "skipped":
        return "xfailed" if setup.get("wasxfail") else "skipped"
    if setup.get("outcome") == "failed":
        return "error"
    if call.get("outcome") == "skipped":
        return "xfailed" if call.get("wasxfail") else "skipped"
    if call.get("wasxfail"):
        if call.get("outcome") == "failed":
            return "xfailed"
        if call.get("outcome") == "passed":
            return "xpassed"
    if call.get("outcome") == "failed":
        return "failed"
    if teardown.get("outcome") == "failed":
        return "error"
    if call.get("outcome") == "passed":
        return "passed"
    if setup.get("outcome") == "passed" and not call:
        return "passed"
    return "error"


def pytest_sessionfinish(session: pytest.Session, exitstatus: int) -> None:
    if not _active():
        return
    out = os.environ.get(PLUGIN_OUT_ENV)
    if not out:
        return
    tests = [
        {
            "nodeid": nodeid,
            "path": _NODE_FILES.get(nodeid),
            "outcome": _normalize_outcome(rec),
        }
        for nodeid, rec in _REPORTS.items()
    ]
    payload = {
        "exitstatus": int(exitstatus),
        "collected": [
            {"nodeid": nodeid, "path": path} for nodeid, path in _NODE_FILES.items()
        ],
        "tests": tests,
    }
    path = os.path.abspath(out)
    parent = os.path.dirname(path)
    if parent:
        os.makedirs(parent, exist_ok=True)
    with open(path, "w", encoding="utf-8") as handle:
        json.dump(payload, handle, indent=2)
        handle.write("\n")
    _REPORTS.clear()
