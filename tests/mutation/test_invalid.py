from __future__ import annotations

from pathlib import Path

from verifypatch.mutation.backend import MutationSpec
from verifypatch.mutation.runner import run_mutation
from verifypatch.model import (
    CoverageSummary,
    DiffCounts,
    LineEvidence,
    Report,
    RequestedRefs,
    ResolvedRefs,
    TestsSummary,
    default_caveats,
)
from verifypatch.config import V2Config, load_config
from verifypatch.deadlines import start_deadline
from verifypatch.generation import empty_generated_tests


class RaisingBackend:
    name = "raise"

    def list_mutations(self, root: Path, files: list[str]):
        return [
            MutationSpec(
                path="mod.py",
                start_pos=(1, 1),
                end_pos=(1, 2),
                operator="comparison",
                occurrence=1,
                original="Eq",
                mutated="NotEq",
            )
        ]

    def apply(self, root: Path, spec: MutationSpec) -> None:
        raise ValueError("cannot apply")


def test_invalid_mutant_when_apply_fails(tmp_path: Path):
    (tmp_path / "mod.py").write_text("x = 1\n", encoding="utf-8")
    report = Report(
        schema_version="2",
        tool_version="0.2.0",
        status="complete",
        requested_refs=RequestedRefs("a", "b"),
        resolved_refs=ResolvedRefs("a" * 40, "b" * 40, "a" * 40),
        diff=DiffCounts(1, 0, 0, 0, 1, 0, 0, 0),
        coverage=CoverageSummary(1, 1, 0, 0, 0, 1.0),
        tests=TestsSummary(),
        findings=[],
        line_evidence=[
            LineEvidence(path="mod.py", line=1, classification="pr_untouched", covering_node_ids=["tests/test_mod.py::test_x"])
        ],
        warnings=[],
        caveats=default_caveats(),
    )
    cfg = V2Config()
    cfg.mutation.enabled = True
    stage, result = run_mutation(
        tmp_path,
        "b" * 40,
        cfg,
        report,
        {},
        {"tests/test_mod.py::test_x": "tests/test_mod.py"},
        load_config(tmp_path),
        empty_generated_tests(),
        tmp_path / "arts",
        start_deadline(30),
        backend=RaisingBackend(),
    )
    assert stage.status == "complete"
    assert result.summary.invalid == 1
    assert result.summary.independent_mutation_score is None
    assert result.mutants[0].result == "invalid"
