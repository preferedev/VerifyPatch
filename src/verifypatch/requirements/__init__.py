from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Literal

Confidence = Literal["high", "medium", "low"]
EXECUTABLE_KINDS = (
    "bounds",
    "charset",
    "round_trip",
    "idempotent",
    "monotonic",
    "non_negative",
    "schema_valid",
    "rejects_invalid",
    "examples",
)
PROMPT_VERSION = "requirements-extract-v1"
REQUIREMENT_SCHEMA_VERSION = "1"


@dataclass
class SourceCitation:
    ref: str
    path: str
    start_line: int
    end_line: int
    digest: str


@dataclass
class Requirement:
    id: str
    statement: str
    kind: str
    confidence: Confidence
    executable: bool
    citations: list[SourceCitation] = field(default_factory=list)
    target_module: str | None = None
    target_callable: str | None = None
    parameters: dict[str, Any] = field(default_factory=dict)
    assumptions: list[str] = field(default_factory=list)
    refusal_reason: str | None = None
    non_executable_reason: str | None = None


@dataclass
class RequirementsResult:
    provider: str | None = None
    model: str | None = None
    prompt_version: str | None = None
    requirement_schema_version: str | None = None
    request_id: str | None = None
    constrained_output: bool | None = None
    items: list[Requirement] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def empty_requirements() -> RequirementsResult:
    return RequirementsResult()
