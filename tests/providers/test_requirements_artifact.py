from __future__ import annotations

import json
from pathlib import Path

from verifypatch.config import V2Config
from verifypatch.requirements.artifact import load_requirements_artifact
from verifypatch.stage import Reason


def test_invalid_requirements_json_is_rejected(tmp_path: Path):
    path = tmp_path / "req.json"
    path.write_text("{not json", encoding="utf-8")
    result, error = load_requirements_artifact(path)
    assert result is None
    assert isinstance(error, Reason)
    assert error.code == "invalid_requirements_artifact"


def test_requirements_schema_mismatch_is_rejected(tmp_path: Path):
    path = tmp_path / "req.json"
    path.write_text(json.dumps({"schema_version": "1", "prompt_version": "x", "items": [{"id": "x"}]}), encoding="utf-8")
    result, error = load_requirements_artifact(path)
    assert result is None
    assert error and error.code == "invalid_requirements_artifact"


def test_v2_report_requirements_block_is_accepted(tmp_path: Path):
    path = tmp_path / "req.json"
    payload = {
        "schema_version": "2",
        "requirements": {
            "requirement_schema_version": "1",
            "prompt_version": "requirements-extract-v1",
            "items": [],
        },
    }
    path.write_text(json.dumps(payload), encoding="utf-8")
    result, error = load_requirements_artifact(path)
    assert error is None
    assert result is not None
    assert result.items == []
