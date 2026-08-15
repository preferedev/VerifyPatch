from __future__ import annotations

from pathlib import Path

from verifypatch.gitops import collect_diff, merge_base_sha, resolve_sha
from tests.helpers import materialize_fixture


def test_resolves_shas_and_added_lines(tmp_path: Path):
    repo, base, head = materialize_fixture("discount", tmp_path / "repo")
    assert resolve_sha(repo, "HEAD") == head
    merge_base = merge_base_sha(repo, base, head)
    assert merge_base == base
    diff = collect_diff(repo, merge_base, head)
    by_path = diff.by_path()
    assert "src/promo.py" in by_path
    assert by_path["src/promo.py"].status == "added"
    assert by_path["src/pricing.py"].added_lines
    assert all("/" != "\\" for file in by_path)
