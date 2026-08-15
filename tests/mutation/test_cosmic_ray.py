from __future__ import annotations

from importlib.metadata import version
from pathlib import Path

import pytest

from verifypatch.mutation.cosmic_ray_backend import CosmicRayBackend, load_backend
from verifypatch.mutation.semantic import mutation_is_semantic
from verifypatch.stage import Reason


def test_missing_cosmic_ray_is_reported_without_silent_fallback(monkeypatch):
    import builtins

    real_import = builtins.__import__

    def fake_import(name, *args, **kwargs):
        if name == "cosmic_ray" or name.startswith("cosmic_ray."):
            raise ImportError("forced missing cosmic-ray")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", fake_import)
    loaded = load_backend("cosmic-ray", ["comparison"])
    assert isinstance(loaded, Reason)
    assert loaded.code == "missing_dependency"


def test_explicit_fallback_to_ast_when_cosmic_ray_missing(monkeypatch):
    import builtins

    from verifypatch.mutation.ast_backend import AstMutationBackend

    real_import = builtins.__import__

    def fake_import(name, *args, **kwargs):
        if name == "cosmic_ray" or name.startswith("cosmic_ray."):
            raise ImportError("forced missing cosmic-ray")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", fake_import)
    loaded = load_backend("cosmic-ray", ["comparison"], fallback="ast")
    assert isinstance(loaded, AstMutationBackend)
    assert loaded.name == "ast"


def test_explicit_fallback_to_ast_is_recorded():
    loaded = load_backend("cosmic-ray", ["comparison"], fallback="ast")
    assert loaded is not None
    assert getattr(loaded, "name", None) in {"cosmic-ray", "ast"}


def test_cosmic_ray_enumerates_and_applies_intended_ast_change(tmp_path: Path):
    pytest.importorskip("cosmic_ray")
    from importlib.metadata import version

    source = "def f(x):\n    return x == 1\n"
    (tmp_path / "mod.py").write_text(source, encoding="utf-8")
    backend = CosmicRayBackend(["comparison"])
    assert backend.name == "cosmic-ray"
    assert backend.version == version("cosmic-ray")
    specs = backend.list_mutations(tmp_path, ["mod.py"])
    eq_specs = [item for item in specs if "Eq_NotEq" in item.operator]
    assert eq_specs, specs
    spec = eq_specs[0]
    backend.apply(tmp_path, spec)
    mutated = (tmp_path / "mod.py").read_text(encoding="utf-8")
    assert "==" not in mutated
    assert "!=" in mutated
    ok, _reason = mutation_is_semantic(source, mutated)
    assert ok
