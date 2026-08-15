from __future__ import annotations

from verifypatch.config import PolicyConfig, V2Config
from verifypatch.model import Report
from verifypatch.policy import POLICY_PRECEDENCE, PolicyReason, PolicyResult


def _worse(left: str, right: str) -> str:
    order = {name: index for index, name in enumerate(POLICY_PRECEDENCE)}
    return left if order[left] < order[right] else right


def evaluate_policy(report: Report, config: PolicyConfig, *, enforced: bool) -> PolicyResult:
    decision = "pass"
    reasons: list[PolicyReason] = []

    coverage = report.coverage.pr_untouched_changed_line_coverage
    threshold = config.minimum_pr_untouched_changed_line_coverage
    incomplete_decision = config.incomplete if config.incomplete in POLICY_PRECEDENCE else "review"
    if threshold is not None:
        if coverage is None:
            decision = _worse(decision, "not_evaluated")
            decision = _worse(decision, incomplete_decision)
            reasons.append(PolicyReason(code="null_metric", message="PR-untouched coverage is null; threshold cannot pass"))
        elif coverage < threshold:
            decision = _worse(decision, "block")
            reasons.append(
                PolicyReason(
                    code="coverage_below_threshold",
                    message=f"PR-untouched changed-line coverage {coverage} < {threshold}",
                )
            )

    mutation_score = None
    if report.mutation is not None:
        mutation_score = report.mutation.summary.independent_mutation_score
    mut_threshold = config.minimum_independent_mutation_score
    if mut_threshold is not None:
        if mutation_score is None:
            decision = _worse(decision, "not_evaluated")
            decision = _worse(decision, incomplete_decision)
            reasons.append(PolicyReason(code="null_metric", message="independent mutation score is null; threshold cannot pass"))
        elif mutation_score < mut_threshold:
            decision = _worse(decision, "block")
            reasons.append(
                PolicyReason(
                    code="mutation_below_threshold",
                    message=f"independent mutation score {mutation_score} < {mut_threshold}",
                )
            )

    finding_ids = {item.id for item in report.findings}
    for code in config.block_on_findings:
        if code in finding_ids:
            decision = _worse(decision, "block")
            reasons.append(PolicyReason(code="finding_block", message=f"finding {code} is configured to block"))
    for code in config.review_on_findings:
        if code in finding_ids:
            decision = _worse(decision, "review")
            reasons.append(PolicyReason(code="finding_review", message=f"finding {code} is configured for review"))

    if config.block_on_deleted_tests and report.tests.changes.nodes_removed:
        decision = _worse(decision, "block")
        reasons.append(PolicyReason(code="deleted_tests", message="deleted tests are configured to block"))

    if config.block_on_generated_failures and report.generated_tests:
        if any(item.outcome == "failed" for item in report.generated_tests.items):
            decision = _worse(decision, "block")
            reasons.append(PolicyReason(code="generated_failure", message="generated tests failed deterministically"))

    if config.block_on_potential_regressions and report.behavioral_comparison:
        if any(item.classification == "potential_regression" for item in report.behavioral_comparison.items):
            decision = _worse(decision, "block")
            reasons.append(PolicyReason(code="potential_regression", message="behavioral comparison found a potential regression"))

    stage_by_name = {}
    if report.pipeline is not None:
        stage_by_name = {stage.name: stage for stage in report.pipeline.stages}
    for name in config.require_stages:
        stage = stage_by_name.get(name)
        if stage is None or stage.status != "complete":
            decision = _worse(decision, incomplete_decision)
            reasons.append(PolicyReason(code="required_stage_incomplete", message=f"required stage {name} is not complete"))

    would = decision
    mode = "enforcing" if enforced else "informational"
    return PolicyResult(
        mode=mode,
        decision=would,  # type: ignore[arg-type]
        would_decide=would,  # type: ignore[arg-type]
        reasons=reasons,
        enforced=enforced,
    )


def evaluate_report_policy(report: Report, config: V2Config, *, enforced: bool) -> PolicyResult:
    return evaluate_policy(report, config.policy, enforced=enforced)
