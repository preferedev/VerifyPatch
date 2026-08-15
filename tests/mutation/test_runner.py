from __future__ import annotations

from pathlib import Path

from verifypatch.mutation.ast_backend import AstMutationBackend
from verifypatch.mutation.runner import run_mutation
from verifypatch.model import (
    CoverageSummary,
    DiffCounts,
    LineEvidence,
    Report,
    RequestedRefs,
    ResolvedRefs,
    TestsSummary,
    default_caveats,
)
from verifypatch.config import V2Config, load_config
from verifypatch.deadlines import start_deadline
from verifypatch.generation import empty_generated_tests
from verifypatch.classify import PathClass


def test_zero_mutants_complete(tmp_path: Path):
    report = Report(
        schema_version="2",
        tool_version="0.2.0",
        status="complete",
        requested_refs=RequestedRefs("a", "b"),
        resolved_refs=ResolvedRefs("a" * 40, "b" * 40, "a" * 40),
        diff=DiffCounts(0, 0, 0, 0, 0, 0, 0, 0),
        coverage=CoverageSummary(0, 0, 0, 0, 0, None),
        tests=TestsSummary(),
        findings=[],
        line_evidence=[],
        warnings=[],
        caveats=default_caveats(),
    )
    cfg = V2Config()
    cfg.mutation.enabled = True
    stage, result = run_mutation(
        tmp_path,
        "b" * 40,
        cfg,
        report,
        {},
        {},
        load_config(tmp_path),
        empty_generated_tests(),
        tmp_path / "arts",
        start_deadline(60),
        backend=AstMutationBackend(),
    )
    assert stage.status == "complete"
    assert result.summary.candidate == 0
    assert result.summary.independent_mutation_score is None


def test_baseline_failed_skips(tmp_path: Path):
    report = Report(
        schema_version="2",
        tool_version="0.2.0",
        status="complete",
        requested_refs=RequestedRefs("a", "b"),
        resolved_refs=ResolvedRefs("a" * 40, "b" * 40, "a" * 40),
        diff=DiffCounts(0, 0, 0, 0, 0, 0, 0, 0),
        coverage=CoverageSummary(0, 0, 0, 0, 0, None),
        tests=TestsSummary(),
        findings=[],
        line_evidence=[],
        warnings=[],
        caveats=default_caveats(),
    )
    cfg = V2Config()
    cfg.mutation.enabled = True
    stage, _result = run_mutation(
        tmp_path,
        "b" * 40,
        cfg,
        report,
        {},
        {},
        load_config(tmp_path),
        empty_generated_tests(),
        tmp_path / "arts",
        start_deadline(60),
        backend=AstMutationBackend(),
        provenance_failed=True,
    )
    assert stage.status == "skipped"
    assert stage.skip_reason and stage.skip_reason.code == "baseline_failed"
