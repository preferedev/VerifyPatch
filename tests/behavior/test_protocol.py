from __future__ import annotations

from verifypatch.behavior.protocol import is_json_value, normalize_exception, preview


def test_json_compatible_values():
    assert is_json_value({"a": [1, 2.5, None, True, "x"]})
    assert not is_json_value(object())
    assert not is_json_value({1: "x"})


def test_exception_normalization():
    payload = normalize_exception(ValueError("boom" * 200))
    assert payload["type"] == "ValueError"
    assert len(payload["message"]) <= 500


def test_preview_is_bounded():
    text = preview("x" * 5000)
    assert len(text) <= 500
