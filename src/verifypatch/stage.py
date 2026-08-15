from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Literal

StageStatus = Literal["not_requested", "skipped", "complete", "incomplete", "error"]
STAGE_NAMES = (
    "preflight",
    "git",
    "provenance",
    "requirements",
    "generation",
    "mutation",
    "behavior",
    "policy",
)


@dataclass
class Reason:
    code: str
    message: str


@dataclass
class ArtifactRef:
    path: str
    sha256: str
    kind: str
    bytes: int


@dataclass
class StageResult:
    name: str
    status: StageStatus
    started_at: str | None = None
    ended_at: str | None = None
    duration_ms: int | None = None
    configured_deadline_seconds: int | None = None
    effective_deadline_seconds: int | None = None
    warnings: list[dict[str, Any]] = field(default_factory=list)
    skip_reason: Reason | None = None
    error_reason: Reason | None = None
    artifacts: list[ArtifactRef] = field(default_factory=list)
    tool_versions: dict[str, str] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def empty_stage(name: str, status: StageStatus = "not_requested") -> StageResult:
    return StageResult(name=name, status=status)


@dataclass
class PipelineSummary:
    stages: list[StageResult] = field(default_factory=list)
    optional_deadline_seconds: int = 900
    optional_deadline_exhausted: bool = False

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def default_pipeline() -> PipelineSummary:
    return PipelineSummary(stages=[empty_stage(name) for name in STAGE_NAMES])
