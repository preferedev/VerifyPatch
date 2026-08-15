from __future__ import annotations

import subprocess
from pathlib import Path

from verifypatch.engine import run_check
from tests.helpers import materialize_fixture, run_git


def _commit(repo: Path, message: str) -> str:
    subprocess.run(["git", "add", "-A"], cwd=repo, check=True, capture_output=True)
    subprocess.run(
        [
            "git",
            "-c",
            "user.name=verifypatch",
            "-c",
            "user.email=verifypatch@example.com",
            "commit",
            "-m",
            message,
        ],
        cwd=repo,
        check=True,
        capture_output=True,
    )
    return run_git(repo, "rev-parse", "HEAD")


def test_production_only_change(tmp_path: Path):
    repo, _base, mid = materialize_fixture("clean_refactor", tmp_path / "prod")
    path = repo / "src" / "mathy.py"
    path.write_text(path.read_text(encoding="utf-8") + "\n\ndef noop() -> int:\n    return 0\n", encoding="utf-8")
    head = _commit(repo, "prod only")
    report = run_check(repo, mid, head, pytest_args=[])
    assert report.diff.production_files_changed >= 1
    assert report.diff.test_files_changed == 0
    noop = [row for row in report.line_evidence if row.classification == "uncovered"]
    assert noop


def test_test_only_change(tmp_path: Path):
    repo, _base, mid = materialize_fixture("clean_refactor", tmp_path / "tests_only")
    test = repo / "tests" / "test_mul.py"
    test.write_text(test.read_text(encoding="utf-8") + "\n\ndef test_mul_one():\n    assert True\n", encoding="utf-8")
    head = _commit(repo, "test only")
    report = run_check(repo, mid, head, pytest_args=[])
    assert report.coverage.changed_executable_lines == 0
    assert report.diff.test_files_changed >= 1


def test_parameterized_node_ids(tmp_path: Path):
    repo, base, _head = materialize_fixture("clean_refactor", tmp_path / "param")
    (repo / "tests" / "test_param.py").write_text(
        "import pytest\nfrom src.mathy import add\n\n@pytest.mark.parametrize('n',[1,2])\n"
        "def test_param(n):\n    assert add(n, 0) == n\n",
        encoding="utf-8",
    )
    head = _commit(repo, "param")
    report = run_check(repo, base, head, pytest_args=[])
    assert report.tests.outcomes.collected >= 2
    assert report.status in {"complete", "incomplete"}
