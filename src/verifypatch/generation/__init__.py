from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Literal

GeneratedOutcome = Literal["passed", "failed", "invalid", "flaky", "timeout", "error"]


@dataclass
class GeneratedTestResult:
    id: str
    requirement_id: str
    source_artifact: str | None
    outcome: GeneratedOutcome
    nodeid: str | None = None
    duration_ms: int | None = None
    counterexample: dict[str, Any] | None = None
    seed: int = 0
    detail: str | None = None
    source_digest: str | None = None


@dataclass
class GeneratedTestsResult:
    seed: int = 0
    items: list[GeneratedTestResult] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def empty_generated_tests() -> GeneratedTestsResult:
    return GeneratedTestsResult()
