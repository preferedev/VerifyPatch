from __future__ import annotations

import os
import shutil
import tempfile
from datetime import datetime, timezone
from pathlib import Path

from verifypatch.artifacts import write_artifact
from verifypatch.classify import PathClass
from verifypatch.cleanup import register_temp_dir, unregister_temp_dir
from verifypatch.config import V2Config
from verifypatch.deadlines import Deadline, python_argv, run_bounded
from verifypatch.pytest_invoke import disable_entry_point_args, scrub_plugin_env
from verifypatch.generation import GeneratedTestResult, GeneratedTestsResult
from verifypatch.limits import MUTANT_TIMEOUT_CEILING_SECONDS, MUTANT_TIMEOUT_FLOOR_SECONDS
from verifypatch.model import Report
from verifypatch.mutation import MutantRecord, MutationResult, MutationSummary, score
from verifypatch.mutation.backend import InvalidMutation, MutationBackend, MutationSpec
from verifypatch.mutation.cosmic_ray_backend import load_backend
from verifypatch.mutation.pytest_exit import classify_pytest_exit
from verifypatch.mutation.selection import cap_specs, dedupe, filter_changed_lines, mutant_id
from verifypatch.mutation.semantic import compact_diff, mutation_is_semantic
from verifypatch.provenance import classify_context
from verifypatch.redact import redact_text
from verifypatch.stage import Reason, StageResult


def _iso_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _changed_executable_lines(report: Report) -> dict[str, set[int]]:
    mapping: dict[str, set[int]] = {}
    for item in report.line_evidence:
        mapping.setdefault(item.path, set()).add(item.line)
    return mapping


def test_path_from_nodeid(nodeid: str) -> str | None:
    head = nodeid.split("::", 1)[0].replace("\\", "/")
    if head.endswith(".py"):
        return head
    return None


def _partition_node_ids(
    report: Report,
    classified: dict[str, PathClass],
    node_files: dict[str, str | None],
    root: Path,
    config,
) -> tuple[list[str], list[str]]:
    untouched: list[str] = []
    touched: list[str] = []
    seen: set[str] = set()
    mapping = dict(node_files)
    for evidence in report.line_evidence:
        for nodeid in evidence.covering_node_ids:
            if nodeid not in mapping:
                mapping[nodeid] = test_path_from_nodeid(nodeid)
            if nodeid in seen:
                continue
            seen.add(nodeid)
            kind, _notes = classify_context(nodeid, mapping, root, classified, config)
            if kind == "pr_untouched":
                untouched.append(nodeid)
            elif kind == "pr_touched":
                touched.append(nodeid)
    return untouched, touched


def per_mutant_timeout(auto_or_seconds: int | str, baseline_seconds: float) -> float:
    if auto_or_seconds != "auto":
        return float(auto_or_seconds)
    return max(MUTANT_TIMEOUT_FLOOR_SECONDS, min(MUTANT_TIMEOUT_CEILING_SECONDS, 2 * baseline_seconds))


def _generated_selectors(generated: GeneratedTestsResult) -> list[GeneratedTestResult]:
    return [
        item
        for item in generated.items
        if item.outcome == "passed" and (item.nodeid or item.source_artifact)
    ]


def run_mutation(
    root: Path,
    head_sha: str,
    config: V2Config,
    report: Report,
    classified: dict[str, PathClass],
    node_files: dict[str, str | None],
    v1_config,
    generated: GeneratedTestsResult,
    artifacts_dir: Path,
    deadline: Deadline,
    backend: MutationBackend | None = None,
    baseline_seconds: float = 1.0,
    provenance_failed: bool = False,
    generated_failed: bool = False,
) -> tuple[StageResult, MutationResult]:
    started = _iso_now()
    stage = StageResult(
        name="mutation",
        status="not_requested",
        started_at=started,
        configured_deadline_seconds=config.mutation.timeout_seconds,
        effective_deadline_seconds=int(deadline.clamp(config.mutation.timeout_seconds)),
    )
    result = MutationResult(backend=config.mutation.backend)
    if not config.mutation.enabled:
        stage.ended_at = _iso_now()
        return stage, result
    if provenance_failed or generated_failed:
        stage.status = "skipped"
        stage.skip_reason = Reason(code="baseline_failed", message="mutation skipped because a baseline partition failed")
        stage.ended_at = _iso_now()
        return stage, result
    if deadline.expired():
        stage.status = "skipped"
        stage.skip_reason = Reason(code="deadline_exhausted", message="optional stage budget exhausted")
        stage.ended_at = _iso_now()
        return stage, result

    loaded = backend or load_backend(
        config.mutation.backend,
        config.mutation.operators,
        fallback=config.mutation.fallback,
    )
    if isinstance(loaded, Reason):
        stage.status = "skipped"
        stage.skip_reason = loaded
        result.backend = config.mutation.backend
        stage.ended_at = _iso_now()
        return stage, result

    result.backend = loaded.name
    result.backend_version = getattr(loaded, "version", None)
    if config.mutation.backend in {"cosmic-ray", "cosmic_ray"} and loaded.name != "cosmic-ray":
        stage.warnings.append(
            {
                "code": "fallback_backend",
                "message": f"requested cosmic-ray but running {loaded.name} because mutation.fallback={config.mutation.fallback!r}",
            }
        )
    stage.tool_versions = {"backend": loaded.name, "backend_version": str(result.backend_version or "")}

    changed = _changed_executable_lines(report)
    files = sorted(changed)
    try:
        candidates = loaded.list_mutations(root, files)
    except Exception as exc:
        stage.status = "error"
        stage.error_reason = Reason(code="backend_error", message=str(exc))
        stage.ended_at = _iso_now()
        return stage, result
    filtered = filter_changed_lines(candidates, changed)
    unique = dedupe(filtered, head_sha)
    selected = cap_specs(unique, head_sha, config.mutation.max_mutants)
    result.summary.candidate = len(unique)
    result.summary.selected = len(selected)
    if not selected:
        stage.status = "complete"
        stage.ended_at = _iso_now()
        return stage, result

    untouched, touched = _partition_node_ids(report, classified, node_files, root, v1_config)
    generated_items = _generated_selectors(generated)
    timeout = per_mutant_timeout(config.mutation.per_mutant_timeout_seconds, baseline_seconds)
    excluded = set(config.mutation.exclude_ids)

    work_root = Path(tempfile.mkdtemp(prefix="verifypatch-mut-"))
    register_temp_dir(work_root)
    try:
        for spec in selected:
            ident = mutant_id(head_sha, spec)
            if ident in excluded:
                record = _record(head_sha, spec, "excluded", None, [], None, spec.original and compact_diff(spec.original, spec.mutated, spec.path) or "")
                result.mutants.append(record)
                result.summary.excluded += 1
                continue
            if deadline.expired():
                record = _record(head_sha, spec, "not_run", None, [], None, "")
                result.mutants.append(record)
                result.summary.not_run += 1
                continue
            record = _execute_mutant(
                root,
                head_sha,
                spec,
                loaded,
                untouched,
                touched,
                generated_items,
                timeout,
                deadline,
                work_root,
                artifacts_dir,
            )
            result.mutants.append(record)
            _tally(result.summary, record)
    finally:
        shutil.rmtree(work_root, ignore_errors=True)
        unregister_temp_dir(work_root)

    valid = (
        result.summary.killed_by_pr_untouched
        + result.summary.killed_by_pr_touched
        + result.summary.killed_by_generated
        + result.summary.survived
    )
    result.summary.independent_mutation_score = score(result.summary.killed_by_pr_untouched, valid)
    all_killed = (
        result.summary.killed_by_pr_untouched
        + result.summary.killed_by_pr_touched
        + result.summary.killed_by_generated
    )
    result.summary.overall_mutation_score = score(all_killed, valid)
    stage.status = "complete"
    stage.ended_at = _iso_now()
    return stage, result


def _tally(summary: MutationSummary, record: MutantRecord) -> None:
    if record.result == "killed" and record.killing_origin == "pr_untouched":
        summary.killed_by_pr_untouched += 1
    elif record.result == "killed" and record.killing_origin == "pr_touched":
        summary.killed_by_pr_touched += 1
    elif record.result == "killed" and record.killing_origin == "generated":
        summary.killed_by_generated += 1
    elif record.result == "survived":
        summary.survived += 1
    elif record.result == "timeout":
        summary.timeout += 1
    elif record.result == "invalid":
        summary.invalid += 1
    elif record.result == "error":
        summary.error += 1
    elif record.result == "not_run":
        summary.not_run += 1
    elif record.result == "excluded":
        summary.excluded += 1


def _record(
    head_sha: str,
    spec: MutationSpec,
    result: str,
    origin: str | None,
    executed: list[str],
    duration_ms: int | None,
    diff: str,
    output_artifact: str | None = None,
) -> MutantRecord:
    return MutantRecord(
        id=mutant_id(head_sha, spec),
        path=spec.path,
        start_pos=list(spec.start_pos),
        end_pos=list(spec.end_pos),
        operator=spec.operator,
        diff=diff,
        selection_reason="changed_executable_line",
        result=result,  # type: ignore[arg-type]
        killing_origin=origin,  # type: ignore[arg-type]
        executed_ids=executed,
        duration_ms=duration_ms,
        output_artifact=output_artifact,
        target_node=spec.target_node or None,
    )


def _persist_output(artifacts_dir: Path, ident: str, text: str) -> str | None:
    if not text.strip():
        return None
    try:
        ref = write_artifact(artifacts_dir, f"mutants/{ident}.txt", text.encode("utf-8"), "mutant_output")
    except ValueError:
        return None
    return ref.path


def _mutant_pythonpath(copy: Path) -> str:
    parts = [str(copy)]
    src = copy / "src"
    if src.is_dir():
        parts.append(str(src))
    return os.pathsep.join(parts)


def _materialize_generated(copy: Path, items: list[GeneratedTestResult], artifacts_dir: Path) -> list[str]:
    selectors: list[str] = []
    dest_dir = copy / ".verifypatch_generated"
    dest_dir.mkdir(parents=True, exist_ok=True)
    (dest_dir / "__init__.py").write_text("", encoding="utf-8")
    for item in items:
        source_text = None
        if item.source_artifact:
            artifact_path = artifacts_dir / item.source_artifact
            if artifact_path.is_file():
                source_text = artifact_path.read_text(encoding="utf-8")
        if source_text is None:
            continue
        name = Path(item.source_artifact).name if item.source_artifact else f"{item.id}.py"
        dest = dest_dir / name
        dest.write_text(source_text, encoding="utf-8")
        if item.nodeid and "::" in item.nodeid:
            selectors.append(f".verifypatch_generated/{name}::{item.nodeid.split('::', 1)[1]}")
        else:
            selectors.append(str(Path(".verifypatch_generated") / name))
    return selectors


def _execute_mutant(
    root: Path,
    head_sha: str,
    spec: MutationSpec,
    backend: MutationBackend,
    untouched: list[str],
    touched: list[str],
    generated_items: list[GeneratedTestResult],
    timeout: float,
    deadline: Deadline,
    work_root: Path,
    artifacts_dir: Path,
) -> MutantRecord:
    copy = work_root / mutant_id(head_sha, spec)
    if copy.exists():
        shutil.rmtree(copy)
    shutil.copytree(root, copy, ignore=shutil.ignore_patterns(".git", ".verifypatch", ".verifypatch_generated"))
    target = copy / spec.path
    before = target.read_text(encoding="utf-8") if target.is_file() else ""
    try:
        backend.apply(copy, spec)
    except InvalidMutation:
        return _record(head_sha, spec, "invalid", None, [], None, "")
    except Exception:
        return _record(head_sha, spec, "invalid", None, [], None, "")
    after = target.read_text(encoding="utf-8") if target.is_file() else ""
    ok, _reason = mutation_is_semantic(before, after)
    if not ok:
        return _record(head_sha, spec, "invalid", None, [], None, compact_diff(before, after, spec.path))
    diff = compact_diff(before, after, spec.path)
    generated_selectors = _materialize_generated(copy, generated_items, artifacts_dir)
    partitions = [
        ("pr_untouched", untouched),
        ("pr_touched", touched),
        ("generated", generated_selectors),
    ]
    executed: list[str] = []
    env = scrub_plugin_env(os.environ.copy())
    env["PYTHONPATH"] = _mutant_pythonpath(copy)
    env.pop("PYTHONSAFEPATH", None)
    attempted = False
    ran_tests = False
    last_detail = ""
    ident = mutant_id(head_sha, spec)
    for origin, node_ids in partitions:
        if not node_ids:
            continue
        attempted = True
        argv = python_argv(
            "-m",
            "pytest",
            *disable_entry_point_args(),
            "-q",
            "--tb=no",
            "--",
            *node_ids,
        )
        completed = run_bounded(
            argv,
            cwd=copy,
            timeout=min(timeout, deadline.remaining() or timeout),
            env=env,
        )
        executed.extend(node_ids)
        last_detail = redact_text((completed.stdout or "") + "\n" + (completed.stderr or ""))
        outcome = classify_pytest_exit(completed.returncode, completed.timed_out)
        artifact = _persist_output(artifacts_dir, ident, last_detail) if outcome != "survived" else None
        if outcome == "timeout":
            return _record(
                head_sha,
                spec,
                "timeout",
                None,
                executed,
                int(completed.duration_seconds * 1000),
                diff,
                artifact,
            )
        if outcome == "killed":
            return _record(
                head_sha,
                spec,
                "killed",
                origin,
                executed,
                int(completed.duration_seconds * 1000),
                diff,
                artifact,
            )
        if outcome in {"error", "interrupted"}:
            return _record(
                head_sha,
                spec,
                "error",
                None,
                executed,
                int(completed.duration_seconds * 1000),
                diff,
                artifact,
            )
        if outcome == "survived":
            ran_tests = True
            continue
        # no_tests: not a kill; try the next origin
    if not attempted or not ran_tests:
        return _record(
            head_sha,
            spec,
            "error",
            None,
            executed,
            None,
            diff,
            _persist_output(artifacts_dir, ident, last_detail),
        )
    return _record(head_sha, spec, "survived", None, executed, None, diff)
