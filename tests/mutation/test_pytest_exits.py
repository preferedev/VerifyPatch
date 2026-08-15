from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

from verifypatch.mutation.pytest_exit import classify_pytest_exit
from verifypatch.mutation.runner import run_mutation
from verifypatch.mutation.backend import MutationSpec
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


class ScriptedBackend:
    name = "scripted"
    version = "test"

    def __init__(self, specs, apply_fn) -> None:
        self._specs = specs
        self._apply_fn = apply_fn

    def list_mutations(self, root: Path, files: list[str]):
        return list(self._specs)

    def apply(self, root: Path, spec: MutationSpec) -> None:
        self._apply_fn(root, spec)


def _report(nodeid: str = "tests/test_mod.py::test_x") -> Report:
    return Report(
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
            LineEvidence(path="mod.py", line=1, classification="pr_untouched", covering_node_ids=[nodeid])
        ],
        warnings=[],
        caveats=default_caveats(),
    )


def test_classify_pytest_exit_codes():
    assert classify_pytest_exit(0, False) == "survived"
    assert classify_pytest_exit(1, False) == "killed"
    assert classify_pytest_exit(2, False) == "interrupted"
    assert classify_pytest_exit(3, False) == "error"
    assert classify_pytest_exit(4, False) == "error"
    assert classify_pytest_exit(5, False) == "no_tests"
    assert classify_pytest_exit(1, True) == "timeout"
    assert classify_pytest_exit(None, True) == "timeout"


def test_infrastructure_exits_are_not_kills(tmp_path: Path, monkeypatch):
    (tmp_path / "mod.py").write_text("X = 1\n", encoding="utf-8")
    spec = MutationSpec(
        path="mod.py",
        start_pos=(1, 5),
        end_pos=(1, 6),
        operator="constants",
        occurrence=1,
        original="1",
        mutated="2",
        target_node="Constant",
    )

    def apply_fn(root: Path, spec: MutationSpec) -> None:
        (root / "mod.py").write_text("X = 2\n", encoding="utf-8")

    calls = {"code": 4}

    def fake_run(argv, **kwargs):
        return SimpleNamespace(
            returncode=calls["code"],
            stdout="",
            stderr="usage error",
            timed_out=False,
            duration_seconds=0.01,
        )

    monkeypatch.setattr("verifypatch.mutation.runner.run_bounded", fake_run)
    cfg = V2Config()
    cfg.mutation.enabled = True
    cfg.mutation.backend = "ast"
    for code, expected in [(2, "error"), (3, "error"), (4, "error"), (5, "error"), (0, "survived"), (1, "killed")]:
        calls["code"] = code
        stage, result = run_mutation(
            tmp_path,
            "b" * 40,
            cfg,
            _report(),
            {},
            {"tests/test_mod.py::test_x": "tests/test_mod.py"},
            load_config(tmp_path),
            empty_generated_tests(),
            tmp_path / "arts",
            start_deadline(30),
            backend=ScriptedBackend([spec], apply_fn),
        )
        assert stage.status == "complete"
        if expected == "killed":
            assert result.summary.killed_by_pr_untouched == 1
            assert result.summary.error == 0
            assert result.summary.independent_mutation_score == 1.0
        elif expected == "survived":
            assert result.summary.survived == 1
            assert result.summary.killed_by_pr_untouched == 0
            assert result.summary.independent_mutation_score == 0.0
        else:
            assert result.summary.error == 1
            assert result.summary.killed_by_pr_untouched == 0
            assert result.summary.independent_mutation_score is None


def test_apply_exception_is_not_a_kill(tmp_path: Path, monkeypatch):
    (tmp_path / "mod.py").write_text("X = 1\n", encoding="utf-8")
    spec = MutationSpec(
        path="mod.py",
        start_pos=(1, 5),
        end_pos=(1, 6),
        operator="constants",
        occurrence=1,
        original="1",
        mutated="2",
        target_node="Constant",
    )

    def apply_fn(root: Path, spec: MutationSpec) -> None:
        raise RuntimeError("backend exploded")

    cfg = V2Config()
    cfg.mutation.enabled = True
    stage, result = run_mutation(
        tmp_path,
        "b" * 40,
        cfg,
        _report(),
        {},
        {"tests/test_mod.py::test_x": "tests/test_mod.py"},
        load_config(tmp_path),
        empty_generated_tests(),
        tmp_path / "arts",
        start_deadline(30),
        backend=ScriptedBackend([spec], apply_fn),
    )
    assert stage.status == "complete"
    assert result.summary.invalid == 1
    assert result.summary.killed_by_pr_untouched == 0
    assert result.summary.independent_mutation_score is None


def test_timeout_is_never_killed(tmp_path: Path, monkeypatch):
    (tmp_path / "mod.py").write_text("X = 1\n", encoding="utf-8")
    spec = MutationSpec(
        path="mod.py",
        start_pos=(1, 5),
        end_pos=(1, 6),
        operator="constants",
        occurrence=1,
        original="1",
        mutated="2",
        target_node="Constant",
    )

    def apply_fn(root: Path, spec: MutationSpec) -> None:
        (root / "mod.py").write_text("X = 2\n", encoding="utf-8")

    def fake_run(argv, **kwargs):
        return SimpleNamespace(returncode=1, stdout="", stderr="", timed_out=True, duration_seconds=1.0)

    monkeypatch.setattr("verifypatch.mutation.runner.run_bounded", fake_run)
    cfg = V2Config()
    cfg.mutation.enabled = True
    stage, result = run_mutation(
        tmp_path,
        "b" * 40,
        cfg,
        _report(),
        {},
        {"tests/test_mod.py::test_x": "tests/test_mod.py"},
        load_config(tmp_path),
        empty_generated_tests(),
        tmp_path / "arts",
        start_deadline(30),
        backend=ScriptedBackend([spec], apply_fn),
    )
    assert result.summary.timeout == 1
    assert result.summary.killed_by_pr_untouched == 0
    assert result.summary.independent_mutation_score is None
