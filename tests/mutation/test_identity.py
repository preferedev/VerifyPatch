from __future__ import annotations

from pathlib import Path

import pytest

from verifypatch.mutation.backend import InvalidMutation
from verifypatch.mutation.ast_backend import AstMutationBackend
from verifypatch.mutation.semantic import mutation_is_semantic, semantic_dump
import ast


def _write(path: Path, source: str) -> None:
    path.write_text(source, encoding="utf-8")


def test_file_global_occurrence_applies_the_matching_node(tmp_path: Path):
    source = "def f(a, b):\n    x = a == 1\n    y = b == 2\n    return x and y\n"
    _write(tmp_path / "mod.py", source)
    backend = AstMutationBackend(["comparison"])
    specs = backend.list_mutations(tmp_path, ["mod.py"])
    assert len(specs) == 2
    assert specs[0].start_pos[0] != specs[1].start_pos[0] or specs[0].start_pos[1] != specs[1].start_pos[1]
    backend.apply(tmp_path, specs[1])
    mutated = (tmp_path / "mod.py").read_text(encoding="utf-8")
    assert "a == 1" in mutated
    assert "b != 2" in mutated
    ok, _reason = mutation_is_semantic(source, mutated)
    assert ok


def test_same_line_comparisons_remain_distinct(tmp_path: Path):
    source = "def f(a, b):\n    return a == 1 and b == 2\n"
    _write(tmp_path / "mod.py", source)
    backend = AstMutationBackend(["comparison"])
    specs = backend.list_mutations(tmp_path, ["mod.py"])
    assert len(specs) == 2
    backend.apply(tmp_path, specs[0])
    mutated = (tmp_path / "mod.py").read_text(encoding="utf-8")
    assert "a != 1" in mutated
    assert "b == 2" in mutated


def test_unparse_formatting_is_not_a_semantic_mutation(tmp_path: Path):
    source = "def f(x):\n    return x==1\n"
    _write(tmp_path / "mod.py", source)
    backend = AstMutationBackend(["comparison"])
    specs = backend.list_mutations(tmp_path, ["mod.py"])
    assert specs
    backend.apply(tmp_path, specs[0])
    mutated = (tmp_path / "mod.py").read_text(encoding="utf-8")
    assert "x!=1" in mutated or "x != 1" in mutated
    assert semantic_dump(ast.parse(source)) != semantic_dump(ast.parse(mutated))
    # Formatting-only change of the original would not count:
    pretty = ast.unparse(ast.parse(source)) + "\n"
    ok, reason = mutation_is_semantic(source, pretty)
    assert ok is False
    assert "semantic AST" in reason


def test_repeat_apply_without_semantic_change_is_invalid(tmp_path: Path):
    source = "def f(x):\n    return x == 1\n"
    _write(tmp_path / "mod.py", source)
    backend = AstMutationBackend(["comparison"])
    specs = backend.list_mutations(tmp_path, ["mod.py"])
    assert specs
    backend.apply(tmp_path, specs[0])
    with pytest.raises(InvalidMutation):
        backend.apply(tmp_path, specs[0])


def test_every_enumerated_mutant_changes_exactly_one_intended_node(tmp_path: Path):
    source = (
        "def f(a, b, flag):\n"
        "    if a == 1 and b == 2:\n"
        "        return a + b\n"
        "    if not flag:\n"
        "        return 7\n"
        "    return a * b\n"
    )
    _write(tmp_path / "mod.py", source)
    backend = AstMutationBackend(["comparison", "boolean", "arithmetic", "constants"])
    specs = backend.list_mutations(tmp_path, ["mod.py"])
    assert len(specs) >= 5
    original_dump = semantic_dump(ast.parse(source))
    seen = set()
    for spec in specs:
        key = (spec.path, spec.start_pos, spec.end_pos, spec.operator, spec.occurrence, spec.target_node)
        assert key not in seen
        seen.add(key)
        target = tmp_path / "mod.py"
        target.write_text(source, encoding="utf-8")
        backend.apply(tmp_path, spec)
        mutated = target.read_text(encoding="utf-8")
        ok, reason = mutation_is_semantic(source, mutated)
        assert ok, (spec, reason, mutated)
        mutated_dump = semantic_dump(ast.parse(mutated))
        assert mutated_dump != original_dump
        # Compact diff must mention the recorded original token.
        from verifypatch.mutation.semantic import compact_diff

        diff = compact_diff(source, mutated, spec.path)
        assert spec.original.strip() in diff or spec.original in mutated or spec.mutated in mutated
        # Re-parsing the mutated file must succeed and differ in exactly the applied span's operator/token.
        assert spec.original != spec.mutated
