from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Literal

BehaviorClass = Literal[
    "expected",
    "potential_regression",
    "unknown",
    "unchanged",
    "nondeterministic",
]


@dataclass
class BehaviorComparison:
    target: str
    input_id: str
    input_digest: str
    base_preview: str
    head_preview: str
    classification: BehaviorClass
    requirement_ids: list[str] = field(default_factory=list)
    duration_ms: int | None = None
    warnings: list[str] = field(default_factory=list)


@dataclass
class BehavioralResult:
    items: list[BehaviorComparison] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def empty_behavior() -> BehavioralResult:
    return BehavioralResult()
