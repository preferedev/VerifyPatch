from __future__ import annotations

import json
import os
from pathlib import Path

import pytest
from coverage import Coverage

from verifypatch.coverage_run import apply_required_overrides
from verifypatch.plugin_env import PLUGIN_ACTIVE_ENV, PLUGIN_OUT_ENV
from verifypatch.pytest_invoke import (
    DISABLE_AUTOLOAD_ENV,
    coverage_pytest_main_args,
    unload_verifypatch_modules,
)


def main() -> int:
    root = Path(os.environ["VERIFYPATCH_ROOT"]).resolve()
    data_file = Path(os.environ["COVERAGE_FILE"]).resolve()
    os.environ.setdefault(PLUGIN_ACTIVE_ENV, "1")
    os.environ[DISABLE_AUTOLOAD_ENV] = "1"
    os.environ["COVERAGE_CORE"] = "ctrace"
    if PLUGIN_OUT_ENV not in os.environ:
        raise SystemExit("VERIFYPATCH_PLUGIN_OUT is required")
    pytest_args = json.loads(os.environ.get("VERIFYPATCH_PYTEST_ARGS_JSON") or "[]")
    os.chdir(root)
    cov = Coverage(config_file=True, data_file=str(data_file), branch=False)
    apply_required_overrides(cov, data_file)
    cov.start()
    try:
        # pytest cannot assertion-rewrite an already-imported plugin. Subject
        # repos with filterwarnings=error treat that warning as a collection error.
        args = coverage_pytest_main_args(pytest_args)
        unload_verifypatch_modules()
        code = pytest.main(args)
    finally:
        cov.stop()
        cov.save()
    return int(code)


if __name__ == "__main__":
    raise SystemExit(main())
