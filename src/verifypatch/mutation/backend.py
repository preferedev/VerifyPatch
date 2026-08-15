from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from verifypatch.mutation.semantic import InvalidMutation

__all__ = ["InvalidMutation", "MutationBackend", "MutationSpec"]


@dataclass
class MutationSpec:
    path: str
    start_pos: tuple[int, int]
    end_pos: tuple[int, int]
    operator: str
    occurrence: int
    original: str
    mutated: str
    target_node: str = ""

    @property
    def stable_key(self) -> str:
        return (
            f"{self.path}:{self.start_pos[0]}:{self.start_pos[1]}:"
            f"{self.end_pos[0]}:{self.end_pos[1]}:{self.operator}:"
            f"{self.target_node}:{self.occurrence}"
        )


class MutationBackend(Protocol):
    name: str
    version: str

    def list_mutations(self, root: Path, files: list[str]) -> list[MutationSpec]:
        ...

    def apply(self, root: Path, spec: MutationSpec) -> None:
        ...
