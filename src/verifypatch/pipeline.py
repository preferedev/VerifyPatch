from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

from verifypatch.artifacts import artifact_manifest
from verifypatch.behavior.compare import run_behavior
from verifypatch.config import V2Config, apply_cli_overrides, load_v2_config
from verifypatch.deadlines import Deadline, start_deadline
from verifypatch.engine import run_check
from verifypatch.generation.runner import run_generation
from verifypatch.gitops import merge_base_sha, resolve_sha
from verifypatch.model import (
    SCHEMA_VERSION_V2,
    DiffCounts,
    Report,
    RequestedRefs,
    ResolvedRefs,
    TestsSummary,
    default_caveats,
    empty_coverage,
)
from verifypatch.requirements import RequirementsResult
from verifypatch.mutation.runner import run_mutation
from verifypatch.policy.evaluate import evaluate_report_policy
from verifypatch.requirements.artifact import load_requirements_artifact
from verifypatch.requirements.extract import extract_requirements
from verifypatch.stage import PipelineSummary, StageResult, empty_stage


def _iso_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _preflight_stage() -> StageResult:
    return StageResult(
        name="preflight",
        status="complete",
        started_at=_iso_now(),
        ended_at=_iso_now(),
        tool_versions={},
    )


def _load_requirements_file(path: Path, root: Path, merge_base: str, v2: V2Config):
    return load_requirements_artifact(path, root=root, merge_base=merge_base, config=v2)


def _is_subject_sys_path(item: str, root: Path) -> bool:
    if item in {"", "."}:
        try:
            cwd = Path.cwd().resolve()
        except OSError:
            return False
        return cwd == root or cwd == root / "src"
    try:
        resolved = Path(item).resolve()
    except OSError:
        return False
    return resolved == root or resolved == root / "src"


def run_requirements_only(root: Path, base: str, head: str, v2: V2Config, provider=None) -> Report:
    """Firewall + provider only. Does not execute repository tests or import head modules."""
    import sys

    # Keep the subject tree off sys.path so a requirements-only job cannot
    # import or execute pull-request Python.
    root = root.resolve()
    sys.path[:] = [item for item in sys.path if not _is_subject_sys_path(item, root)]
    v2.requirements.enabled = True
    v2.generation.enabled = False
    v2.mutation.enabled = False
    v2.behavior.enabled = False
    requested = RequestedRefs(base=base, head=head)
    base_sha = resolve_sha(root, base)
    head_sha = resolve_sha(root, head)
    merge_base = merge_base_sha(root, base_sha, head_sha)
    resolved = ResolvedRefs(base=base_sha, head=head_sha, merge_base=merge_base)
    deadline = start_deadline(v2.runtime.optional_timeout_seconds)
    req_stage, requirements = extract_requirements(root, merge_base, v2, set(), deadline, provider=provider)
    report = Report(
        schema_version=SCHEMA_VERSION_V2,
        tool_version=__import__("verifypatch").__version__,
        status="complete" if req_stage.status in {"complete", "skipped"} else "incomplete",
        requested_refs=requested,
        resolved_refs=resolved,
        diff=DiffCounts(0, 0, 0, 0, 0, 0, 0, 0),
        coverage=empty_coverage(),
        tests=TestsSummary(),
        findings=[],
        line_evidence=[],
        warnings=[],
        caveats=default_caveats()
        + [
            "This run extracted requirements without executing head tests.",
            "Generated tests are a third evidence class and are never PR-untouched evidence.",
        ],
        pipeline=PipelineSummary(
            stages=[
                _preflight_stage(),
                StageResult(name="git", status="complete", started_at=_iso_now(), ended_at=_iso_now()),
                empty_stage("provenance"),
                req_stage,
                empty_stage("generation"),
                empty_stage("mutation"),
                empty_stage("behavior"),
                empty_stage("policy"),
            ],
            optional_deadline_seconds=v2.runtime.optional_timeout_seconds,
        ),
        requirements=requirements,
    )
    return report


def run_verify(
    root: Path,
    base: str,
    head: str,
    pytest_args: list[str],
    timeout: int | None,
    v2: V2Config,
    *,
    enforce: bool = False,
    provider=None,
    mutation_backend=None,
    requirements_only: bool = False,
    requirements_file: Path | None = None,
) -> Report:
    if requirements_only:
        return run_requirements_only(root, base, head, v2, provider=provider)

    deadline = start_deadline(v2.runtime.optional_timeout_seconds)
    artifacts_dir = root / v2.runtime.artifacts_dir
    artifacts_dir.mkdir(parents=True, exist_ok=True)

    preflight = _preflight_stage()
    report = run_check(root, base, head, pytest_args, timeout=timeout)
    git_stage = StageResult(
        name="git",
        status="complete" if report.resolved_refs else "error",
        started_at=_iso_now(),
        ended_at=_iso_now(),
    )
    provenance = StageResult(
        name="provenance",
        status="error" if report.status == "error" else ("incomplete" if report.status == "incomplete" else "complete"),
        started_at=_iso_now(),
        ended_at=_iso_now(),
        warnings=[{"code": w.code, "message": w.message, "path": w.path} for w in report.warnings],
    )

    merge_base = report.resolved_refs.merge_base if report.resolved_refs else ""
    head_sha = report.resolved_refs.head if report.resolved_refs else ""
    pr_touched_tests = set()
    # Conservative: every changed test file is PR-touched infrastructure.
    # Exact node mapping is reconstructed after the v1 plugin run inside provenance.

    if requirements_file is not None:
        from verifypatch.stage import Reason

        requirements, load_error = _load_requirements_file(requirements_file, root, merge_base, v2)
        if requirements is None:
            requirements = RequirementsResult()
        req_stage = StageResult(
            name="requirements",
            status="error" if load_error and load_error.code == "invalid_requirements_artifact" else ("incomplete" if load_error else "complete"),
            started_at=_iso_now(),
            ended_at=_iso_now(),
            skip_reason=None,
            error_reason=load_error,
            tool_versions={"source": "requirements_file"},
        )
    else:
        req_stage, requirements = extract_requirements(
            root, merge_base, v2, pr_touched_tests, deadline, provider=provider
        )
    # Optional-stage failure must not erase v1 evidence.
    gen_stage, generated = run_generation(root, v2, requirements, artifacts_dir, deadline)

    provenance_failed = report.status == "error" or (report.tests.outcomes.failed + report.tests.outcomes.error) > 0
    generated_failed = any(item.outcome == "failed" for item in generated.items)
    from verifypatch.classify import classify_diffs
    from verifypatch.config import load_config
    from verifypatch.gitops import collect_diff

    classified = {}
    node_files: dict[str, str | None] = {}
    v1_config = load_config(root)
    if report.resolved_refs:
        from verifypatch.mutation.runner import test_path_from_nodeid

        diff = collect_diff(root, merge_base, head_sha)
        classified = classify_diffs(diff.files, v1_config)
        for evidence in report.line_evidence:
            for nodeid in evidence.covering_node_ids:
                node_files.setdefault(nodeid, test_path_from_nodeid(nodeid))

    mut_stage, mutation = run_mutation(
        root,
        head_sha,
        v2,
        report,
        classified,
        node_files,
        v1_config,
        generated,
        artifacts_dir,
        deadline,
        backend=mutation_backend,
        provenance_failed=provenance_failed,
        generated_failed=generated_failed,
    )
    beh_stage, behavior = run_behavior(root, merge_base, head_sha, v2, requirements, deadline)

    report.schema_version = SCHEMA_VERSION_V2
    report.requirements = requirements
    report.generated_tests = generated
    report.mutation = mutation
    report.behavioral_comparison = behavior
    report.pipeline = PipelineSummary(
        stages=[preflight, git_stage, provenance, req_stage, gen_stage, mut_stage, beh_stage, empty_stage("policy")],
        optional_deadline_seconds=v2.runtime.optional_timeout_seconds,
        optional_deadline_exhausted=deadline.expired(),
    )
    policy = evaluate_report_policy(report, v2, enforced=enforce)
    policy_stage = StageResult(
        name="policy",
        status="complete",
        started_at=_iso_now(),
        ended_at=_iso_now(),
    )
    report.pipeline.stages[-1] = policy_stage
    report.policy = policy
    items = []
    for stage in report.pipeline.stages:
        items.extend(stage.artifacts)
    report.artifacts = artifact_manifest(v2.runtime.artifacts_dir, items)
    extra = [
        "Generated tests are a third evidence class and are never PR-untouched evidence.",
        "Independent Mutation Score is not a correctness score.",
        "Policy is informational unless --enforce is supplied.",
    ]
    for caveat in extra:
        if caveat not in report.caveats:
            report.caveats.append(caveat)
    return report


def config_for_verify(root: Path, config_path: Path | None, overrides: dict) -> V2Config:
    cfg = load_v2_config(root, config_path)
    return apply_cli_overrides(cfg, overrides)
