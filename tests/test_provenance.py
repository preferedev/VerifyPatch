from __future__ import annotations

from verifypatch.model import CoverageSummary, LineEvidence
from verifypatch.provenance import partition_line, summarize_coverage


def test_partition_prefers_untouched():
    assert partition_line({"pr_untouched", "pr_touched"}) == "pr_untouched"
    assert partition_line({"pr_touched"}) == "pr_touched_only"
    assert partition_line({"unknown"}) == "unknown_only"
    assert partition_line({"pr_touched", "unknown"}) == "unknown_only"
    assert partition_line(set()) == "uncovered"


def test_invariant():
    evidence = [
        LineEvidence("a.py", 1, "pr_untouched"),
        LineEvidence("a.py", 2, "pr_touched_only"),
        LineEvidence("a.py", 3, "unknown_only"),
        LineEvidence("b.py", 4, "uncovered"),
    ]
    summary = summarize_coverage(evidence)
    summary.assert_invariant()
    assert summary.changed_executable_lines == 4
    assert summary.pr_untouched_changed_line_coverage == 0.25


def test_zero_denominator():
    summary = summarize_coverage([])
    assert summary.changed_executable_lines == 0
    assert summary.pr_untouched_changed_line_coverage is None
    summary.assert_invariant()
