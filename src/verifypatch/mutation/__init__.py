from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Literal

MutationResultKind = Literal[
    "killed",
    "survived",
    "timeout",
    "invalid",
    "error",
    "not_run",
    "excluded",
]
KillOrigin = Literal["pr_untouched", "pr_touched", "generated"]


@dataclass
class MutantRecord:
    id: str
    path: str
    start_pos: list[int]
    end_pos: list[int]
    operator: str
    diff: str
    selection_reason: str
    result: MutationResultKind
    killing_origin: KillOrigin | None = None
    executed_ids: list[str] = field(default_factory=list)
    duration_ms: int | None = None
    output_artifact: str | None = None
    target_node: str | None = None


@dataclass
class MutationSummary:
    candidate: int = 0
    selected: int = 0
    killed_by_pr_untouched: int = 0
    killed_by_pr_touched: int = 0
    killed_by_generated: int = 0
    survived: int = 0
    timeout: int = 0
    invalid: int = 0
    error: int = 0
    not_run: int = 0
    excluded: int = 0
    independent_mutation_score: float | None = None
    overall_mutation_score: float | None = None


@dataclass
class MutationResult:
    backend: str | None = None
    backend_version: str | None = None
    summary: MutationSummary = field(default_factory=MutationSummary)
    mutants: list[MutantRecord] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def empty_mutation() -> MutationResult:
    return MutationResult()


def score(killed: int, valid_executed: int) -> float | None:
    if valid_executed <= 0:
        return None
    return killed / valid_executed
