from __future__ import annotations

import hashlib

from verifypatch.mutation.backend import MutationSpec


def mutant_id(head_sha: str, spec: MutationSpec) -> str:
    material = "|".join(
        [
            head_sha,
            spec.path,
            f"{spec.start_pos[0]}:{spec.start_pos[1]}",
            f"{spec.end_pos[0]}:{spec.end_pos[1]}",
            spec.operator,
            spec.target_node,
            str(spec.occurrence),
        ]
    )
    digest = hashlib.sha256(material.encode("utf-8")).hexdigest()[:16]
    return f"mut-{digest}"


def filter_changed_lines(specs: list[MutationSpec], changed_lines: dict[str, set[int]]) -> list[MutationSpec]:
    kept: list[MutationSpec] = []
    for spec in specs:
        lines = changed_lines.get(spec.path) or set()
        if spec.start_pos[0] in lines:
            kept.append(spec)
    return kept


def dedupe(specs: list[MutationSpec], head_sha: str) -> list[MutationSpec]:
    seen: set[str] = set()
    unique: list[MutationSpec] = []
    for spec in specs:
        key = mutant_id(head_sha, spec)
        if key in seen:
            continue
        seen.add(key)
        unique.append(spec)
    return unique


def cap_specs(specs: list[MutationSpec], head_sha: str, limit: int) -> list[MutationSpec]:
    if len(specs) <= limit:
        return specs
    ranked = sorted(specs, key=lambda spec: hashlib.sha256(mutant_id(head_sha, spec).encode("utf-8")).hexdigest())
    return ranked[:limit]
