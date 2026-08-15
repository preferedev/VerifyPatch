from __future__ import annotations

from pathlib import Path

from verifypatch.classify import classify_path
from verifypatch.config import VerifyPatchConfig


def test_pytest_filename_conventions():
    config = VerifyPatchConfig()
    assert classify_path("tests/test_foo.py", config).kind == "test_file"
    assert classify_path("pkg/foo_test.py", config).kind == "test_file"
    assert classify_path("tests/conftest.py", config).kind == "conftest"


def test_shared_helper_under_tests():
    config = VerifyPatchConfig()
    assert classify_path("tests/helpers.py", config).kind == "shared_test_helper"


def test_production_python():
    config = VerifyPatchConfig()
    assert classify_path("src/pricing.py", config).kind == "production"


def test_configured_test_root(tmp_path: Path):
    config = VerifyPatchConfig(test_paths=["spec"])
    assert classify_path("spec/support.py", config).kind == "shared_test_helper"
    assert classify_path("spec/test_thing.py", config).kind == "test_file"


def test_configured_test_globs():
    config = VerifyPatchConfig(test_globs=["checks/*.py"])
    assert classify_path("checks/verify.py", config).kind == "test_file"
    assert classify_path("src/pricing.py", config).kind == "production"
