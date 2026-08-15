from __future__ import annotations

import json
from pathlib import Path

_SCHEMAS = {
    "1": "verifypatch-report-v1.schema.json",
    "2": "verifypatch-report-v2.schema.json",
    "requirements-v1": "verifypatch-requirements-v1.schema.json",
}


def _candidates(filename: str) -> list[Path]:
    packaged = Path(__file__).with_name(filename)
    repo = Path(__file__).resolve().parents[2] / "schemas" / filename
    return [packaged, repo]


def load_schema(version: str = "1") -> dict:
    filename = _SCHEMAS.get(str(version))
    if filename is None:
        raise FileNotFoundError(f"unknown schema {version!r}")
    for path in _candidates(filename):
        if path.is_file():
            return json.loads(path.read_text(encoding="utf-8"))
    raise FileNotFoundError(f"{filename} was not found")


def load_schema_text(version: str = "1") -> str:
    filename = _SCHEMAS.get(str(version))
    if filename is None:
        raise FileNotFoundError(f"unknown schema {version!r}")
    for path in _candidates(filename):
        if path.is_file():
            return path.read_text(encoding="utf-8")
    raise FileNotFoundError(f"{filename} was not found")


def bundled_schema_names() -> dict[str, str]:
    return dict(_SCHEMAS)
