from __future__ import annotations

import json
import subprocess
from pathlib import Path

from verifypatch.artifacts import sha256_text
from verifypatch.config import V2Config
from verifypatch.deadlines import start_deadline
from verifypatch.requirements.artifact import load_requirements_artifact
from verifypatch.requirements.extract import extract_requirements
from verifypatch.requirements.firewall import (
    citation_matches,
    cited_range_digest,
    snapshot_from_text,
)
from verifypatch.requirements.model import ProviderResponse
from verifypatch.requirements.providers import FakeProvider

SPEC = "Prices must never be negative.\nSecond line of spec.\nThird line.\n"


def _git_repo(tmp_path: Path) -> tuple[Path, str, str]:
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "README.md").write_text(SPEC, encoding="utf-8")
    subprocess.run(["git", "init"], cwd=repo, check=True, capture_output=True)
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
            "base",
        ],
        cwd=repo,
        check=True,
        capture_output=True,
    )
    merge_base = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=repo, check=True, capture_output=True, text=True
    ).stdout.strip()
    (repo / "extra.txt").write_text("unrelated\n", encoding="utf-8")
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
            "head",
        ],
        cwd=repo,
        check=True,
        capture_output=True,
    )
    head = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=repo, check=True, capture_output=True, text=True
    ).stdout.strip()
    return repo, merge_base, head


def _cfg() -> V2Config:
    cfg = V2Config()
    cfg.requirements.enabled = True
    cfg.requirements.model = "fake"
    cfg.requirements.task_files = ["README.md"]
    cfg.requirements.base_sources = ["README.md"]
    return cfg


def _item(ref: str, path: str, start: int, end: int, digest: str, req_id: str = "REQ-1") -> dict:
    return {
        "id": req_id,
        "statement": "Prices must never be negative.",
        "kind": "non_negative",
        "confidence": "high",
        "executable": True,
        "citations": [
            {
                "ref": ref,
                "path": path,
                "start_line": start,
                "end_line": end,
                "digest": digest,
            }
        ],
        "target_module": "pricing",
        "target_callable": "final_price",
        "parameters": {},
    }


def _payload(items: list[dict]) -> dict:
    return {
        "schema_version": "1",
        "prompt_version": "requirements-extract-v1",
        "items": items,
    }


def _extract(repo: Path, merge_base: str, items: list[dict]):
    provider = FakeProvider(
        ProviderResponse(payload=_payload(items), provider="fake", model="fake", constrained_output=True)
    )
    return extract_requirements(repo, merge_base, _cfg(), set(), start_deadline(90), provider=provider)


def _artifact(tmp_path: Path, repo: Path, merge_base: str, items: list[dict]):
    path = tmp_path / "req.json"
    path.write_text(json.dumps(_payload(items)), encoding="utf-8")
    return load_requirements_artifact(path, root=repo, merge_base=merge_base, config=_cfg())


def test_valid_exact_range_citation_is_accepted(tmp_path: Path):
    repo, merge_base, _head = _git_repo(tmp_path)
    source = snapshot_from_text(merge_base, "README.md", SPEC, "task")
    digest = cited_range_digest(source, 1, 1)
    assert digest == sha256_text("Prices must never be negative.")
    stage, result = _extract(repo, merge_base, [_item(merge_base, "README.md", 1, 1, digest)])
    assert stage.status == "complete"
    assert len(result.items) == 1
    assert result.items[0].citations[0].ref == merge_base
    assert result.items[0].citations[0].digest == digest


def test_wrong_git_ref_is_rejected(tmp_path: Path):
    repo, merge_base, _head = _git_repo(tmp_path)
    source = snapshot_from_text(merge_base, "README.md", SPEC, "task")
    digest = cited_range_digest(source, 1, 1)
    assert citation_matches(source, merge_base, "README.md", 1, 1, digest)
    assert not citation_matches(source, "0" * 40, "README.md", 1, 1, digest)
    _, result = _extract(repo, merge_base, [_item("0" * 40, "README.md", 1, 1, digest)])
    assert result.items == []


def test_head_ref_substituted_for_merge_base_is_rejected(tmp_path: Path):
    repo, merge_base, head = _git_repo(tmp_path)
    source = snapshot_from_text(merge_base, "README.md", SPEC, "task")
    digest = cited_range_digest(source, 1, 1)
    _, result = _extract(repo, merge_base, [_item(head, "README.md", 1, 1, digest)])
    assert result.items == []
    loaded, err = _artifact(tmp_path, repo, merge_base, [_item(head, "README.md", 1, 1, digest)])
    assert err and err.code == "citation_mismatch"
    assert loaded is not None and loaded.items == []


def test_reversed_range_is_rejected(tmp_path: Path):
    repo, merge_base, _head = _git_repo(tmp_path)
    source = snapshot_from_text(merge_base, "README.md", SPEC, "task")
    digest = cited_range_digest(source, 1, 3) or source.digest
    assert not citation_matches(source, merge_base, "README.md", 3, 1, digest)
    _, result = _extract(repo, merge_base, [_item(merge_base, "README.md", 3, 1, digest)])
    assert result.items == []
    loaded, err = _artifact(tmp_path, repo, merge_base, [_item(merge_base, "README.md", 3, 1, digest)])
    assert err and err.code == "citation_mismatch"
    assert loaded is not None and loaded.items == []


def test_zero_and_negative_ranges_are_rejected(tmp_path: Path):
    repo, merge_base, _head = _git_repo(tmp_path)
    source = snapshot_from_text(merge_base, "README.md", SPEC, "task")
    digest = cited_range_digest(source, 1, 1)
    assert not citation_matches(source, merge_base, "README.md", 0, 1, digest)
    assert not citation_matches(source, merge_base, "README.md", -1, 1, digest)
    assert not citation_matches(source, merge_base, "README.md", 1, 0, digest)
    _, result = _extract(repo, merge_base, [_item(merge_base, "README.md", 0, 1, digest)])
    assert result.items == []
    loaded, err = _artifact(tmp_path, repo, merge_base, [_item(merge_base, "README.md", -2, 1, digest)])
    assert err and err.code in {"citation_mismatch", "invalid_requirements_artifact"}


def test_out_of_bounds_range_is_rejected(tmp_path: Path):
    repo, merge_base, _head = _git_repo(tmp_path)
    source = snapshot_from_text(merge_base, "README.md", SPEC, "task")
    digest = cited_range_digest(source, 1, 1)
    assert not citation_matches(source, merge_base, "README.md", 1, 99, digest)
    _, result = _extract(repo, merge_base, [_item(merge_base, "README.md", 1, 99, digest)])
    assert result.items == []
    loaded, err = _artifact(tmp_path, repo, merge_base, [_item(merge_base, "README.md", 1, 99, digest)])
    assert err and err.code == "citation_mismatch"


def test_snapshot_digest_does_not_authenticate_wrong_subrange(tmp_path: Path):
    repo, merge_base, _head = _git_repo(tmp_path)
    source = snapshot_from_text(merge_base, "README.md", SPEC, "task")
    assert source.digest != cited_range_digest(source, 2, 2)
    assert not citation_matches(source, merge_base, "README.md", 2, 2, source.digest)
    _, result = _extract(repo, merge_base, [_item(merge_base, "README.md", 2, 2, source.digest)])
    assert result.items == []
    loaded, err = _artifact(tmp_path, repo, merge_base, [_item(merge_base, "README.md", 2, 2, source.digest)])
    assert err and err.code == "citation_mismatch"


def test_forged_digest_with_correct_range_is_rejected(tmp_path: Path):
    repo, merge_base, _head = _git_repo(tmp_path)
    source = snapshot_from_text(merge_base, "README.md", SPEC, "task")
    assert cited_range_digest(source, 1, 1)
    forged = "a" * 64
    assert not citation_matches(source, merge_base, "README.md", 1, 1, forged)
    _, result = _extract(repo, merge_base, [_item(merge_base, "README.md", 1, 1, forged)])
    assert result.items == []
    loaded, err = _artifact(tmp_path, repo, merge_base, [_item(merge_base, "README.md", 1, 1, forged)])
    assert err and err.code == "citation_mismatch"


def test_requirement_with_one_invalid_citation_is_dropped(tmp_path: Path):
    repo, merge_base, _head = _git_repo(tmp_path)
    source = snapshot_from_text(merge_base, "README.md", SPEC, "task")
    good = cited_range_digest(source, 1, 1)
    bad = source.digest
    item = _item(merge_base, "README.md", 1, 1, good)
    item["citations"].append(
        {
            "ref": merge_base,
            "path": "README.md",
            "start_line": 2,
            "end_line": 2,
            "digest": bad,
        }
    )
    _, result = _extract(repo, merge_base, [item])
    assert result.items == []
    loaded, err = _artifact(tmp_path, repo, merge_base, [item])
    assert err and err.code == "citation_mismatch"
    assert loaded is not None and loaded.items == []


def test_artifact_rejects_mixed_valid_and_invalid_requirements(tmp_path: Path):
    repo, merge_base, _head = _git_repo(tmp_path)
    source = snapshot_from_text(merge_base, "README.md", SPEC, "task")
    good = cited_range_digest(source, 1, 1)
    valid = _item(merge_base, "README.md", 1, 1, good, "REQ-OK")
    invalid = _item("forged-ref", "README.md", 1, 1, good, "REQ-BAD")
    _, extracted = _extract(repo, merge_base, [valid, invalid])
    assert [item.id for item in extracted.items] == ["REQ-OK"]
    loaded, err = _artifact(tmp_path, repo, merge_base, [valid, invalid])
    assert err and err.code == "citation_mismatch"
    assert loaded is not None and loaded.items == []
