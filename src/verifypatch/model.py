from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Literal

from verifypatch.behavior import BehavioralResult, empty_behavior
from verifypatch.generation import GeneratedTestsResult, empty_generated_tests
from verifypatch.mutation import MutationResult, empty_mutation
from verifypatch.policy import PolicyResult, empty_policy
from verifypatch.requirements import RequirementsResult, empty_requirements
from verifypatch.stage import PipelineSummary, default_pipeline

SCHEMA_VERSION = "1"
SCHEMA_VERSION_V2 = "2"
V2_REPORT_KEYS = (
    "pipeline",
    "requirements",
    "generated_tests",
    "mutation",
    "behavioral_comparison",
    "policy",
    "artifacts",
)

Status = Literal["complete", "incomplete", "error"]
LineClassification = Literal[
    "pr_untouched",
    "pr_touched_only",
    "unknown_only",
    "uncovered",
]
FindingSeverity = Literal["notice", "review"]
FindingCode = Literal[
    "TEST_SKIP_ADDED",
    "TEST_XFAIL_ADDED",
    "BROAD_EXCEPT_ADDED",
    "ASSERT_TO_TRUTHY",
    "TEST_REMOVED",
    "ASSERT_COUNT_DROP",
]


def _drop_none(value: Any) -> Any:
    if isinstance(value, dict):
        return {k: _drop_none(v) for k, v in value.items() if v is not None}
    if isinstance(value, list):
        return [_drop_none(item) for item in value]
    return value


@dataclass
class RequestedRefs:
    base: str
    head: str


@dataclass
class ResolvedRefs:
    base: str
    head: str
    merge_base: str


@dataclass
class DiffCounts:
    production_files_changed: int
    test_files_changed: int
    shared_test_infrastructure_changed: int
    files_added: int
    files_modified: int
    files_deleted: int
    files_renamed: int
    production_lines_deleted: int


@dataclass
class CoverageSummary:
    changed_executable_lines: int
    covered_by_pr_untouched_tests: int
    covered_only_by_pr_touched_tests: int
    covered_only_by_unknown_contexts: int
    uncovered: int
    pr_untouched_changed_line_coverage: float | None

    def assert_invariant(self) -> None:
        total = (
            self.covered_by_pr_untouched_tests
            + self.covered_only_by_pr_touched_tests
            + self.covered_only_by_unknown_contexts
            + self.uncovered
        )
        if total != self.changed_executable_lines:
            raise ValueError(
                "coverage partition invariant failed: "
                f"{total} != {self.changed_executable_lines}"
            )


@dataclass
class TestOutcomes:
    passed: int = 0
    failed: int = 0
    skipped: int = 0
    xfailed: int = 0
    xpassed: int = 0
    error: int = 0
    collected: int = 0


@dataclass
class TestChanges:
    __test__ = False
    files_changed: int = 0
    nodes_added: int = 0
    nodes_removed: int = 0
    nodes_modified: int = 0
    shared_infrastructure_changed: int = 0


@dataclass
class TestsSummary:
    __test__ = False
    outcomes: TestOutcomes = field(default_factory=TestOutcomes)
    changes: TestChanges = field(default_factory=TestChanges)
    pytest_exit_code: int | None = None


@dataclass
class LineEvidence:
    path: str
    line: int
    classification: LineClassification
    covering_node_ids: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)


@dataclass
class Finding:
    id: FindingCode
    severity: FindingSeverity
    path: str
    detail: str
    line: int | None = None
    test_node_id: str | None = None
    before: str | None = None
    after: str | None = None


@dataclass
class WarningRecord:
    code: str
    message: str
    path: str | None = None


@dataclass
class CoverageOverride:
    key: str
    value: str
    reason: str


@dataclass
class Report:
    schema_version: str
    tool_version: str
    status: Status
    requested_refs: RequestedRefs
    resolved_refs: ResolvedRefs | None
    diff: DiffCounts
    coverage: CoverageSummary
    tests: TestsSummary
    findings: list[Finding]
    line_evidence: list[LineEvidence]
    warnings: list[WarningRecord]
    caveats: list[str]
    coverage_overrides: list[CoverageOverride] = field(default_factory=list)
    pipeline: PipelineSummary | None = None
    requirements: RequirementsResult | None = None
    generated_tests: GeneratedTestsResult | None = None
    mutation: MutationResult | None = None
    behavioral_comparison: BehavioralResult | None = None
    policy: PolicyResult | None = None
    artifacts: dict[str, Any] | None = None

    def to_json_dict(self) -> dict[str, Any]:
        self.coverage.assert_invariant()
        payload = asdict(self)
        if self.schema_version == SCHEMA_VERSION_V2:
            if payload.get("pipeline") is None:
                payload["pipeline"] = default_pipeline().to_dict()
            if payload.get("requirements") is None:
                payload["requirements"] = empty_requirements().to_dict()
            if payload.get("generated_tests") is None:
                payload["generated_tests"] = empty_generated_tests().to_dict()
            if payload.get("mutation") is None:
                payload["mutation"] = empty_mutation().to_dict()
            if payload.get("behavioral_comparison") is None:
                payload["behavioral_comparison"] = empty_behavior().to_dict()
            if payload.get("policy") is None:
                payload["policy"] = empty_policy().to_dict()
            if payload.get("artifacts") is None:
                payload["artifacts"] = {"directory": ".verifypatch/artifacts", "items": []}
        else:
            for key in V2_REPORT_KEYS:
                payload.pop(key, None)
        return payload


def empty_coverage() -> CoverageSummary:
    return CoverageSummary(
        changed_executable_lines=0,
        covered_by_pr_untouched_tests=0,
        covered_only_by_pr_touched_tests=0,
        covered_only_by_unknown_contexts=0,
        uncovered=0,
        pr_untouched_changed_line_coverage=None,
    )


def default_caveats() -> list[str]:
    return [
        "No correctness score or automatic recommendation was produced.",
        "PR-untouched evidence means this pull request did not modify the covering test file or known related test infrastructure. It does not identify who originally authored those tests.",
        "VerifyPatch observes Git provenance. It does not prove which human or agent process wrote historical tests.",
    ]
