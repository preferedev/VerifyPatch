from __future__ import annotations

from pathlib import Path

from verifypatch.engine import run_check
from tests.helpers import commit_all, materialize_fixture


def test_nested_conftest_does_not_taint_sibling_tests(tmp_path: Path):
    repo, _base, mid = materialize_fixture("clean_refactor", tmp_path / "nested")
    nested = repo / "tests" / "unit"
    nested.mkdir()
    (nested / "conftest.py").write_text("import pytest\n", encoding="utf-8")
    (nested / "test_unit.py").write_text("def test_unit():\n    assert True\n", encoding="utf-8")
    path = repo / "src" / "mathy.py"
    path.write_text(
        path.read_text(encoding="utf-8").replace("return product", "return product + 0"),
        encoding="utf-8",
    )
    head = commit_all(repo, "nested conftest")
    report = run_check(repo, mid, head, pytest_args=[])
    mathy = [row for row in report.line_evidence if row.path == "src/mathy.py"]
    assert mathy
    # tests/test_mul.py is unchanged and is not under tests/unit/
    assert any(row.classification == "pr_untouched" for row in mathy)
