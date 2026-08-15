from __future__ import annotations

import json
import os
import sys
from dataclasses import dataclass, field
from pathlib import Path

from coverage import Coverage
from coverage.data import CoverageData
from coverage.files import canonical_filename
from coverage.inorout import InOrOut, file_and_path_for_module
from coverage.plugin_support import Plugins
from coverage.python import source_for_file

from verifypatch.deadlines import run_bounded
from verifypatch.errors import AnalysisError
from verifypatch.model import CoverageOverride, WarningRecord
from verifypatch.plugin_env import PLUGIN_ACTIVE_ENV, PLUGIN_OUT_ENV
from verifypatch.pytest_invoke import DISABLE_AUTOLOAD_ENV
from verifypatch.redact import redact_text

UNSUPPORTED_CONCURRENCY = {
    "multiprocessing",
    "process",
    "thread",
    "gevent",
    "eventlet",
    "greenlet",
    "subprocess",
}


@dataclass
class CoverageSettings:
    root: Path
    coverage: Coverage
    inorout: InOrOut
    exclude_regex: str | None
    warnings: list[WarningRecord] = field(default_factory=list)


@dataclass
class PytestRunResult:
    exit_code: int
    plugin_payload: dict
    coverage_file: Path
    overrides: list[CoverageOverride]
    settings: CoverageSettings
    timed_out: bool = False


def _chdir(root: Path):
    previous = os.getcwd()
    os.chdir(root)
    return previous


def apply_required_overrides(cov: Coverage, data_file: Path) -> list[CoverageOverride]:
    cov.config.set_option("run:data_file", str(data_file))
    cov.config.set_option("run:relative_files", True)
    cov.config.set_option("run:branch", False)
    cov.config.set_option("run:parallel", False)
    cov.config.set_option("run:dynamic_context", "")
    # sysmon (Python 3.14 default) cannot record plugin switch_context node IDs.
    try:
        cov.config.set_option("run:core", "ctrace")
    except Exception:
        pass
    return [
        CoverageOverride(
            key="data_file",
            value=str(data_file),
            reason="Isolate VerifyPatch coverage data from the customer data file.",
        ),
        CoverageOverride(
            key="relative_files",
            value="true",
            reason="Normalize coverage paths to repository-relative POSIX paths.",
        ),
        CoverageOverride(
            key="branch",
            value="false",
            reason="v1 contract uses line coverage, not branch coverage.",
        ),
        CoverageOverride(
            key="parallel",
            value="false",
            reason="v1 supports a single pytest process.",
        ),
        CoverageOverride(
            key="dynamic_context",
            value="",
            reason="VerifyPatch sets exact pytest node IDs via its plugin.",
        ),
        CoverageOverride(
            key="core",
            value="ctrace",
            reason="Dynamic pytest node-ID contexts require the C tracer, not sysmon.",
        ),
    ]


def build_coverage(root: Path, data_file: Path) -> tuple[Coverage, list[CoverageOverride], list[WarningRecord]]:
    previous = _chdir(root)
    try:
        cov = Coverage(config_file=True, data_file=str(data_file), branch=False)
        overrides = apply_required_overrides(cov, data_file)
        warnings: list[WarningRecord] = []
        concurrency = [str(item) for item in (cov.config.concurrency or []) if item]
        risky = [item for item in concurrency if item in UNSUPPORTED_CONCURRENCY]
        if risky:
            warnings.append(
                WarningRecord(
                    code="unsupported_concurrency",
                    message=(
                        "coverage concurrency "
                        f"{risky} is not fully supported in v1; "
                        "coverage attribution may be incomplete."
                    ),
                )
            )
        return cov, overrides, warnings
    finally:
        os.chdir(previous)


def attach_inorout(cov: Coverage, root: Path) -> InOrOut:
    previous = _chdir(root)
    try:
        inorout = InOrOut(
            config=cov.config,
            warn=lambda msg, slug=None, once=False: None,
            debug=None,
            include_namespace_packages=bool(cov.config.include_namespace_packages),
        )
        inorout.plugins = Plugins()
        return inorout
    finally:
        os.chdir(previous)


def _exclude_regex(cov: Coverage) -> str | None:
    patterns = [pattern for pattern in cov.get_exclude_list() if pattern]
    if not patterns:
        return None
    return "(?:" + ")|(?:".join(patterns) + ")"


def prepare_coverage_settings(root: Path, data_file: Path) -> tuple[CoverageSettings, list[CoverageOverride]]:
    cov, overrides, warnings = build_coverage(root, data_file)
    settings = CoverageSettings(
        root=root.resolve(),
        coverage=cov,
        inorout=attach_inorout(cov, root),
        exclude_regex=_exclude_regex(cov),
        warnings=warnings,
    )
    return settings, overrides


def _package_covers_file(abs_path: str, inorout: InOrOut, root: Path) -> bool:
    target = canonical_filename(abs_path)
    previous = _chdir(root)
    inserted = False
    root_s = str(root.resolve())
    if root_s not in sys.path:
        sys.path.insert(0, root_s)
        inserted = True
    try:
        for pkg in inorout.source_pkgs:
            filename, locations = file_and_path_for_module(pkg)
            candidates: list[str] = []
            if filename and filename not in {"namespace", "built-in"}:
                canon = canonical_filename(source_for_file(filename))
                candidates.append(canon)
                if canon.endswith(f"{os.sep}__init__.py"):
                    candidates.append(os.path.dirname(canon))
            for loc in locations or []:
                candidates.append(canonical_filename(loc))
            for candidate in candidates:
                if target == candidate:
                    return True
                if target.startswith(candidate.rstrip(os.sep) + os.sep):
                    return True
        return False
    finally:
        if inserted:
            try:
                sys.path.remove(root_s)
            except ValueError:
                pass
        os.chdir(previous)


def _dotted_module_from_relpath(rel_path: str) -> str:
    dotted = rel_path.replace("\\", "/")
    if dotted.endswith(".py"):
        dotted = dotted[:-3]
    if dotted.endswith("/__init__"):
        dotted = dotted[: -len("/__init__")]
    return dotted.replace("/", ".")


class _StaticFrame:
    """Minimal frame so Coverage.py can resolve importable source_pkgs names.

    Coverage's should_trace() uses inspect.getmodulename() when no frame is
    present, which yields the basename (``mathy``) rather than the importable
    name (``src.mathy``). Passing __name__ uses Coverage's own matcher.
    """

    def __init__(self, module_name: str, filename: str) -> None:
        self.f_globals = {"__name__": module_name, "__file__": filename}


def coverage_measures_file(rel_path: str, settings: CoverageSettings) -> bool:
    abs_path = str((settings.root / rel_path).resolve())
    target = canonical_filename(abs_path)
    if settings.inorout.omit_match and settings.inorout.omit_match.match(target):
        return False
    previous = _chdir(settings.root)
    inserted = False
    root_s = str(settings.root)
    if root_s not in sys.path:
        sys.path.insert(0, root_s)
        inserted = True
    try:
        disp = settings.inorout.should_trace(abs_path, None)
        if disp.trace:
            return True
        if settings.inorout.source_pkgs_match or settings.inorout.source_pkgs:
            dotted = _dotted_module_from_relpath(rel_path)
            disp = settings.inorout.should_trace(abs_path, _StaticFrame(dotted, abs_path))
            if disp.trace:
                return True
            if settings.inorout.source_pkgs and _package_covers_file(
                abs_path, settings.inorout, settings.root
            ):
                if settings.inorout.omit_match and settings.inorout.omit_match.match(target):
                    return False
                return True
        return False
    finally:
        if inserted:
            try:
                sys.path.remove(root_s)
            except ValueError:
                pass
        os.chdir(previous)


def path_excluded_from_coverage(path: str, settings: CoverageSettings) -> bool:
    return not coverage_measures_file(path, settings)


def executable_statements(source_path: Path, cov: Coverage | None = None, exclude: str | None = None) -> set[int]:
    if cov is not None:
        _filename, statements, _excluded, _missing, _formatted = cov.analysis2(str(source_path))
        return set(statements)
    from coverage.parser import PythonParser

    parser = PythonParser(filename=str(source_path), exclude=exclude)
    parser.parse_source()
    return set(parser.statements)


def contexts_by_line(coverage_file: Path, filename: str) -> dict[int, set[str]]:
    data = CoverageData(basename=str(coverage_file))
    data.read()
    candidates = {filename}
    for measured in data.measured_files():
        normalized = measured.replace("\\", "/")
        if normalized == filename or normalized.endswith("/" + filename) or normalized.endswith(filename):
            candidates.add(measured)
    result: dict[int, set[str]] = {}
    for measured in candidates:
        mapping = data.contexts_by_lineno(measured)
        for line, contexts in mapping.items():
            result.setdefault(line, set()).update(ctx or "" for ctx in contexts)
    return result


def run_pytest_coverage(
    root: Path,
    pytest_args: list[str],
    timeout: int,
    work_dir: Path,
) -> PytestRunResult:
    work_dir.mkdir(parents=True, exist_ok=True)
    coverage_file = work_dir / ".coverage"
    analysis_file = work_dir / ".coverage-analysis"
    plugin_out = work_dir / "pytest_nodes.json"
    settings, overrides = prepare_coverage_settings(root, analysis_file)

    env = os.environ.copy()
    env[PLUGIN_OUT_ENV] = str(plugin_out)
    env[PLUGIN_ACTIVE_ENV] = "1"
    env[DISABLE_AUTOLOAD_ENV] = "1"
    env["COVERAGE_FILE"] = str(coverage_file)
    env["COVERAGE_CORE"] = "ctrace"
    env["VERIFYPATCH_ROOT"] = str(root.resolve())
    env["VERIFYPATCH_PYTEST_ARGS_JSON"] = json.dumps(list(pytest_args))
    command = [sys.executable, "-m", "verifypatch.coverage_worker"]
    completed = run_bounded(
        command,
        cwd=root,
        timeout=float(timeout),
        env=env,
    )
    if completed.timed_out:
        raise AnalysisError(
            f"pytest coverage run exceeded the wall-clock timeout of {timeout} seconds"
        )

    payload = {}
    if plugin_out.is_file():
        payload = json.loads(plugin_out.read_text(encoding="utf-8"))
    else:
        detail = redact_text(
            "\n".join(part for part in (completed.stderr or "", completed.stdout or "") if part).strip()
        )
        rewrite = "already imported so cannot be rewritten" in detail or "PytestAssertRewriteWarning" in detail
        if rewrite:
            settings.warnings.append(
                WarningRecord(
                    code="pytest_plugin_unsupported",
                    message=(
                        "Subject pytest warning policy aborted collection while loading the "
                        "VerifyPatch plugin. Coverage provenance is incomplete."
                    ),
                )
            )
            payload = {"exitstatus": completed.returncode, "collected": [], "tests": []}
        else:
            preview = detail[-4000:]
            raise AnalysisError(
                "pytest did not produce VerifyPatch plugin output. "
                f"exit={completed.returncode} output={preview}"
            )
    return PytestRunResult(
        exit_code=completed.returncode if completed.returncode is not None else 1,
        plugin_payload=payload,
        coverage_file=coverage_file,
        overrides=overrides,
        settings=settings,
        timed_out=completed.timed_out,
    )
