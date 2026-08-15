from __future__ import annotations

from pathlib import Path

import pytest
from jsonschema import Draft202012Validator

from verifypatch.behavior import empty_behavior
from verifypatch.generation import empty_generated_tests
from verifypatch.model import (
    CoverageSummary,
    DiffCounts,
    Report,
    RequestedRefs,
    ResolvedRefs,
    TestsSummary,
    default_caveats,
    empty_coverage,
)
from verifypatch.mutation import empty_mutation
from verifypatch.policy import empty_policy
from verifypatch.report import validate_report
from verifypatch.requirements import empty_requirements
from verifypatch.schema import load_schema
from verifypatch.stage import Reason, StageResult, default_pipeline


def _v2_report(**kwargs) -> Report:
    data = dict(
        schema_version="2",
        tool_version="0.2.0",
        status="complete",
        requested_refs=RequestedRefs("abc", "def"),
        resolved_refs=ResolvedRefs("a" * 40, "b" * 40, "a" * 40),
        diff=DiffCounts(1, 1, 0, 0, 2, 0, 0, 0),
        coverage=CoverageSummary(4, 1, 1, 1, 1, 0.25),
        tests=TestsSummary(),
        findings=[],
        line_evidence=[],
        warnings=[],
        caveats=default_caveats(),
        pipeline=default_pipeline(),
        requirements=empty_requirements(),
        generated_tests=empty_generated_tests(),
        mutation=empty_mutation(),
        behavioral_comparison=empty_behavior(),
        policy=empty_policy(),
        artifacts={"directory": ".verifypatch/artifacts", "items": []},
    )
    data.update(kwargs)
    return Report(**data)


def test_v2_schema_loads():
    schema = load_schema("2")
    Draft202012Validator.check_schema(schema)
    Draft202012Validator.check_schema(load_schema("requirements-v1"))


@pytest.mark.parametrize("status", ["not_requested", "skipped", "complete", "incomplete", "error"])
def test_stage_status_shapes(status):
    pipeline = default_pipeline()
    extra = {}
    if status == "skipped":
        extra["skip_reason"] = Reason(code="insufficient_specification", message="thin spec")
    if status == "error":
        extra["error_reason"] = Reason(code="invalid_schema", message="bad payload")
    pipeline.stages[3] = StageResult(name="requirements", status=status, **extra)
    report = _v2_report(pipeline=pipeline)
    validate_report(report.to_json_dict())


def test_null_mutation_denominator_validates():
    mutation = empty_mutation()
    assert mutation.summary.independent_mutation_score is None
    assert mutation.summary.overall_mutation_score is None
    validate_report(_v2_report(mutation=mutation).to_json_dict())


def test_v1_payload_rejected_by_v2_schema():
    from verifypatch.model import SCHEMA_VERSION

    report = _v2_report()
    payload = report.to_json_dict()
    payload["schema_version"] = "1"
    with pytest.raises(ValueError):
        validate_report(payload)


def test_v2_does_not_appear_in_v1_serialization():
    report = _v2_report(schema_version="1")
    payload = report.to_json_dict()
    assert "pipeline" not in payload
    assert payload["schema_version"] == "1"
    validate_report(payload)


def test_zero_denominator_v2():
    report = _v2_report(coverage=empty_coverage())
    validate_report(report.to_json_dict())
