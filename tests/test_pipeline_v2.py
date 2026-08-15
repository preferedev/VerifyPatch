from __future__ import annotations

from pathlib import Path

from verifypatch.cli import main
from verifypatch.engine import run_check
from verifypatch.report import validate_report
from tests.helpers import materialize_fixture, normalize_report


def test_verify_without_stages_preserves_v1_coverage_partitions(tmp_path: Path):
    repo, base, head = materialize_fixture("discount", tmp_path / "repo")
    v1 = run_check(repo, base, head, pytest_args=[])
    v1_payload = normalize_report(v1.to_json_dict())
    json_out = tmp_path / "v2.json"
    md_out = tmp_path / "v2.md"
    code = main(
        [
            "verify",
            "--base",
            base,
            "--head",
            head,
            "--root",
            str(repo),
            "--json-out",
            str(json_out),
            "--md-out",
            str(md_out),
        ]
    )
    assert code == 0
    v2 = json_out.read_text(encoding="utf-8")
    import json

    payload = json.loads(v2)
    validate_report(payload)
    assert payload["coverage"] == v1.to_json_dict()["coverage"]
    assert payload["findings"] == v1.to_json_dict()["findings"]
    assert payload["schema_version"] == "2"
    assert v1_payload["coverage"]["changed_executable_lines"] == payload["coverage"]["changed_executable_lines"]
    stages = {item["name"]: item["status"] for item in payload["pipeline"]["stages"]}
    assert stages["requirements"] == "not_requested"
    assert stages["generation"] == "not_requested"
    assert stages["mutation"] == "not_requested"
    assert stages["behavior"] == "not_requested"
