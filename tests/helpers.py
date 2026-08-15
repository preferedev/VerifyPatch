from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures"


def run_git(repo: Path, *args: str) -> str:
    result = subprocess.run(
        ["git", "-C", str(repo), *args],
        check=True,
        capture_output=True,
        text=True,
    )
    return result.stdout.strip()


def materialize_fixture(name: str, dest: Path) -> tuple[Path, str, str]:
    src = FIXTURES / name
    if dest.exists():
        shutil.rmtree(dest)
    dest.mkdir(parents=True)
    base_src = src / "base"
    shutil.copytree(base_src, dest, dirs_exist_ok=True)
    subprocess.run(["git", "init"], cwd=dest, check=True, capture_output=True)
    subprocess.run(["git", "add", "-A"], cwd=dest, check=True, capture_output=True)
    subprocess.run(
        [
            "git",
            "-c",
            "user.name=verifypatch",
            "-c",
            "user.email=verifypatch@example.com",
            "commit",
            "-m",
            "base",
        ],
        cwd=dest,
        check=True,
        capture_output=True,
    )
    base_sha = run_git(dest, "rev-parse", "HEAD")
    # replace tree with head
    for child in dest.iterdir():
        if child.name == ".git":
            continue
        if child.is_dir():
            shutil.rmtree(child)
        else:
            child.unlink()
    shutil.copytree(src / "head", dest, dirs_exist_ok=True)
    subprocess.run(["git", "add", "-A"], cwd=dest, check=True, capture_output=True)
    subprocess.run(
        [
            "git",
            "-c",
            "user.name=verifypatch",
            "-c",
            "user.email=verifypatch@example.com",
            "commit",
            "-m",
            "head",
        ],
        cwd=dest,
        check=True,
        capture_output=True,
    )
    head_sha = run_git(dest, "rev-parse", "HEAD")
    return dest, base_sha, head_sha


def normalize_report(payload: dict) -> dict:
    clone = json_clone(payload)
    if clone.get("resolved_refs"):
        clone["resolved_refs"] = {
            "base": "<BASE_SHA>",
            "head": "<HEAD_SHA>",
            "merge_base": "<MERGE_BASE_SHA>",
        }
    clone["tool_version"] = "<TOOL_VERSION>"
    clone["requested_refs"] = {"base": "<BASE>", "head": "<HEAD>"}
    for override in clone.get("coverage_overrides") or []:
        if override.get("key") == "data_file":
            override["value"] = "<COVERAGE_DATA_FILE>"
    return clone


def commit_all(repo: Path, message: str) -> str:
    subprocess.run(["git", "add", "-A"], cwd=repo, check=True, capture_output=True)
    subprocess.run(
        [
            "git",
            "-c",
            "user.name=verifypatch",
            "-c",
            "user.email=verifypatch@example.com",
            "commit",
            "-m",
            message,
        ],
        cwd=repo,
        check=True,
        capture_output=True,
    )
    return run_git(repo, "rev-parse", "HEAD")


def json_clone(payload: dict) -> dict:
    import json

    return json.loads(json.dumps(payload))
