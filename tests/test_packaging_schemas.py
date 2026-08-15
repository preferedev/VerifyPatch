from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path

from verifypatch.requirements.prompts import load_prompt
from verifypatch.schema import load_schema, load_schema_text

ROOT = Path(__file__).resolve().parents[1]


def test_bundled_schemas_load():
    for name in ("1", "2", "requirements-v1"):
        schema = load_schema(name)
        assert schema["$schema"] == "https://json-schema.org/draft/2020-12/schema"
        assert load_schema_text(name)


def test_wheel_would_include_schemas_and_prompt():
    packaged = ROOT / "src" / "verifypatch"
    for name in (
        "verifypatch-report-v1.schema.json",
        "verifypatch-report-v2.schema.json",
        "verifypatch-requirements-v1.schema.json",
    ):
        assert (packaged / name).is_file()
    assert (packaged / "requirements" / "prompts" / "extract_v1.txt").is_file()
    assert "requirement" in load_prompt().lower() or len(load_prompt()) > 50


def test_schemas_and_prompt_load_from_empty_cwd(tmp_path: Path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    assert load_schema("1")["$schema"]
    assert load_schema("2")["$schema"]
    assert load_schema("requirements-v1")["$schema"]
    assert load_prompt()


def test_installed_package_loads_schemas_outside_source(tmp_path: Path):
    target = tmp_path / "site"
    shutil.copytree(ROOT / "src" / "verifypatch", target / "verifypatch")
    empty = tmp_path / "empty"
    empty.mkdir()
    env = os.environ.copy()
    env["PYTHONPATH"] = str(target)
    env["PYTHONNOUSERSITE"] = "1"
    for name in ("report-v1", "report-v2", "requirements-v1"):
        completed = subprocess.run(
            [sys.executable, "-m", "verifypatch", "schema", name],
            cwd=empty,
            env=env,
            capture_output=True,
            text=True,
            check=False,
        )
        assert completed.returncode == 0, completed.stderr
        assert "$schema" in completed.stdout
    prompt = subprocess.run(
        [
            sys.executable,
            "-c",
            "from verifypatch.requirements.prompts import load_prompt; print(load_prompt()[:24])",
        ],
        cwd=empty,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    assert prompt.returncode == 0, prompt.stderr
    assert prompt.stdout.strip()
