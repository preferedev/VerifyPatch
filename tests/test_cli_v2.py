from __future__ import annotations

import json
from pathlib import Path

from verifypatch.cli import main
from tests.helpers import materialize_fixture


def test_schema_command_prints_v1():
    import io
    from contextlib import redirect_stdout

    buf = io.StringIO()
    with redirect_stdout(buf):
        code = main(["schema", "report-v1"])
    assert code == 0
    payload = json.loads(buf.getvalue())
    assert payload["$id"].endswith("verifypatch-report-v1.schema.json")


def test_schema_command_prints_v2_and_requirements():
    import io
    from contextlib import redirect_stdout

    buf = io.StringIO()
    with redirect_stdout(buf):
        assert main(["schema", "report-v2"]) == 0
    assert '"const": "2"' in buf.getvalue() or '"const":"2"' in buf.getvalue()
    buf = io.StringIO()
    with redirect_stdout(buf):
        assert main(["schema", "requirements-v1"]) == 0
    assert "requirement" in buf.getvalue()


def test_verify_emits_schema_v2(tmp_path: Path):
    repo, base, head = materialize_fixture("clean_refactor", tmp_path / "repo")
    json_out = tmp_path / "out.json"
    md_out = tmp_path / "out.md"
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
            "--no-requirements",
            "--no-generate",
            "--no-mutation",
            "--no-behavior",
        ]
    )
    assert code == 0
    payload = json.loads(json_out.read_text(encoding="utf-8"))
    assert payload["schema_version"] == "2"
    assert "pipeline" in payload
    assert payload["policy"]["mode"] == "informational"
    assert "PIPELINE" in md_out.read_text(encoding="utf-8")


def test_check_remains_schema_v1(tmp_path: Path):
    repo, base, head = materialize_fixture("clean_refactor", tmp_path / "repo")
    json_out = tmp_path / "v1.json"
    md_out = tmp_path / "v1.md"
    code = main(
        [
            "check",
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
    payload = json.loads(json_out.read_text(encoding="utf-8"))
    assert payload["schema_version"] == "1"
    assert "pipeline" not in payload


def test_requirements_only_does_not_run_pytest(tmp_path: Path, monkeypatch):
    repo, base, head = materialize_fixture("clean_refactor", tmp_path / "repo")
    ran = {"pytest": False}

    def boom(*_args, **_kwargs):
        ran["pytest"] = True
        raise AssertionError("pytest must not run during requirements-only")

    monkeypatch.setattr("verifypatch.engine.run_pytest_coverage", boom)
    json_out = tmp_path / "req.json"
    md_out = tmp_path / "req.md"
    code = main(
        [
            "verify",
            "--base",
            base,
            "--head",
            head,
            "--root",
            str(repo),
            "--requirements-only",
            "--json-out",
            str(json_out),
            "--md-out",
            str(md_out),
        ]
    )
    assert code == 0
    assert ran["pytest"] is False
    payload = json.loads(json_out.read_text(encoding="utf-8"))
    assert payload["schema_version"] == "2"
    stages = {item["name"]: item["status"] for item in payload["pipeline"]["stages"]}
    assert stages["provenance"] == "not_requested"


def test_enforce_block_exit_3(tmp_path: Path):
    repo, base, head = materialize_fixture("discount", tmp_path / "repo")
    cfg = tmp_path / "verifypatch.yml"
    cfg.write_text(
        "version: 2\npolicy:\n  block_on_findings:\n    - TEST_SKIP_ADDED\n",
        encoding="utf-8",
    )
    json_out = tmp_path / "e.json"
    md_out = tmp_path / "e.md"
    code = main(
        [
            "verify",
            "--base",
            base,
            "--head",
            head,
            "--root",
            str(repo),
            "--config",
            str(cfg),
            "--json-out",
            str(json_out),
            "--md-out",
            str(md_out),
            "--enforce",
        ]
    )
    payload = json.loads(json_out.read_text(encoding="utf-8"))
    if payload.get("policy", {}).get("decision") != "block":
        raise AssertionError(f"expected blocking policy, got {payload.get('policy')}")
    assert code == 3


def test_requirements_only_does_not_import_subject_python(tmp_path: Path):
    repo, base, head = materialize_fixture("clean_refactor", tmp_path / "repo")
    marker = tmp_path / "imported.flag"
    boom = repo / "boom_on_import.py"
    boom.write_text(
        f"from pathlib import Path\nPath({str(marker)!r}).write_text('imported', encoding='utf-8')\n",
        encoding="utf-8",
    )
    json_out = tmp_path / "req.json"
    md_out = tmp_path / "req.md"
    import sys

    sys.path.insert(0, str(repo))
    try:
        code = main(
            [
                "verify",
                "--base",
                base,
                "--head",
                head,
                "--root",
                str(repo),
                "--requirements-only",
                "--json-out",
                str(json_out),
                "--md-out",
                str(md_out),
            ]
        )
    finally:
        while str(repo) in sys.path:
            sys.path.remove(str(repo))
        sys.modules.pop("boom_on_import", None)
    assert code == 0
    assert not marker.exists()
    assert "boom_on_import" not in sys.modules


def test_requirements_only_from_neutral_directory_ignores_subject_shadow(tmp_path: Path):
    import os
    import subprocess
    import sys

    repo, base, head = materialize_fixture("clean_refactor", tmp_path / "subject")
    (repo / "verifypatch.py").write_text(
        "raise SystemExit('subject module shadowed verifypatch')\n",
        encoding="utf-8",
    )
    neutral = tmp_path / "pp-req"
    neutral.mkdir()
    json_out = neutral / "requirements.json"
    md_out = neutral / "requirements.md"
    env = os.environ.copy()
    env["PYTHONPATH"] = str(Path(__file__).resolve().parents[1] / "src")
    env["PYTHONNOUSERSITE"] = "1"
    completed = subprocess.run(
        [
            sys.executable,
            "-m",
            "verifypatch",
            "verify",
            "--root",
            str(repo),
            "--base",
            base,
            "--head",
            head,
            "--requirements-only",
            "--json-out",
            str(json_out),
            "--md-out",
            str(md_out),
        ],
        cwd=neutral,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    assert completed.returncode == 0, completed.stderr
    payload = json.loads(json_out.read_text(encoding="utf-8"))
    assert payload["schema_version"] == "2"
    assert payload["status"] in {"complete", "incomplete", "error"} or "pipeline" in payload


def test_block_without_enforce_exits_0(tmp_path: Path):
    repo, base, head = materialize_fixture("discount", tmp_path / "repo")
    cfg = tmp_path / "verifypatch.yml"
    cfg.write_text(
        "version: 2\npolicy:\n  block_on_findings:\n    - TEST_SKIP_ADDED\n",
        encoding="utf-8",
    )
    json_out = tmp_path / "e.json"
    md_out = tmp_path / "e.md"
    code = main(
        [
            "verify",
            "--base",
            base,
            "--head",
            head,
            "--root",
            str(repo),
            "--config",
            str(cfg),
            "--json-out",
            str(json_out),
            "--md-out",
            str(md_out),
        ]
    )
    payload = json.loads(json_out.read_text(encoding="utf-8"))
    assert payload["policy"]["decision"] == "block"
    assert payload["policy"]["would_decide"] == "block"
    assert payload["policy"]["mode"] == "informational"
    assert payload["policy"]["enforced"] is False
    assert code == 0


def test_policy_command_matches_verify_enforcement(tmp_path: Path):
    repo, base, head = materialize_fixture("discount", tmp_path / "repo")
    cfg = tmp_path / "verifypatch.yml"
    cfg.write_text(
        "version: 2\npolicy:\n  block_on_findings:\n    - TEST_SKIP_ADDED\n",
        encoding="utf-8",
    )
    json_out = tmp_path / "e.json"
    md_out = tmp_path / "e.md"
    verify_code = main(
        [
            "verify",
            "--base",
            base,
            "--head",
            head,
            "--root",
            str(repo),
            "--config",
            str(cfg),
            "--json-out",
            str(json_out),
            "--md-out",
            str(md_out),
        ]
    )
    assert verify_code == 0
    policy_info = main(
        [
            "policy",
            "--report",
            str(json_out),
            "--config",
            str(cfg),
            "--root",
            str(repo),
            "--json-out",
            str(tmp_path / "p0.json"),
            "--md-out",
            str(tmp_path / "p0.md"),
        ]
    )
    assert policy_info == 0
    policy_enforced = main(
        [
            "policy",
            "--report",
            str(json_out),
            "--config",
            str(cfg),
            "--root",
            str(repo),
            "--enforce",
            "--json-out",
            str(tmp_path / "p3.json"),
            "--md-out",
            str(tmp_path / "p3.md"),
        ]
    )
    payload = json.loads((tmp_path / "p3.json").read_text(encoding="utf-8"))
    assert payload["policy"]["decision"] == "block"
    assert payload["policy"]["enforced"] is True
    assert payload["policy"]["mode"] == "enforcing"
    assert policy_enforced == 3


def test_config_mode_enforcing_exits_2(tmp_path: Path):
    repo, base, head = materialize_fixture("clean_refactor", tmp_path / "repo")
    cfg = tmp_path / "verifypatch.yml"
    cfg.write_text("version: 2\npolicy:\n  mode: enforcing\n", encoding="utf-8")
    code = main(
        [
            "verify",
            "--base",
            base,
            "--head",
            head,
            "--root",
            str(repo),
            "--config",
            str(cfg),
            "--json-out",
            str(tmp_path / "x.json"),
            "--md-out",
            str(tmp_path / "x.md"),
        ]
    )
    assert code == 2
