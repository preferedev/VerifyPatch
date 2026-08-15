from __future__ import annotations

import hashlib
import json
import shutil
import tempfile
from datetime import datetime, timezone
from pathlib import Path

from verifypatch.artifacts import sha256_text
from verifypatch.behavior import BehaviorComparison, BehavioralResult
from verifypatch.behavior.manifest import validate_targets
from verifypatch.cleanup import register_temp_dir, register_worktree, unregister_temp_dir, unregister_worktree
from verifypatch.config import V2Config
from verifypatch.deadlines import Deadline, python_argv, run_bounded
from verifypatch.gitops import add_worktree, remove_worktree
from verifypatch.requirements import RequirementsResult
from verifypatch.stage import Reason, StageResult


def _iso_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _input_id(payload: dict) -> str:
    blob = json.dumps(payload, sort_keys=True, default=str)
    return "in-" + hashlib.sha256(blob.encode("utf-8")).hexdigest()[:12]


def _run_worker(worktree: Path, module: str, qualname: str, args: list, kwargs: dict, timeout: float) -> dict:
    request = json.dumps({"module": module, "qualname": qualname, "args": args, "kwargs": kwargs})
    completed = run_bounded(
        python_argv("-m", "verifypatch.behavior.worker"),
        cwd=worktree,
        timeout=timeout,
        input_text=request,
    )
    if completed.timed_out:
        return {"ok": False, "error": {"type": "Timeout", "message": "worker timeout"}, "preview": "timeout"}
    try:
        return json.loads(completed.stdout.strip() or "{}")
    except json.JSONDecodeError:
        return {"ok": False, "error": {"type": "InvalidWorkerOutput", "message": completed.stderr[:200]}, "preview": "invalid"}


def run_behavior(
    root: Path,
    merge_base: str,
    head_sha: str,
    config: V2Config,
    requirements: RequirementsResult,
    deadline: Deadline,
) -> tuple[StageResult, BehavioralResult]:
    started = _iso_now()
    stage = StageResult(
        name="behavior",
        status="not_requested",
        started_at=started,
        configured_deadline_seconds=config.behavior.timeout_seconds,
        effective_deadline_seconds=int(deadline.clamp(config.behavior.timeout_seconds)),
    )
    result = BehavioralResult()
    if not config.behavior.enabled:
        stage.ended_at = _iso_now()
        return stage, result
    if deadline.expired():
        stage.status = "skipped"
        stage.skip_reason = Reason(code="deadline_exhausted", message="optional stage budget exhausted")
        stage.ended_at = _iso_now()
        return stage, result
    try:
        targets = validate_targets(config)
    except Exception as exc:
        stage.status = "error"
        stage.error_reason = Reason(code="invalid_manifest", message=str(exc))
        stage.ended_at = _iso_now()
        return stage, result
    if not targets:
        stage.status = "skipped"
        stage.skip_reason = Reason(code="no_targets", message="no behavior targets configured")
        stage.ended_at = _iso_now()
        return stage, result

    req_ids = {item.id for item in requirements.items}
    work = Path(tempfile.mkdtemp(prefix="verifypatch-behavior-"))
    register_temp_dir(work)
    base_tree = work / "base"
    head_tree = work / "head"
    try:
        add_worktree(root, base_tree, merge_base)
        register_worktree(root, base_tree)
        add_worktree(root, head_tree, head_sha)
        register_worktree(root, head_tree)
        timeout = min(float(config.behavior.timeout_seconds), deadline.remaining())
        for target in targets:
            module, qualname = target.callable.split(":", 1)
            for raw in target.inputs:
                args = list(raw.get("args") or [])
                kwargs = dict(raw.get("kwargs") or {})
                payload = {"args": args, "kwargs": kwargs}
                input_id = _input_id(payload)
                digest = sha256_text(json.dumps(payload, sort_keys=True))
                base_result = _run_worker(base_tree, module, qualname, args, kwargs, timeout)
                head_result = _run_worker(head_tree, module, qualname, args, kwargs, timeout)
                classification = "unchanged"
                warnings: list[str] = []
                if base_result == head_result:
                    classification = "unchanged"
                else:
                    replay = _run_worker(head_tree, module, qualname, args, kwargs, timeout)
                    if replay != head_result:
                        classification = "nondeterministic"
                    else:
                        linked = [rid for rid in target.requirement_ids if rid in req_ids]
                        if linked:
                            classification = "expected"
                            # A linked high-confidence requirement that the head violates is a regression.
                            if head_result.get("ok") is False and base_result.get("ok") is True:
                                classification = "potential_regression"
                        else:
                            classification = "unknown"
                            warnings.append("behavior differed without a linked requirement")
                result.items.append(
                    BehaviorComparison(
                        target=target.callable,
                        input_id=input_id,
                        input_digest=digest,
                        base_preview=str(base_result.get("preview") or ""),
                        head_preview=str(head_result.get("preview") or ""),
                        classification=classification,  # type: ignore[arg-type]
                        requirement_ids=list(target.requirement_ids),
                        warnings=warnings,
                    )
                )
        stage.status = "complete"
    except Exception as exc:
        stage.status = "error"
        stage.error_reason = Reason(code="behavior_error", message=str(exc))
    finally:
        unregister_worktree(base_tree)
        unregister_worktree(head_tree)
        remove_worktree(root, base_tree)
        remove_worktree(root, head_tree)
        shutil.rmtree(work, ignore_errors=True)
        unregister_temp_dir(work)
    stage.ended_at = _iso_now()
    return stage, result
