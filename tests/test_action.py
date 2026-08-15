from __future__ import annotations

import re
from pathlib import Path

import pytest

ACTION = Path(__file__).resolve().parents[1] / "action.yml"
WORKFLOW = Path(__file__).resolve().parents[1] / "examples" / "github-pull-request.yml"
WORKFLOW_CI = Path(__file__).resolve().parents[1] / ".github" / "workflows" / "verifypatch.yml"
WORKFLOW_V2 = Path(__file__).resolve().parents[1] / "examples" / "github-v2-two-job.yml"
WORKFLOW_TEST = Path(__file__).resolve().parents[1] / ".github" / "workflows" / "ci.yml"

_SHA_REF = re.compile(r"^[0-9a-f]{40}$")
_USES = re.compile(r"^\s+uses:\s+(\S+)\s*(?:#.*)?$")


def _load(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def _third_party_uses(text: str) -> list[tuple[str, str]]:
    found: list[tuple[str, str]] = []
    for line in text.splitlines():
        match = _USES.match(line)
        if not match:
            continue
        spec = match.group(1)
        if spec.startswith("./") or spec.startswith(".\\"):
            continue
        if "@" not in spec:
            raise AssertionError(f"unpinned action: {spec}")
        name, ref = spec.rsplit("@", 1)
        found.append((name, ref))
    return found


def test_action_is_composite_and_writes_summary():
    text = _load(ACTION)
    assert "using: composite" in text
    assert "python -m pip install" in text
    assert "${{ github.action_path }}" in text
    assert "GITHUB_STEP_SUMMARY" in text
    assert "GITHUB_OUTPUT" in text
    assert "python -m verifypatch" in text
    assert "checks:write" not in text


def test_workflows_use_pull_request_not_target():
    on_target = re.compile(r"(?m)^on:\s*\n(?:  .*\n)*?[ \t]*pull_request_target\b")
    for path in (WORKFLOW, WORKFLOW_CI, WORKFLOW_V2, WORKFLOW_TEST):
        text = _load(path)
        assert on_target.search(text) is None
        assert re.search(r"(?m)^on:\s*$", text) or "pull_request:" in text
        assert "contents: read" in text
        assert "timeout-minutes: 30" in text
        assert "runs-on: ubuntu-latest" in text
        assert "checks: write" not in text.lower()


def test_third_party_actions_are_pinned_to_commit_shas():
    for path in (WORKFLOW, WORKFLOW_CI, WORKFLOW_V2, WORKFLOW_TEST):
        for name, ref in _third_party_uses(_load(path)):
            assert _SHA_REF.match(ref), f"{path} pins {name} to {ref!r}, not a 40-char SHA"


def test_example_workflow_security_contract():
    for path in (WORKFLOW, WORKFLOW_CI, WORKFLOW_V2):
        text = _load(path)
        assert "github.event.pull_request.head.sha" in text
        assert "github.event.pull_request.base.sha" in text
        assert "fetch-depth: 0" in text
        assert "upload-artifact" in text
    two_job = _load(WORKFLOW_V2)
    assert "timeout-minutes: 30" in two_job
    assert "OPENAI_API_KEY" in two_job
    assert "verifypatch-verify" in two_job
    assert "pull_request_target" not in two_job
    req_job, verify_job = two_job.split("verifypatch-verify:")
    assert "OPENAI_API_KEY" in req_job
    assert "OPENAI_API_KEY" not in verify_job
    assert "secrets." not in verify_job
    assert 'pip install ".[' not in req_job
    assert "pip install -e" not in req_job
    assert "pip install ." not in req_job
    assert "python -m pip install" in req_job and "verifypatch[openai]==" in req_job
    assert 'VERIFYPATCH_VERSION: "0.2.0"' in two_job
    assert "verifypatch==${VERIFYPATCH_VERSION}" in verify_job
    assert "path: subject" in req_job
    assert "--root" in req_job
    assert "working-directory:" in req_job
    assert "PYTHONNOUSERSITE" in req_job
    assert "PYTHONPATH" in req_job
    assert "runner.temp" in req_job
    assert "runner.temp" in verify_job
    assert "Validate requirements artifact" in req_job
    assert "load_requirements_artifact" in req_job
    assert "exact merge-base citation ranges" in req_job
    assert "validation.json" in req_job
    assert "requirements.md" in req_job
    assert "verifypatch.json" in verify_job
    assert "verifypatch.md" in verify_job
    # The requirements job must not execute or install the subject package.
    assert "Install repository dependencies" not in req_job
    assert "Install repository dependencies" in verify_job
    assert "working-directory:" in verify_job
    assert "--root" in verify_job


def test_action_shell_outputs(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    summary = tmp_path / "summary.md"
    output = tmp_path / "output.txt"
    md = tmp_path / "verifypatch.md"
    md.write_text("hello-summary\n", encoding="utf-8")
    json_path = tmp_path / "verifypatch.json"
    json_path.write_text("{}\n", encoding="utf-8")
    monkeypatch.setenv("GITHUB_STEP_SUMMARY", str(summary))
    monkeypatch.setenv("GITHUB_OUTPUT", str(output))
    monkeypatch.setenv("VERIFYPATCH_JSON_OUT", str(json_path))
    monkeypatch.setenv("VERIFYPATCH_MD_OUT", str(md))
    script = r"""
set -euo pipefail
json_path="$(python -c 'import os,pathlib; print(pathlib.Path(os.environ["VERIFYPATCH_JSON_OUT"]).resolve())')"
md_path="$(python -c 'import os,pathlib; print(pathlib.Path(os.environ["VERIFYPATCH_MD_OUT"]).resolve())')"
echo "json-path=${json_path}" >> "$GITHUB_OUTPUT"
echo "md-path=${md_path}" >> "$GITHUB_OUTPUT"
if [ -n "${GITHUB_STEP_SUMMARY:-}" ]; then
  cat "${VERIFYPATCH_MD_OUT}" >> "${GITHUB_STEP_SUMMARY}"
fi
"""
    import subprocess

    subprocess.run(["bash", "-c", script], check=True, cwd=tmp_path)
    assert "hello-summary" in summary.read_text(encoding="utf-8")
    out = output.read_text(encoding="utf-8")
    assert "json-path=" in out
    assert "md-path=" in out
    assert json_path.name in out
