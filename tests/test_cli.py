from __future__ import annotations

import json
from pathlib import Path

from verifypatch.cli import main
from verifypatch.engine import run_check
from verifypatch.report import validate_report
from tests.helpers import materialize_fixture, normalize_report


def _assert_partitions(payload: dict) -> None:
    cov = payload["coverage"]
    total = (
        cov["covered_by_pr_untouched_tests"]
        + cov["covered_only_by_pr_touched_tests"]
        + cov["covered_only_by_unknown_contexts"]
        + cov["uncovered"]
    )
    assert total == cov["changed_executable_lines"]


def test_discount_golden(tmp_path: Path):
    repo, base, head = materialize_fixture("discount", tmp_path / "repo")
    report = run_check(repo, base, head, pytest_args=[])
    payload = report.to_json_dict()
    validate_report(payload)
    _assert_partitions(payload)
    expected_path = Path(__file__).resolve().parents[1] / "fixtures" / "discount" / "expected.json"
    expected = json.loads(expected_path.read_text(encoding="utf-8"))
    actual = normalize_report(payload)
    assert actual == expected


def test_clean_refactor_no_review(tmp_path: Path):
    repo, base, head = materialize_fixture("clean_refactor", tmp_path / "repo")
    report = run_check(repo, base, head, pytest_args=[])
    payload = report.to_json_dict()
    validate_report(payload)
    _assert_partitions(payload)
    review = [item for item in payload["findings"] if item["severity"] == "review"]
    assert review == []
    expected_path = (
        Path(__file__).resolve().parents[1] / "fixtures" / "clean_refactor" / "expected.json"
    )
    expected = json.loads(expected_path.read_text(encoding="utf-8"))
    actual = normalize_report(payload)
    assert actual == expected


def test_cli_writes_files(tmp_path: Path):
    repo, base, head = materialize_fixture("clean_refactor", tmp_path / "repo")
    json_out = tmp_path / "out.json"
    md_out = tmp_path / "out.md"
    code = main(
        [
            "check",
            "--base",
            base,
            "--head",
            head,
            "--root",
            str(repo),
            "--json-out",
            str(json_out),
            "--md-out",
            str(md_out),
        ]
    )
    assert code == 0
    payload = json.loads(json_out.read_text(encoding="utf-8"))
    validate_report(payload)
    assert "Independent Verification Report" in md_out.read_text(encoding="utf-8")


def test_python_module_invocation(tmp_path: Path):
    import subprocess
    import sys

    repo, base, head = materialize_fixture("clean_refactor", tmp_path / "mod")
    json_out = tmp_path / "m.json"
    md_out = tmp_path / "m.md"
    completed = subprocess.run(
        [
            sys.executable,
            "-m",
            "verifypatch",
            "check",
            "--base",
            base,
            "--head",
            head,
            "--root",
            str(repo),
            "--json-out",
            str(json_out),
            "--md-out",
            str(md_out),
        ],
        check=False,
        capture_output=True,
        text=True,
    )
    assert completed.returncode == 0, completed.stderr
    assert json_out.is_file()
    assert md_out.is_file()


def test_xdist_rejected(tmp_path: Path):
    repo, base, head = materialize_fixture("clean_refactor", tmp_path / "repo")
    code = main(
        [
            "check",
            "--base",
            base,
            "--head",
            head,
            "--root",
            str(repo),
            "--pytest-args",
            "-n auto",
            "--json-out",
            str(tmp_path / "x.json"),
            "--md-out",
            str(tmp_path / "x.md"),
        ]
    )
    assert code == 2
