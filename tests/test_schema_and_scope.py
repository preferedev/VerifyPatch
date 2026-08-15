from __future__ import annotations

from pathlib import Path

from verifypatch.schema import load_schema


def test_schema_copies_are_identical():
    root = Path(__file__).resolve().parents[1]
    for name in (
        "verifypatch-report-v1.schema.json",
        "verifypatch-report-v2.schema.json",
        "verifypatch-requirements-v1.schema.json",
    ):
        repo = root / "schemas" / name
        packaged = root / "src" / "verifypatch" / name
        assert repo.read_text(encoding="utf-8") == packaged.read_text(encoding="utf-8")
    schema = load_schema()
    assert schema["$schema"] == "https://json-schema.org/draft/2020-12/schema"


def test_no_out_of_scope_features():
    root = Path(__file__).resolve().parents[1] / "src" / "verifypatch"
    blob = "\n".join(path.read_text(encoding="utf-8") for path in root.rglob("*.py"))
    for needle in (
        "trust_score",
        "pull_request_target",
        "checks:write",
        "import mutmut",
        "from mutmut",
    ):
        assert needle not in blob
