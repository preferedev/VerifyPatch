from __future__ import annotations

from pathlib import Path

from verifypatch.generation.compiler import compile_requirement
from verifypatch.requirements import Requirement, SourceCitation


def _req(kind: str, statement: str = "x must hold", **kwargs) -> Requirement:
    return Requirement(
        id="REQ-001",
        statement=statement,
        kind=kind,
        confidence="high",
        executable=True,
        citations=[SourceCitation(ref="s", path="README.md", start_line=1, end_line=1, digest="abc")],
        target_module="pricing",
        target_callable="final_price",
        parameters=kwargs.get("parameters", {"min": 0, "max": 10}),
    )


def test_compiler_does_not_embed_provider_python():
    evil = "import os; os.system('echo pwned')"
    source = compile_requirement(_req("bounds", statement=evil), max_examples=10, deadline_ms=200, seed=0)
    assert "os.system" not in source
    assert "echo pwned" not in source
    assert "importlib" in source
    compile_mod = compile(source, "<generated>", "exec")
    assert compile_mod is not None


def test_each_supported_kind_compiles():
    for kind, params in {
        "bounds": {"min": 0, "max": 5},
        "charset": {"alphabet": "abc"},
        "round_trip": {},
        "idempotent": {},
        "monotonic": {},
        "non_negative": {},
        "schema_valid": {},
        "rejects_invalid": {"invalid": [None]},
        "examples": {"examples": [{"args": [1], "expected": 1}]},
    }.items():
        source = compile_requirement(_req(kind, parameters=params), max_examples=5, deadline_ms=100, seed=0)
        assert f"test_REQ_001_{kind}" in source
        compile(source, "<generated>", "exec")


def test_invalid_target_rejected():
    req = _req("bounds")
    req.target_module = "pricing; import os"
    try:
        compile_requirement(req, max_examples=1, deadline_ms=100, seed=0)
    except ValueError:
        return
    raise AssertionError("expected invalid target to be rejected")
