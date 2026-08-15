from __future__ import annotations

from pathlib import Path

from verifypatch.classify import PathClass
from verifypatch.config import V2Config, load_config
from verifypatch.deadlines import start_deadline
from verifypatch.generation import GeneratedTestResult, GeneratedTestsResult
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
from verifypatch.mutation.ast_backend import AstMutationBackend
from verifypatch.mutation.backend import InvalidMutation, MutationSpec
from verifypatch.mutation.runner import run_mutation


class LifecycleBackend:
    name = "ast"
    version = "test"

    def __init__(self, inner: AstMutationBackend, extra: list[MutationSpec]) -> None:
        self.inner = inner
        self.extra = extra

    def list_mutations(self, root: Path, files: list[str]) -> list[MutationSpec]:
        listed = self.inner.list_mutations(root, files)
        source = (root / "mod.py").read_text(encoding="utf-8")
        chosen: list[MutationSpec] = []
        seen = set()
        for spec in listed:
            snippet = _span_text(source, spec)
            key = None
            if spec.operator == "arithmetic" and snippet == "+":
                key = "add"
            elif spec.operator == "arithmetic" and snippet == "*":
                key = "mul"
            elif spec.operator == "arithmetic" and snippet == "-":
                key = "ident"
            elif spec.operator == "constants" and snippet == "7":
                key = "flag"
            elif spec.operator == "constants" and snippet == "8":
                key = "hang"
            if key and key not in seen:
                seen.add(key)
                chosen.append(spec)
        return chosen + self.extra

    def apply(self, root: Path, spec: MutationSpec) -> None:
        if spec.operator == "invalid":
            raise InvalidMutation("forced invalid mutant")
        self.inner.apply(root, spec)


def _span_text(source: str, spec: MutationSpec) -> str:
    lines = source.splitlines()
    line = lines[spec.start_pos[0] - 1]
    return line[spec.start_pos[1] - 1 : spec.end_pos[1] - 1]


def test_origin_split_lifecycle(tmp_path: Path):
    (tmp_path / "mod.py").write_text(
        "def add(x, y):\n    return x + y\n"
        "def mul(x, y):\n    return x * y\n"
        "def ident(x):\n    return x - 0\n"
        "def flag():\n    return 7\n"
        "def hang():\n    return 8\n",
        encoding="utf-8",
    )
    tests = tmp_path / "tests"
    tests.mkdir()
    (tests / "__init__.py").write_text("", encoding="utf-8")
    (tests / "test_untouched.py").write_text(
        "from mod import add, ident, hang\n"
        "def test_add():\n    assert add(2, 3) == 5\n"
        "def test_ident():\n    assert ident(3) == 3\n"
        "def test_hang():\n"
        "    value = hang()\n"
        "    if value != 8:\n"
        "        import time\n"
        "        time.sleep(30)\n"
        "    assert value == 8\n",
        encoding="utf-8",
    )
    (tests / "test_touched.py").write_text(
        "from mod import mul\n"
        "def test_mul():\n    assert mul(2, 3) == 6\n",
        encoding="utf-8",
    )
    arts = tmp_path / "arts"
    gen_dir = arts / "generated_tests" / ".verifypatch_generated"
    gen_dir.mkdir(parents=True)
    (gen_dir / "__init__.py").write_text("", encoding="utf-8")
    gen_src = (
        "def test_flag():\n"
        "    import importlib\n"
        "    mod = importlib.import_module('mod')\n"
        "    assert mod.flag() == 7\n"
    )
    (gen_dir / "test_REQ_001.py").write_text(gen_src, encoding="utf-8")
    generated = GeneratedTestsResult(
        items=[
            GeneratedTestResult(
                id="gen-REQ-001",
                requirement_id="REQ-001",
                source_artifact="generated_tests/.verifypatch_generated/test_REQ_001.py",
                outcome="passed",
                nodeid=".verifypatch_generated/test_REQ_001.py::test_flag",
                source_digest="abc",
            )
        ]
    )
    report = Report(
        schema_version="2",
        tool_version="0.2.0",
        status="complete",
        requested_refs=RequestedRefs("a", "b"),
        resolved_refs=ResolvedRefs("a" * 40, "b" * 40, "a" * 40),
        diff=DiffCounts(1, 1, 0, 0, 1, 0, 0, 0),
        coverage=CoverageSummary(5, 3, 1, 0, 1, 0.6),
        tests=TestsSummary(),
        findings=[],
        line_evidence=[
            LineEvidence("mod.py", 2, "pr_untouched", ["tests/test_untouched.py::test_add"]),
            LineEvidence("mod.py", 4, "pr_touched_only", ["tests/test_touched.py::test_mul"]),
            LineEvidence("mod.py", 6, "pr_untouched", ["tests/test_untouched.py::test_ident"]),
            LineEvidence("mod.py", 8, "uncovered", []),
            LineEvidence("mod.py", 10, "pr_untouched", ["tests/test_untouched.py::test_hang"]),
        ],
        warnings=[],
        caveats=default_caveats(),
    )
    invalid = MutationSpec(
        path="mod.py",
        start_pos=(2, 1),
        end_pos=(2, 2),
        operator="invalid",
        occurrence=1,
        original="x",
        mutated="x",
        target_node="forced",
    )
    cfg = V2Config()
    cfg.mutation.enabled = True
    cfg.mutation.backend = "ast"
    cfg.mutation.per_mutant_timeout_seconds = 8
    classified = {
        "tests/test_touched.py": PathClass(path="tests/test_touched.py", kind="test_file"),
        "mod.py": PathClass(path="mod.py", kind="production"),
    }
    node_files = {
        "tests/test_untouched.py::test_add": "tests/test_untouched.py",
        "tests/test_untouched.py::test_ident": "tests/test_untouched.py",
        "tests/test_untouched.py::test_hang": "tests/test_untouched.py",
        "tests/test_touched.py::test_mul": "tests/test_touched.py",
    }
    stage, result = run_mutation(
        tmp_path,
        "b" * 40,
        cfg,
        report,
        classified,
        node_files,
        load_config(tmp_path),
        generated,
        arts,
        start_deadline(120),
        backend=LifecycleBackend(AstMutationBackend(), [invalid]),
    )
    assert stage.status == "complete", result
    summary = (
        f"untouched={result.summary.killed_by_pr_untouched} "
        f"touched={result.summary.killed_by_pr_touched} "
        f"generated={result.summary.killed_by_generated} "
        f"survived={result.summary.survived} "
        f"invalid={result.summary.invalid} "
        f"timeout={result.summary.timeout} "
        f"mutants={[ (m.operator, m.result, m.killing_origin, m.diff) for m in result.mutants ]}"
    )
    assert result.summary.killed_by_pr_untouched == 1, summary
    assert result.summary.killed_by_pr_touched == 1, summary
    assert result.summary.killed_by_generated == 1, summary
    assert result.summary.survived == 1, summary
    assert result.summary.invalid == 1, summary
    assert result.summary.timeout == 1, summary
    valid = (
        result.summary.killed_by_pr_untouched
        + result.summary.killed_by_pr_touched
        + result.summary.killed_by_generated
        + result.summary.survived
    )
    assert result.summary.independent_mutation_score == result.summary.killed_by_pr_untouched / valid
    assert result.summary.overall_mutation_score == (
        result.summary.killed_by_pr_untouched
        + result.summary.killed_by_pr_touched
        + result.summary.killed_by_generated
    ) / valid
