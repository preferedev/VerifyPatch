from __future__ import annotations

import os
from datetime import datetime, timezone
from pathlib import Path

from verifypatch.artifacts import sha256_text, write_artifact
from verifypatch.config import V2Config
from verifypatch.deadlines import Deadline, python_argv, run_bounded
from verifypatch.pytest_invoke import disable_entry_point_args, scrub_plugin_env
from verifypatch.generation import GeneratedTestResult, GeneratedTestsResult
from verifypatch.generation.compiler import compile_all
from verifypatch.generation.strategies import hypothesis_available
from verifypatch.mutation.pytest_exit import classify_pytest_exit
from verifypatch.redact import redact_text
from verifypatch.requirements import Requirement, RequirementsResult
from verifypatch.stage import Reason, StageResult


def _iso_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _collect_nodeid(path: Path, cwd: Path, env: dict[str, str], timeout: float) -> str | None:
    collected = run_bounded(
        python_argv("-m", "pytest", *disable_entry_point_args(), "--collect-only", "-q", str(path)),
        cwd=cwd,
        timeout=min(30.0, timeout),
        env=scrub_plugin_env(env),
    )
    if collected.timed_out or collected.returncode not in (0, None):
        return None
    for line in (collected.stdout or "").splitlines():
        line = line.strip()
        if "::" in line and not line.startswith("="):
            return line
    return None


def run_generation(
    root: Path,
    config: V2Config,
    requirements: RequirementsResult,
    artifacts_dir: Path,
    deadline: Deadline,
) -> tuple[StageResult, GeneratedTestsResult]:
    started = _iso_now()
    stage = StageResult(
        name="generation",
        status="not_requested",
        started_at=started,
        configured_deadline_seconds=config.generation.timeout_seconds,
        effective_deadline_seconds=int(deadline.clamp(config.generation.timeout_seconds)),
    )
    result = GeneratedTestsResult(seed=config.generation.seed)
    if not config.generation.enabled:
        stage.ended_at = _iso_now()
        return stage, result
    if not config.requirements.enabled and not requirements.items:
        stage.status = "skipped"
        stage.skip_reason = Reason(code="requirements_disabled", message="generation requires requirements.enabled")
        stage.ended_at = _iso_now()
        return stage, result
    if deadline.expired():
        stage.status = "skipped"
        stage.skip_reason = Reason(code="deadline_exhausted", message="optional stage budget exhausted")
        stage.ended_at = _iso_now()
        return stage, result
    executable = [item for item in requirements.items if item.executable]
    if not executable:
        stage.status = "skipped"
        stage.skip_reason = Reason(code="no_executable_requirements", message="no high-confidence executable requirements")
        stage.ended_at = _iso_now()
        return stage, result
    if not hypothesis_available():
        stage.status = "skipped"
        stage.skip_reason = Reason(
            code="missing_dependency",
            message="hypothesis is not installed; install verifypatch[generation] or verifypatch[v2]",
        )
        stage.ended_at = _iso_now()
        return stage, result

    package = artifacts_dir / "generated_tests" / ".verifypatch_generated"
    try:
        written = compile_all(
            executable,
            package,
            max_examples=config.generation.max_examples,
            deadline_ms=config.generation.deadline_ms,
            seed=config.generation.seed,
        )
    except ValueError as exc:
        stage.status = "error"
        stage.error_reason = Reason(code="compile_failed", message=str(exc))
        stage.ended_at = _iso_now()
        return stage, result

    for req, path, source in written:
        artifact = write_artifact(
            artifacts_dir,
            f"generated_tests/.verifypatch_generated/{path.name}",
            source.encode("utf-8"),
            "generated_test",
        )
        stage.artifacts.append(artifact)
        item = _run_one(root, package, req, path, artifact.path, sha256_text(source), config, deadline)
        result.items.append(item)
        if deadline.expired():
            break
    stage.status = "complete"
    stage.ended_at = _iso_now()
    return stage, result


def _run_one(
    root: Path,
    package: Path,
    req: Requirement,
    path: Path,
    artifact_path: str,
    digest: str,
    config: V2Config,
    deadline: Deadline,
) -> GeneratedTestResult:
    env = os.environ.copy()
    pythonpath = [str(package.parent), str(root)]
    if (root / "src").is_dir():
        pythonpath.append(str(root / "src"))
    env["PYTHONPATH"] = os.pathsep.join(pythonpath)
    env = scrub_plugin_env(env)
    timeout = min(float(config.generation.timeout_seconds), deadline.remaining() or 1.0)
    nodeid = _collect_nodeid(path, root, env, timeout)
    completed = run_bounded(
        python_argv("-m", "pytest", *disable_entry_point_args(), str(path), "-q", "--tb=short"),
        cwd=root,
        timeout=timeout,
        env=env,
    )
    detail = redact_text((completed.stdout or "") + "\n" + (completed.stderr or ""))
    outcome = classify_pytest_exit(completed.returncode, completed.timed_out)
    ident = f"gen-{req.id}"
    if outcome == "timeout":
        return GeneratedTestResult(
            id=ident,
            requirement_id=req.id,
            source_artifact=artifact_path,
            outcome="timeout",
            nodeid=nodeid,
            seed=config.generation.seed,
            source_digest=digest,
            detail=detail,
        )
    if outcome == "survived":
        return GeneratedTestResult(
            id=ident,
            requirement_id=req.id,
            source_artifact=artifact_path,
            outcome="passed",
            nodeid=nodeid,
            seed=config.generation.seed,
            source_digest=digest,
        )
    if outcome in {"error", "interrupted", "no_tests"}:
        return GeneratedTestResult(
            id=ident,
            requirement_id=req.id,
            source_artifact=artifact_path,
            outcome="error" if outcome != "no_tests" else "invalid",
            nodeid=nodeid,
            seed=config.generation.seed,
            source_digest=digest,
            detail=detail,
        )
    replay = run_bounded(
        python_argv("-m", "pytest", *disable_entry_point_args(), str(path), "-q", "--tb=short"),
        cwd=root,
        timeout=min(timeout, deadline.remaining() or timeout),
        env=env,
    )
    replay_outcome = classify_pytest_exit(replay.returncode, replay.timed_out)
    if replay_outcome == "survived" or replay_outcome == "timeout":
        return GeneratedTestResult(
            id=ident,
            requirement_id=req.id,
            source_artifact=artifact_path,
            outcome="flaky",
            nodeid=nodeid,
            seed=config.generation.seed,
            source_digest=digest,
            detail=detail,
        )
    if replay_outcome != "killed":
        return GeneratedTestResult(
            id=ident,
            requirement_id=req.id,
            source_artifact=artifact_path,
            outcome="error",
            nodeid=nodeid,
            seed=config.generation.seed,
            source_digest=digest,
            detail=detail,
        )
    counterexample = None
    for line in (replay.stdout or "").splitlines():
        if "Falsifying example" in line or "assert" in line:
            counterexample = {"preview": line[:500]}
            break
    return GeneratedTestResult(
        id=ident,
        requirement_id=req.id,
        source_artifact=artifact_path,
        outcome="failed",
        nodeid=nodeid,
        seed=config.generation.seed,
        source_digest=digest,
        counterexample=counterexample,
        detail=detail,
    )
