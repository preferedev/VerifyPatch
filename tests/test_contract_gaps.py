from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from verifypatch.engine import run_check
from verifypatch.errors import UnsupportedError
from verifypatch.gitops import collect_diff, merge_base_sha
from verifypatch.xdist import reject_xdist
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


def test_xdist_compact_flags_are_rejected(tmp_path: Path):
    (tmp_path / "pyproject.toml").write_text("[project]\nname='demo'\nversion='0'\n", encoding="utf-8")
    for args in (["-nauto"], ["-n=auto"], ["--numprocesses=auto"], ["-n8"]):
        with pytest.raises(UnsupportedError):
            reject_xdist(tmp_path, args)
    reject_xdist(tmp_path, ["-n", "0"])
    reject_xdist(tmp_path, ["--dist=no"])


def test_deleted_production_file_counts_lines(tmp_path: Path):
    repo, _base, mid = materialize_fixture("discount", tmp_path / "del")
    (repo / "src" / "promo.py").unlink()
    head = _commit(repo, "delete promo")
    diff = collect_diff(repo, merge_base_sha(repo, mid, head), head)
    promo = diff.by_path()["src/promo.py"]
    assert promo.status == "deleted"
    assert promo.deleted_line_count > 0
    report = run_check(repo, mid, head, pytest_args=[])
    assert report.diff.production_lines_deleted > 0


def test_renamed_test_compares_old_path(tmp_path: Path):
    repo, _base, mid = materialize_fixture("clean_refactor", tmp_path / "rename")
    src = repo / "tests" / "test_mul.py"
    dest = repo / "tests" / "test_multiply.py"
    dest.write_text(
        src.read_text(encoding="utf-8").replace("assert mul(3, 4) == 12", "assert mul(3, 4)"),
        encoding="utf-8",
    )
    src.unlink()
    head = _commit(repo, "rename and weaken")
    report = run_check(repo, mid, head, pytest_args=[])
    codes = [item.id for item in report.findings]
    assert "ASSERT_TO_TRUTHY" in codes
    assert report.tests.changes.nodes_added == 0
    assert report.tests.changes.nodes_removed == 0
    assert report.tests.changes.nodes_modified == 1


def test_pragma_no_cover_is_not_executable(tmp_path: Path):
    repo, _base, mid = materialize_fixture("clean_refactor", tmp_path / "pragma")
    path = repo / "src" / "mathy.py"
    path.write_text(
        path.read_text(encoding="utf-8") + "\nHIDDEN = 1  # pragma: no cover\n",
        encoding="utf-8",
    )
    head = _commit(repo, "pragma")
    report = run_check(repo, mid, head, pytest_args=[])
    hidden = [row for row in report.line_evidence if row.path.endswith("mathy.py")]
    assert all(row.line != _line_of(path, "HIDDEN") for row in hidden)


def _line_of(path: Path, needle: str) -> int:
    for index, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        if needle in line:
            return index
    raise AssertionError(needle)


def test_customer_omit_is_preserved(tmp_path: Path):
    repo, _base, mid = materialize_fixture("clean_refactor", tmp_path / "omit")
    pyproject = repo / "pyproject.toml"
    pyproject.write_text(
        pyproject.read_text(encoding="utf-8") + "\n[tool.coverage.run]\nomit = [\"src/skipped.py\"]\n",
        encoding="utf-8",
    )
    (repo / "src" / "skipped.py").write_text("VALUE = 1\n", encoding="utf-8")
    head = _commit(repo, "omit")
    report = run_check(repo, mid, head, pytest_args=[])
    assert all(row.path != "src/skipped.py" for row in report.line_evidence)
    mathy = [row for row in report.line_evidence if row.path.endswith("mathy.py")]
    # mathy was not changed in this commit besides skipped.py and pyproject
    assert report.coverage.changed_executable_lines == 0 or mathy


def test_empty_context_marks_incomplete(tmp_path: Path):
    repo, _base, mid = materialize_fixture("clean_refactor", tmp_path / "emptyctx")
    path = repo / "src" / "mathy.py"
    path.write_text("FLAG = True\n" + path.read_text(encoding="utf-8"), encoding="utf-8")
    head = _commit(repo, "import time")
    report = run_check(repo, mid, head, pytest_args=[])
    unknown = [row for row in report.line_evidence if row.classification == "unknown_only"]
    assert unknown
    assert report.status == "incomplete"
    assert any(item.code in {"empty_context", "unknown_coverage"} for item in report.warnings)
