from __future__ import annotations

import json
from pathlib import Path

from jsonschema import Draft202012Validator

from verifypatch.model import (
    CoverageSummary,
    DiffCounts,
    Report,
    RequestedRefs,
    ResolvedRefs,
    TestsSummary,
    default_caveats,
    empty_coverage,
)
from verifypatch.report import render_markdown, validate_report
from verifypatch.schema import load_schema
from verifypatch import SCHEMA_VERSION, __version__


def _report(**kwargs) -> Report:
    data = dict(
        schema_version=SCHEMA_VERSION,
        tool_version=__version__,
        status="complete",
        requested_refs=RequestedRefs("abc", "def"),
        resolved_refs=ResolvedRefs("a" * 40, "b" * 40, "a" * 40),
        diff=DiffCounts(1, 1, 0, 0, 2, 0, 0, 0),
        coverage=CoverageSummary(4, 1, 1, 1, 1, 0.25),
        tests=TestsSummary(),
        findings=[],
        line_evidence=[],
        warnings=[],
        caveats=default_caveats(),
    )
    data.update(kwargs)
    return Report(**data)


def test_schema_loads():
    schema = load_schema()
    Draft202012Validator.check_schema(schema)


def test_valid_report_roundtrip(tmp_path: Path):
    report = _report()
    payload = report.to_json_dict()
    validate_report(payload)
    markdown = render_markdown(report)
    assert "PR-UNTOUCHED EVIDENCE" in markdown
    assert "No correctness score" in markdown


def test_zero_denominator_markdown():
    report = _report(coverage=empty_coverage())
    markdown = render_markdown(report)
    assert "n/a" in markdown
    validate_report(report.to_json_dict())


def test_partition_mismatch_rejected():
    try:
        CoverageSummary(2, 1, 0, 0, 0, 0.5).assert_invariant()
    except ValueError:
        return
    raise AssertionError("expected invariant failure")
