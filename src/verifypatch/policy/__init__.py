from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Literal

PolicyDecisionKind = Literal["pass", "review", "block", "not_evaluated"]
POLICY_PRECEDENCE = ("block", "review", "not_evaluated", "pass")


@dataclass
class PolicyReason:
    code: str
    message: str


@dataclass
class PolicyResult:
    mode: str = "informational"
    decision: PolicyDecisionKind = "not_evaluated"
    would_decide: PolicyDecisionKind = "not_evaluated"
    reasons: list[PolicyReason] = field(default_factory=list)
    enforced: bool = False

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def empty_policy() -> PolicyResult:
    return PolicyResult()
