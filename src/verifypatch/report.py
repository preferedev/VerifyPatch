from __future__ import annotations

import json
from pathlib import Path

from jsonschema import Draft202012Validator

from verifypatch.model import Report
from verifypatch.schema import load_schema


def validate_report(payload: dict) -> None:
    version = str(payload.get("schema_version") or "1")
    validator = Draft202012Validator(load_schema(version))
    errors = sorted(validator.iter_errors(payload), key=lambda e: list(e.path))
    if errors:
        first = errors[0]
        path = "/".join(str(p) for p in first.path) or "<root>"
        raise ValueError(f"report failed schema validation at {path}: {first.message}")


def coverage_pct(part: int, total: int) -> str:
    if total == 0:
        return "n/a"
    return f"{(part / total) * 100:.1f}%"


def render_markdown(report: Report) -> str:
    cov = report.coverage
    total = cov.changed_executable_lines
    tests = report.tests
    lines = [
        "VERIFYPATCH",
        "Independent Verification Report",
        "",
        f"Status: {report.status}",
        f"Production files changed: {report.diff.production_files_changed}",
        f"Tests changed by PR: {report.diff.test_files_changed}",
        f"Changed executable lines: {total}",
        "",
        "PR-UNTOUCHED EVIDENCE",
        "",
        "Changed lines covered by PR-untouched tests:",
        f"{cov.covered_by_pr_untouched_tests} / {total}",
        coverage_pct(cov.covered_by_pr_untouched_tests, total),
        "",
        "PR-TOUCHED EVIDENCE",
        "",
        "Changed lines covered only by PR-touched tests:",
        f"{cov.covered_only_by_pr_touched_tests} / {total}",
        coverage_pct(cov.covered_only_by_pr_touched_tests, total),
        "",
        "TEST CHANGE ANALYSIS",
        "",
        f"Review findings: {sum(1 for f in report.findings if f.severity == 'review')}",
        f"Notice findings: {sum(1 for f in report.findings if f.severity == 'notice')}",
        f"Tests passed: {tests.outcomes.passed}",
        f"Tests skipped: {tests.outcomes.skipped}",
        f"Tests failed: {tests.outcomes.failed}",
        f"Tests xfailed: {tests.outcomes.xfailed}",
        f"Tests errored: {tests.outcomes.error}",
        "",
        "UNKNOWN EVIDENCE",
        "",
        "Changed lines covered only by ambiguous contexts:",
        f"{cov.covered_only_by_unknown_contexts} / {total}",
        coverage_pct(cov.covered_only_by_unknown_contexts, total),
        "",
        "UNCOVERED",
        "",
        f"{cov.uncovered} / {total}",
        coverage_pct(cov.uncovered, total),
        "",
    ]
    if report.findings:
        lines.extend(["FINDINGS", ""])
        for finding in report.findings:
            loc = f"{finding.path}" + (f":{finding.line}" if finding.line else "")
            lines.append(f"- [{finding.severity}] {finding.id} {loc}")
            lines.append(f"  {finding.detail}")
            if finding.before:
                lines.append("  before:")
                for row in finding.before.splitlines()[:20]:
                    lines.append(f"    {row}")
            if finding.after:
                lines.append("  after:")
                for row in finding.after.splitlines()[:20]:
                    lines.append(f"    {row}")
            lines.append("")
    if report.warnings:
        lines.extend(["WARNINGS", ""])
        for warning in report.warnings:
            lines.append(f"- {warning.code}: {warning.message}")
        lines.append("")
    lines.extend(["CAVEATS", ""])
    for caveat in report.caveats:
        lines.append(f"- {caveat}")
    lines.append("")
    if report.schema_version == "2":
        lines.extend(_render_v2_sections(report))
    return "\n".join(lines) + "\n"


def _render_v2_sections(report: Report) -> list[str]:
    lines: list[str] = []
    pipeline = report.pipeline
    if pipeline is not None:
        lines.extend(["PIPELINE", ""])
        for stage in pipeline.stages:
            extra = ""
            if stage.skip_reason:
                extra = f" ({stage.skip_reason.code})"
            elif stage.error_reason:
                extra = f" ({stage.error_reason.code})"
            lines.append(f"- {stage.name}: {stage.status}{extra}")
        if pipeline.optional_deadline_exhausted:
            lines.append("- optional stage budget exhausted")
        lines.append("")
    if report.requirements is not None:
        lines.extend(["REQUIREMENTS", ""])
        lines.append(f"Count: {len(report.requirements.items)}")
        if report.requirements.provider:
            lines.append(f"Provider: {report.requirements.provider}")
        if report.requirements.model:
            lines.append(f"Model: {report.requirements.model}")
        lines.append("")
    if report.generated_tests is not None and report.generated_tests.items:
        lines.extend(["GENERATED TESTS", ""])
        for item in report.generated_tests.items:
            lines.append(f"- {item.id}: {item.outcome} ({item.requirement_id})")
        lines.append("")
    if report.mutation is not None:
        summary = report.mutation.summary
        lines.extend(["MUTATION", ""])
        lines.append(f"Backend: {report.mutation.backend or 'n/a'}")
        if report.mutation.backend_version:
            lines.append(f"Backend version: {report.mutation.backend_version}")
        lines.append(f"Selected: {summary.selected} / {summary.candidate}")
        indep = summary.independent_mutation_score
        overall = summary.overall_mutation_score
        lines.append(f"Independent mutation score: {'n/a' if indep is None else f'{indep:.3f}'}")
        lines.append(f"Overall mutation score: {'n/a' if overall is None else f'{overall:.3f}'}")
        lines.append("")
    if report.behavioral_comparison is not None and report.behavioral_comparison.items:
        lines.extend(["BEHAVIORAL COMPARISON", ""])
        for item in report.behavioral_comparison.items:
            lines.append(f"- {item.target} {item.input_id}: {item.classification}")
        lines.append("")
    if report.policy is not None:
        lines.extend(["POLICY", ""])
        lines.append(f"Mode: {report.policy.mode}")
        lines.append(f"Decision: {report.policy.decision}")
        lines.append(f"Would decide: {report.policy.would_decide}")
        for reason in report.policy.reasons:
            lines.append(f"- {reason.code}: {reason.message}")
        lines.append("")
    if report.artifacts and report.artifacts.get("items"):
        lines.extend(["ARTIFACTS", ""])
        for item in report.artifacts["items"]:
            lines.append(f"- {item.get('path')} ({item.get('sha256', '')[:12]})")
        lines.append("")
    return lines


def write_reports(report: Report, json_out: Path, md_out: Path) -> dict:
    payload = report.to_json_dict()
    validate_report(payload)
    json_out.parent.mkdir(parents=True, exist_ok=True)
    json_out.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    md_out.parent.mkdir(parents=True, exist_ok=True)
    md_out.write_text(render_markdown(report), encoding="utf-8")
    return payload
