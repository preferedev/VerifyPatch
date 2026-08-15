from __future__ import annotations

from pathlib import Path

from verifypatch.engine import run_check
from tests.helpers import commit_all, materialize_fixture


def test_tox_ini_coverage_source(tmp_path: Path):
    repo, _base, mid = materialize_fixture("clean_refactor", tmp_path / "toxcov")
    (repo / "tox.ini").write_text("[coverage:run]\nsource = src\n", encoding="utf-8")
    path = repo / "src" / "mathy.py"
    path.write_text(path.read_text(encoding="utf-8") + "\nTOX = 1\n", encoding="utf-8")
    head = commit_all(repo, "tox coverage")
    report = run_check(repo, mid, head, pytest_args=[])
    assert any(row.path == "src/mathy.py" for row in report.line_evidence)
    assert report.coverage.changed_executable_lines >= 1
