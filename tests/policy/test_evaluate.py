from __future__ import annotations

from verifypatch.model import (
    CoverageSummary,
    DiffCounts,
    Finding,
    Report,
    RequestedRefs,
    ResolvedRefs,
    TestChanges,
    TestsSummary,
    default_caveats,
)
from verifypatch.policy.evaluate import evaluate_policy
from verifypatch.config import PolicyConfig
from verifypatch.stage import StageResult, PipelineSummary, default_pipeline


def _report(**kwargs) -> Report:
    data = dict(
        schema_version="2",
        tool_version="0.2.0",
        status="complete",
        requested_refs=RequestedRefs("a", "b"),
        resolved_refs=ResolvedRefs("a" * 40, "b" * 40, "a" * 40),
        diff=DiffCounts(1, 0, 0, 0, 1, 0, 0, 0),
        coverage=CoverageSummary(10, 4, 3, 1, 2, 0.4),
        tests=TestsSummary(),
        findings=[],
        line_evidence=[],
        warnings=[],
        caveats=default_caveats(),
        pipeline=default_pipeline(),
    )
    data.update(kwargs)
    return Report(**data)


def test_threshold_equality_passes():
    cfg = PolicyConfig(minimum_pr_untouched_changed_line_coverage=0.4)
    result = evaluate_policy(_report(), cfg, enforced=False)
    assert result.decision == "pass"


def test_null_metric_does_not_satisfy_threshold():
    cfg = PolicyConfig(minimum_pr_untouched_changed_line_coverage=0.0)
    report = _report(coverage=CoverageSummary(0, 0, 0, 0, 0, None))
    result = evaluate_policy(report, cfg, enforced=False)
    assert result.decision == "review"
    assert any(item.code == "null_metric" for item in result.reasons)


def test_incomplete_required_stage():
    cfg = PolicyConfig(require_stages=["mutation"], incomplete="review")
    result = evaluate_policy(_report(), cfg, enforced=False)
    assert result.decision == "review"
    assert any(item.code == "required_stage_incomplete" for item in result.reasons)


def test_informational_block_still_reports_block():
    cfg = PolicyConfig(block_on_findings=["TEST_SKIP_ADDED"])
    report = _report(
        findings=[
            Finding(id="TEST_SKIP_ADDED", severity="review", path="tests/t.py", detail="skip")
        ]
    )
    result = evaluate_policy(report, cfg, enforced=False)
    assert result.mode == "informational"
    assert result.decision == "block"
    assert result.enforced is False


def test_enforced_block():
    cfg = PolicyConfig(block_on_findings=["TEST_SKIP_ADDED"])
    report = _report(
        findings=[
            Finding(id="TEST_SKIP_ADDED", severity="review", path="tests/t.py", detail="skip")
        ]
    )
    result = evaluate_policy(report, cfg, enforced=True)
    assert result.enforced is True
    assert result.decision == "block"


def test_null_mutation_score_does_not_satisfy_threshold():
    from verifypatch.mutation import MutationResult, MutationSummary

    cfg = PolicyConfig(minimum_independent_mutation_score=0.0)
    report = _report(mutation=MutationResult(summary=MutationSummary(independent_mutation_score=None)))
    result = evaluate_policy(report, cfg, enforced=False)
    assert result.decision != "pass"
    assert any(item.code == "null_metric" for item in result.reasons)


def test_null_metric_stays_not_pass_even_if_incomplete_is_pass():
    cfg = PolicyConfig(minimum_pr_untouched_changed_line_coverage=0.5, incomplete="pass")
    report = _report(coverage=CoverageSummary(0, 0, 0, 0, 0, None))
    result = evaluate_policy(report, cfg, enforced=False)
    assert result.decision != "pass"


def test_deleted_tests_optional_block():
    tests = TestsSummary()
    tests.changes = TestChanges(nodes_removed=2)
    cfg = PolicyConfig(block_on_deleted_tests=True)
    result = evaluate_policy(_report(tests=tests), cfg, enforced=True)
    assert result.decision == "block"


def test_enforce_flag_not_config_controls_enforced():
    cfg = PolicyConfig(block_on_findings=["TEST_SKIP_ADDED"])
    report = _report(
        findings=[Finding(id="TEST_SKIP_ADDED", severity="review", path="tests/t.py", detail="skip")]
    )
    informational = evaluate_policy(report, cfg, enforced=False)
    assert informational.mode == "informational"
    assert informational.decision == "block"
    assert informational.would_decide == "block"
    assert informational.enforced is False
    enforcing = evaluate_policy(report, cfg, enforced=True)
    assert enforcing.mode == "enforcing"
    assert enforcing.decision == "block"
    assert enforcing.would_decide == "block"
    assert enforcing.enforced is True
