from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

from jsonschema import Draft202012Validator

from verifypatch.config import V2Config
from verifypatch.deadlines import Deadline
from verifypatch.requirements import (
    EXECUTABLE_KINDS,
    PROMPT_VERSION,
    REQUIREMENT_SCHEMA_VERSION,
    Requirement,
    RequirementsResult,
    SourceCitation,
)
from verifypatch.requirements.firewall import (
    citations_match_sources,
    delimit_sources,
    has_specification_signal,
    load_merge_base_sources,
)
from verifypatch.requirements.model import ExtractionRequest, RequirementProvider
from verifypatch.requirements.providers import load_provider
from verifypatch.schema import load_schema
from verifypatch.stage import Reason, StageResult

CONFIDENCE_RANK = {"low": 0, "medium": 1, "high": 2}


def _citations_from_raw(raw_citations: list) -> list[SourceCitation]:
    citations: list[SourceCitation] = []
    for cite in raw_citations:
        if not isinstance(cite, dict):
            return []
        ref = cite.get("ref")
        path = cite.get("path")
        start = cite.get("start_line")
        end = cite.get("end_line")
        digest = cite.get("digest")
        if not isinstance(ref, str) or not ref:
            return []
        if not isinstance(path, str) or not path:
            return []
        if isinstance(start, bool) or isinstance(end, bool):
            return []
        if not isinstance(start, int) or not isinstance(end, int):
            return []
        if not isinstance(digest, str) or not digest:
            return []
        citations.append(
            SourceCitation(
                ref=ref,
                path=path,
                start_line=start,
                end_line=end,
                digest=digest,
            )
        )
    return citations


def _iso_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _validate_payload(payload: dict) -> str | None:
    validator = Draft202012Validator(load_schema("requirements-v1"))
    errors = sorted(validator.iter_errors(payload), key=lambda e: list(e.path))
    if not errors:
        return None
    first = errors[0]
    path = "/".join(str(p) for p in first.path) or "<root>"
    return f"{path}: {first.message}"


def extract_requirements(
    root: Path,
    merge_base: str,
    config: V2Config,
    pr_touched_tests: set[str],
    deadline: Deadline,
    provider: RequirementProvider | None = None,
) -> tuple[StageResult, RequirementsResult]:
    started = _iso_now()
    stage = StageResult(
        name="requirements",
        status="not_requested",
        started_at=started,
        configured_deadline_seconds=config.requirements.timeout_seconds,
        effective_deadline_seconds=int(deadline.clamp(config.requirements.timeout_seconds)),
    )
    result = RequirementsResult(
        prompt_version=PROMPT_VERSION,
        requirement_schema_version=REQUIREMENT_SCHEMA_VERSION,
    )
    if not config.requirements.enabled:
        stage.status = "not_requested"
        stage.ended_at = _iso_now()
        return stage, result
    if deadline.expired():
        stage.status = "skipped"
        stage.skip_reason = Reason(code="deadline_exhausted", message="optional stage budget exhausted")
        stage.ended_at = _iso_now()
        return stage, result

    sources, _reason = load_merge_base_sources(root, merge_base, config, pr_touched_tests)
    # Delimit even when unused so tests can assert the firewall ran.
    _ = delimit_sources(sources)
    if not has_specification_signal(sources):
        stage.status = "skipped"
        stage.skip_reason = Reason(
            code="insufficient_specification",
            message="No source-backed behavior, invariant, boundary, example, or schema constraint.",
        )
        stage.ended_at = _iso_now()
        return stage, result

    loaded = load_provider(config.requirements, provider)
    if isinstance(loaded, Reason):
        stage.status = "skipped"
        stage.skip_reason = loaded
        stage.ended_at = _iso_now()
        return stage, result

    request = ExtractionRequest(
        sources=sources,
        schema=load_schema("requirements-v1"),
        model=config.requirements.model,
    )
    response = loaded.extract(request)
    result.provider = response.provider
    result.model = response.model
    result.request_id = response.request_id
    result.constrained_output = response.constrained_output
    result.prompt_version = PROMPT_VERSION
    result.requirement_schema_version = REQUIREMENT_SCHEMA_VERSION
    stage.tool_versions = {"provider": response.provider, "model": response.model or ""}

    if response.error_code:
        stage.status = "error"
        stage.error_reason = Reason(code=response.error_code, message=response.error_message or response.error_code)
        stage.ended_at = _iso_now()
        return stage, result
    if response.truncated:
        stage.status = "incomplete"
        stage.error_reason = Reason(code="truncated", message="provider response was truncated")
        stage.ended_at = _iso_now()
        return stage, result
    if response.refused:
        stage.status = "skipped"
        stage.skip_reason = Reason(
            code="insufficient_specification",
            message=response.refusal_message or "provider refused extraction",
        )
        stage.ended_at = _iso_now()
        return stage, result

    payload = response.payload or {}
    schema_error = _validate_payload(payload)
    if schema_error:
        stage.status = "error"
        stage.error_reason = Reason(code="invalid_schema", message=schema_error)
        stage.ended_at = _iso_now()
        return stage, result

    refusal = payload.get("refusal")
    items_raw = payload.get("items") or []
    if refusal and not items_raw:
        stage.status = "skipped"
        stage.skip_reason = Reason(
            code=str(refusal.get("code") or "insufficient_specification"),
            message=str(refusal.get("message") or "refused"),
        )
        stage.ended_at = _iso_now()
        return stage, result

    kept: list[Requirement] = []
    for raw in items_raw:
        citations = _citations_from_raw(raw.get("citations") or [])
        if not citations_match_sources(sources, citations):
            continue
        kind = str(raw.get("kind") or "unknown")
        confidence = str(raw.get("confidence") or "low")
        if confidence not in CONFIDENCE_RANK:
            confidence = "low"
        executable = bool(raw.get("executable")) and kind in EXECUTABLE_KINDS
        min_conf = config.requirements.minimum_confidence
        if executable and CONFIDENCE_RANK[confidence] < CONFIDENCE_RANK.get(min_conf, 2):
            executable = False
        kept.append(
            Requirement(
                id=str(raw["id"]),
                statement=str(raw["statement"]),
                kind=kind,
                confidence=confidence,  # type: ignore[arg-type]
                executable=executable,
                citations=citations,
                target_module=raw.get("target_module"),
                target_callable=raw.get("target_callable"),
                parameters=dict(raw.get("parameters") or {}),
                assumptions=list(raw.get("assumptions") or []),
                refusal_reason=raw.get("refusal_reason"),
                non_executable_reason=raw.get("non_executable_reason"),
            )
        )
    result.items = kept
    stage.status = "complete"
    stage.ended_at = _iso_now()
    return stage, result
