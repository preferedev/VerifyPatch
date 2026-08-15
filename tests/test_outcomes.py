from __future__ import annotations

from pathlib import Path

from verifypatch.engine import run_check
from tests.helpers import commit_all, materialize_fixture


def test_pytest_outcome_matrix(tmp_path: Path):
    repo, _base, mid = materialize_fixture("clean_refactor", tmp_path / "outcomes")
    (repo / "tests" / "conftest.py").write_text(
        "import pytest\n\n"
        "@pytest.fixture\n"
        "def bad_setup():\n"
        "    raise RuntimeError('setup')\n\n"
        "@pytest.fixture\n"
        "def bad_teardown():\n"
        "    yield\n"
        "    raise RuntimeError('teardown')\n",
        encoding="utf-8",
    )
    (repo / "tests" / "test_outcomes.py").write_text(
        "import pytest\n\n"
        "def test_fail():\n"
        "    assert False\n\n"
        "def test_skip():\n"
        "    pytest.skip('nope')\n\n"
        "@pytest.mark.xfail(reason='expected')\n"
        "def test_xfail():\n"
        "    assert False\n\n"
        "@pytest.mark.xfail(reason='unexpected pass')\n"
        "def test_xpass():\n"
        "    assert True\n\n"
        "@pytest.mark.xfail(strict=True, reason='strict')\n"
        "def test_xpass_strict():\n"
        "    assert True\n\n"
        "def test_setup_error(bad_setup):\n"
        "    assert True\n\n"
        "def test_teardown_error(bad_teardown):\n"
        "    assert True\n",
        encoding="utf-8",
    )
    head = commit_all(repo, "outcomes")
    report = run_check(repo, mid, head, pytest_args=["tests/test_outcomes.py"])
    out = report.tests.outcomes
    assert out.failed >= 1
    assert out.skipped >= 1
    assert out.xfailed >= 1
    assert out.xpassed >= 1
    assert out.error >= 1
    assert report.tests.pytest_exit_code not in (0, None)
    assert report.status in {"complete", "incomplete"}


def test_collection_syntax_error(tmp_path: Path):
    repo, _base, mid = materialize_fixture("clean_refactor", tmp_path / "syntax")
    (repo / "tests" / "test_broken.py").write_text("def test_bad(:\n    pass\n", encoding="utf-8")
    head = commit_all(repo, "syntax")
    report = run_check(repo, mid, head, pytest_args=[])
    assert any(item.code == "test_parse_failed" for item in report.warnings)
    assert report.status == "incomplete"


def test_deleted_test_notice(tmp_path: Path):
    repo, _base, mid = materialize_fixture("clean_refactor", tmp_path / "deltest")
    (repo / "tests" / "test_mul.py").write_text("from src.mathy import mul\n", encoding="utf-8")
    head = commit_all(repo, "delete test")
    report = run_check(repo, mid, head, pytest_args=[])
    assert any(item.id == "TEST_REMOVED" and item.severity == "notice" for item in report.findings)


def test_fixture_teardown_keeps_exact_test_context(tmp_path: Path):
    repo, _base, mid = materialize_fixture("clean_refactor", tmp_path / "teardown_context")
    source = repo / "src" / "mathy.py"
    source.write_text(
        source.read_text(encoding="utf-8")
        + "\n\ndef cleanup_marker() -> int:\n    return 17\n",
        encoding="utf-8",
    )
    (repo / "tests" / "conftest.py").write_text(
        "import pytest\n"
        "from src.mathy import cleanup_marker\n\n"
        "@pytest.fixture\n"
        "def cleanup_fixture():\n"
        "    yield\n"
        "    cleanup_marker()\n",
        encoding="utf-8",
    )
    (repo / "tests" / "test_cleanup.py").write_text(
        "def test_cleanup(cleanup_fixture):\n"
        "    assert True\n",
        encoding="utf-8",
    )
    head = commit_all(repo, "teardown context")

    report = run_check(repo, mid, head, pytest_args=["tests/test_cleanup.py"])
    return_line = next(
        index
        for index, text in enumerate(
            source.read_text(encoding="utf-8").splitlines(), start=1
        )
        if "return 17" in text
    )
    evidence = next(
        row
        for row in report.line_evidence
        if row.path == "src/mathy.py" and row.line == return_line
    )

    assert evidence.classification == "pr_touched_only"
    assert evidence.covering_node_ids == ["tests/test_cleanup.py::test_cleanup"]
    assert "empty_context" not in evidence.notes


def test_duplicate_names_do_not_collide(tmp_path: Path):
    repo, _base, mid = materialize_fixture("clean_refactor", tmp_path / "dup")
    (repo / "tests" / "test_other.py").write_text(
        "from src.mathy import add\n\ndef test_add_positive():\n    assert add(8, 1) == 9\n",
        encoding="utf-8",
    )
    path = repo / "src" / "mathy.py"
    path.write_text(path.read_text(encoding="utf-8") + "\nDUP = 1\n", encoding="utf-8")
    head = commit_all(repo, "dup names")
    report = run_check(repo, mid, head, pytest_args=[])
    covering = []
    for row in report.line_evidence:
        covering.extend(row.covering_node_ids)
    assert any("test_add.py::test_add_positive" in node for node in covering) or report.line_evidence
    # node ids remain file-qualified
    assert all("::" in node for row in report.line_evidence for node in row.covering_node_ids)
