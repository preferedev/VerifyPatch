from __future__ import annotations

from pathlib import Path

from verifypatch.coverage_run import run_pytest_coverage
from verifypatch.engine import run_check
from verifypatch.pytest_invoke import VERIFYPATCH_PLUGIN_MODULE, coverage_pytest_main_args
from tests.helpers import materialize_fixture

WORKER = Path(__file__).resolve().parents[1] / "src" / "verifypatch" / "coverage_worker.py"
COVERAGE_RUN = Path(__file__).resolve().parents[1] / "src" / "verifypatch" / "coverage_run.py"


def test_package_docstring_disables_assertion_rewrite():
    import verifypatch
    import verifypatch.pytest_plugin as plugin
    from _pytest.assertion.rewrite import AssertionRewriter

    assert AssertionRewriter.is_rewrite_disabled(verifypatch.__doc__ or "")
    assert AssertionRewriter.is_rewrite_disabled(plugin.__doc__ or "")
    invoke = Path(__file__).resolve().parents[1] / "src" / "verifypatch" / "pytest_invoke.py"
    assert "unload_verifypatch_modules" in invoke.read_text(encoding="utf-8")
    assert "unload_verifypatch_modules" in WORKER.read_text(encoding="utf-8")
    assert "PYTEST_DONT_REWRITE" in (
        Path(__file__).resolve().parents[1] / "src" / "verifypatch" / "__init__.py"
    ).read_text(encoding="utf-8")


def test_worker_does_not_preimport_pytest_plugin():
    worker = WORKER.read_text(encoding="utf-8")
    coverage_run = COVERAGE_RUN.read_text(encoding="utf-8")
    assert "from verifypatch.pytest_plugin" not in worker
    assert "import verifypatch.pytest_plugin" not in worker
    assert "from verifypatch.pytest_plugin" not in coverage_run
    assert "import verifypatch.pytest_plugin" not in coverage_run
    args = coverage_pytest_main_args([])
    assert args[:4] == ["-p", "no:verifypatch", "-p", VERIFYPATCH_PLUGIN_MODULE]
    worker = WORKER.read_text(encoding="utf-8")
    assert "unload_verifypatch_modules" in worker
    assert "PYTEST_DISABLE_PLUGIN_AUTOLOAD" in worker or "DISABLE_AUTOLOAD_ENV" in worker
    coverage_run = COVERAGE_RUN.read_text(encoding="utf-8")
    assert "DISABLE_AUTOLOAD_ENV" in coverage_run


def test_filterwarnings_error_collection_and_coverage(tmp_path: Path):
    repo, base, head = materialize_fixture("filterwarnings_error", tmp_path / "repo")
    report = run_check(repo, base, head, pytest_args=[])
    assert report.status in {"complete", "incomplete"}
    assert report.tests.outcomes.collected >= 1
    assert report.tests.outcomes.passed >= 1
    assert report.coverage.changed_executable_lines >= 1
    assert report.tests.pytest_exit_code == 0
    warnings = " ".join(item.message for item in report.warnings)
    assert "cannot be rewritten" not in warnings
    assert "already imported" not in warnings


def test_filterwarnings_error_pytest_worker_exit(tmp_path: Path):
    repo, _base, _head = materialize_fixture("filterwarnings_error", tmp_path / "repo")
    work = tmp_path / "work"
    result = run_pytest_coverage(repo, [], timeout=60, work_dir=work)
    assert result.timed_out is False
    collected = result.plugin_payload.get("collected") or []
    assert collected
    assert result.exit_code == 0
