from __future__ import annotations

import json
from pathlib import Path

from jsonschema import Draft202012Validator

from verifypatch.requirements import (
    PROMPT_VERSION,
    REQUIREMENT_SCHEMA_VERSION,
    Requirement,
    RequirementsResult,
)
from verifypatch.requirements.extract import _citations_from_raw
from verifypatch.requirements.firewall import citations_match_sources, load_merge_base_sources
from verifypatch.schema import load_schema
from verifypatch.stage import Reason


def _requirement_from_raw(raw: dict, merge_base: str) -> Requirement:
    citations = _citations_from_raw(raw.get("citations") or [])
    return Requirement(
        id=str(raw["id"]),
        statement=str(raw["statement"]),
        kind=str(raw.get("kind") or "unknown"),
        confidence=raw.get("confidence") or "low",
        executable=bool(raw.get("executable")),
        citations=citations,
        target_module=raw.get("target_module"),
        target_callable=raw.get("target_callable"),
        parameters=dict(raw.get("parameters") or {}),
        assumptions=list(raw.get("assumptions") or []),
        refusal_reason=raw.get("refusal_reason"),
        non_executable_reason=raw.get("non_executable_reason"),
    )


def _as_requirements_payload(payload: dict) -> dict:
    if payload.get("schema_version") == "2" or "requirements" in payload:
        block = payload.get("requirements") or {}
        return {
            "schema_version": str(block.get("requirement_schema_version") or "1"),
            "prompt_version": str(block.get("prompt_version") or PROMPT_VERSION),
            "provider": block.get("provider"),
            "model": block.get("model"),
            "request_id": block.get("request_id"),
            "constrained_output": block.get("constrained_output"),
            "items": list(block.get("items") or []),
        }
    return payload


def load_requirements_artifact(
    path: Path,
    root: Path | None = None,
    merge_base: str | None = None,
    config=None,
) -> tuple[RequirementsResult | None, Reason | None]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        return None, Reason(code="invalid_requirements_artifact", message=f"requirements file is not valid JSON: {exc}")
    if not isinstance(payload, dict):
        return None, Reason(code="invalid_requirements_artifact", message="requirements file must be a JSON object")
    req_payload = _as_requirements_payload(payload)
    validator = Draft202012Validator(load_schema("requirements-v1"))
    errors = sorted(validator.iter_errors(req_payload), key=lambda e: list(e.path))
    if errors:
        first = errors[0]
        loc = "/".join(str(p) for p in first.path) or "<root>"
        return None, Reason(code="invalid_requirements_artifact", message=f"{loc}: {first.message}")

    merge = merge_base or ""
    result = RequirementsResult(
        provider=req_payload.get("provider"),
        model=req_payload.get("model"),
        prompt_version=req_payload.get("prompt_version") or PROMPT_VERSION,
        requirement_schema_version=req_payload.get("schema_version") or REQUIREMENT_SCHEMA_VERSION,
        request_id=req_payload.get("request_id"),
        constrained_output=req_payload.get("constrained_output"),
    )
    items = [_requirement_from_raw(raw, merge) for raw in req_payload.get("items") or []]
    if root is not None and merge_base and config is not None:
        sources, _reason = load_merge_base_sources(root, merge_base, config, set())
        kept: list[Requirement] = []
        invalid = False
        for item in items:
            if citations_match_sources(sources, item.citations):
                kept.append(item)
            else:
                invalid = True
        if invalid:
            result.items = []
            return result, Reason(
                code="citation_mismatch",
                message="requirements artifact citations do not match the exact merge-base snapshot, path, ordered line range, and range digest",
            )
        result.items = kept
    else:
        result.items = items
    return result, None
