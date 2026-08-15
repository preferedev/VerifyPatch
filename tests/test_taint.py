from __future__ import annotations

import subprocess
from pathlib import Path

from verifypatch.engine import run_check
from tests.helpers import materialize_fixture, run_git


def test_unimported_module_is_uncovered(tmp_path: Path):
    repo, base, head = materialize_fixture("discount", tmp_path / "repo")
    report = run_check(repo, base, head, pytest_args=[])
    promo = [row for row in report.line_evidence if row.path == "src/promo.py"]
    assert promo
    assert all(row.classification == "uncovered" for row in promo)


def test_shared_helper_taints_subtree(tmp_path: Path):
    repo, _base, mid = materialize_fixture("clean_refactor", tmp_path / "helper")
    (repo / "tests" / "helpers.py").write_text("VALUE = 1\n", encoding="utf-8")
    subprocess.run(["git", "add", "tests/helpers.py"], cwd=repo, check=True, capture_output=True)
    subprocess.run(
        [
            "git",
            "-c",
            "user.name=verifypatch",
            "-c",
            "user.email=verifypatch@example.com",
            "commit",
            "-m",
            "helper",
        ],
        cwd=repo,
        check=True,
        capture_output=True,
    )
    path = repo / "src" / "mathy.py"
    text = path.read_text(encoding="utf-8").replace("return product", "return product + 0")
    path.write_text(text, encoding="utf-8")
    subprocess.run(["git", "add", "src/mathy.py"], cwd=repo, check=True, capture_output=True)
    subprocess.run(
        [
            "git",
            "-c",
            "user.name=verifypatch",
            "-c",
            "user.email=verifypatch@example.com",
            "commit",
            "-m",
            "prod",
        ],
        cwd=repo,
        check=True,
        capture_output=True,
    )
    head = run_git(repo, "rev-parse", "HEAD")
    report = run_check(repo, mid, head, pytest_args=[])
    mathy = [row for row in report.line_evidence if row.path.endswith("mathy.py")]
    assert mathy
    assert all(row.classification != "pr_untouched" for row in mathy)


def test_conftest_taint_does_not_inflate_untouched(tmp_path: Path):
    repo, base, _head = materialize_fixture("clean_refactor", tmp_path / "nested")
    conftest = repo / "tests" / "conftest.py"
    conftest.write_text(
        "import pytest\n\n@pytest.fixture\ndef unused():\n    return 1\n",
        encoding="utf-8",
    )
    subprocess.run(["git", "add", "tests/conftest.py"], cwd=repo, check=True, capture_output=True)
    subprocess.run(
        [
            "git",
            "-c",
            "user.name=verifypatch",
            "-c",
            "user.email=verifypatch@example.com",
            "commit",
            "-m",
            "conftest",
        ],
        cwd=repo,
        check=True,
        capture_output=True,
    )
    head = run_git(repo, "rev-parse", "HEAD")
    report = run_check(repo, base, head, pytest_args=[])
    mul_lines = [row for row in report.line_evidence if row.path.endswith("mathy.py")]
    assert mul_lines
    assert all(row.classification != "pr_untouched" for row in mul_lines)
