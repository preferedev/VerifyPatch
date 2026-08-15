from __future__ import annotations

from pathlib import Path

from verifypatch.behavior.compare import _input_id
from verifypatch.behavior.protocol import is_json_value


def test_difference_without_requirement_is_unknown_by_contract():
    source = (
        Path(__file__).resolve().parents[2]
        / "src"
        / "verifypatch"
        / "behavior"
        / "compare.py"
    ).read_text(encoding="utf-8")
    assert 'classification = "unknown"' in source
    assert "without a linked requirement" in source
    assert 'classification = "expected"' in source
    assert 'classification = "potential_regression"' in source
    assert 'classification = "nondeterministic"' in source


def test_input_ids_are_stable():
    assert _input_id({"args": [1], "kwargs": {}}) == _input_id({"args": [1], "kwargs": {}})
    assert is_json_value([1, {"a": None}])
