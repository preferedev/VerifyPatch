from __future__ import annotations

import shutil
import tempfile
from pathlib import Path

from verifypatch import SCHEMA_VERSION, __version__
from verifypatch.classify import PathClass, classify_diffs, classify_path
from verifypatch.cleanup import register_temp_dir, unregister_temp_dir
from verifypatch.config import VerifyPatchConfig, load_config
from verifypatch.coverage_run import run_pytest_coverage
from verifypatch.errors import AnalysisError
from verifypatch.gitops import (
    FileDiff,
    collect_diff,
    merge_base_sha,
    resolve_sha,
    tracked_dirty,
    worktree_head,
)
from verifypatch.heuristics import collect_findings, git_show
from verifypatch.model import (
    DiffCounts,
    Report,
    RequestedRefs,
    ResolvedRefs,
    TestChanges,
    TestOutcomes,
    TestsSummary,
    WarningRecord,
    default_caveats,
    empty_coverage,
)
from verifypatch.provenance import build_line_evidence, summarize_coverage
from verifypatch.xdist import reject_xdist


def _rel_node_files(root: Path, raw: dict[str, str | None]) -> dict[str, str | None]:
    mapped: dict[str, str | None] = {}
    root_res = root.resolve()
    for nodeid, path in raw.items():
        if not path:
            mapped[nodeid] = None
            continue
        candidate = Path(path)
        try:
            mapped[nodeid] = candidate.resolve().relative_to(root_res).as_posix()
        except ValueError:
            mapped[nodeid] = Path(path).as_posix()
    return mapped


def _outcomes(payload: dict) -> TestOutcomes:
    counts = TestOutcomes()
    tests = payload.get("tests") or []
    collected = payload.get("collected") or []
    counts.collected = len(collected) if collected else len(tests)
    for item in tests:
        outcome = item.get("outcome")
        if outcome == "passed":
            counts.passed += 1
        elif outcome == "failed":
            counts.failed += 1
        elif outcome == "skipped":
            counts.skipped += 1
        elif outcome == "xfailed":
            counts.xfailed += 1
        elif outcome == "xpassed":
            counts.xpassed += 1
        else:
            counts.error += 1
    return counts


def _ast_test_names(root: Path, sha: str, path: str) -> set[str]:
    text = git_show(root, sha, path)
    if text is None:
        return set()
    from verifypatch.heuristics import iter_test_functions
    import ast

    try:
        tree = ast.parse(text)
    except SyntaxError:
        return set()
    return {fn.qname for fn in iter_test_functions(tree, text)}


def build_test_changes(
    root: Path,
    merge_base: str,
    head: str,
    diff_files: list[FileDiff],
    classified: dict[str, PathClass],
    config: VerifyPatchConfig,
) -> TestChanges:
    test_files = [
        item
        for item in diff_files
        if classified.get(item.path, PathClass(item.path, "other")).kind in {"test_file", "conftest"}
        or (item.old_path and classify_path(item.old_path, config).kind in {"test_file", "conftest"})
    ]
    helpers = [
        item
        for item in diff_files
        if classified.get(item.path) and classified[item.path].kind == "shared_test_helper"
    ]
    nodes_added = nodes_removed = nodes_modified = 0
    for item in test_files:
        base_path = item.old_path or item.path
        base_names = _ast_test_names(root, merge_base, base_path)
        if item.status == "deleted":
            head_names: set[str] = set()
        else:
            head_names = _ast_test_names(root, head, item.path)
        nodes_added += len(head_names - base_names)
        nodes_removed += len(base_names - head_names)
        nodes_modified += len(base_names & head_names)
    return TestChanges(
        files_changed=len(test_files),
        nodes_added=nodes_added,
        nodes_removed=nodes_removed,
        nodes_modified=nodes_modified,
        shared_infrastructure_changed=len(helpers),
    )


def error_report(
    requested: RequestedRefs,
    resolved: ResolvedRefs | None,
    warnings: list[WarningRecord],
    message: str,
) -> Report:
    warnings = list(warnings) + [WarningRecord(code="analysis_error", message=message)]
    return Report(
        schema_version=SCHEMA_VERSION,
        tool_version=__version__,
        status="error",
        requested_refs=requested,
        resolved_refs=resolved,
        diff=DiffCounts(0, 0, 0, 0, 0, 0, 0, 0),
        coverage=empty_coverage(),
        tests=TestsSummary(),
        findings=[],
        line_evidence=[],
        warnings=warnings,
        caveats=default_caveats(),
    )


def run_check(
    root: Path,
    base: str,
    head: str,
    pytest_args: list[str],
    timeout: int | None = None,
    work_dir: Path | None = None,
) -> Report:
    requested = RequestedRefs(base=base, head=head)
    warnings: list[WarningRecord] = []
    root = root.resolve()
    config = load_config(root)
    timeout = timeout or config.timeout_seconds

    try:
        reject_xdist(root, pytest_args)
        base_sha = resolve_sha(root, base)
        head_sha = resolve_sha(root, head)
        current = worktree_head(root)
        if current != head_sha:
            raise AnalysisError(
                "Worktree HEAD does not match the resolved --head commit. "
                "v1 does not analyze one commit while executing another."
            )
        if tracked_dirty(root):
            raise AnalysisError(
                "Worktree has tracked modifications. Commit or stash them so execution matches HEAD."
            )
        merge_base = merge_base_sha(root, base_sha, head_sha)
        resolved = ResolvedRefs(base=base_sha, head=head_sha, merge_base=merge_base)
        diff = collect_diff(root, merge_base, head_sha)
    except (AnalysisError, OSError) as exc:
        report = error_report(requested, None, warnings, str(exc))
        return report

    classified = classify_diffs(diff.files, config)
    # also classify unchanged? only changed files matter for taint
    production_files = [
        item for item in diff.files if classified[item.path].kind == "production" and item.status != "deleted"
    ]
    test_files = [
        item
        for item in diff.files
        if classified[item.path].kind in {"test_file", "conftest"}
    ]
    helpers = [item for item in diff.files if classified[item.path].kind == "shared_test_helper"]
    deleted_prod = sum(
        item.deleted_line_count
        for item in diff.files
        if classified[item.path].kind == "production"
    )
    diff_counts = DiffCounts(
        production_files_changed=len(production_files),
        test_files_changed=len(test_files),
        shared_test_infrastructure_changed=len(helpers),
        files_added=sum(1 for item in diff.files if item.status == "added"),
        files_modified=sum(1 for item in diff.files if item.status == "modified"),
        files_deleted=sum(1 for item in diff.files if item.status == "deleted"),
        files_renamed=sum(1 for item in diff.files if item.status == "renamed"),
        production_lines_deleted=deleted_prod,
    )

    owned_tmp = False
    if work_dir is None:
        work_dir = Path(tempfile.mkdtemp(prefix="verifypatch-"))
        register_temp_dir(work_dir)
        owned_tmp = True
    try:
        try:
            run = run_pytest_coverage(root, pytest_args, timeout, work_dir)
        except AnalysisError as exc:
            report = error_report(requested, resolved, warnings, str(exc))
            report.diff = diff_counts
            return report

        payload = run.plugin_payload
        raw_nodes: dict[str, str | None] = {}
        collected = payload.get("collected") or []
        if collected and isinstance(collected[0], dict):
            for item in collected:
                raw_nodes[item["nodeid"]] = item.get("path")
        else:
            for nodeid in collected:
                raw_nodes[str(nodeid)] = None
        for item in payload.get("tests") or []:
            raw_nodes[item["nodeid"]] = item.get("path") or raw_nodes.get(item["nodeid"])
        node_files = _rel_node_files(root, raw_nodes)

        warnings.extend(run.settings.warnings)
        evidence = build_line_evidence(
            root,
            diff,
            classified,
            config,
            run.coverage_file,
            node_files,
            warnings,
            exclude_regex=run.settings.exclude_regex,
            coverage_settings=run.settings,
        )
        coverage = summarize_coverage(evidence)

        def _is_test_path(path: str) -> bool:
            return classify_path(path, config).kind in {"test_file", "conftest"}

        findings = collect_findings(root, merge_base, head_sha, diff.files, _is_test_path, warnings)
        changes = build_test_changes(root, merge_base, head_sha, diff.files, classified, config)
        changes.files_changed = diff_counts.test_files_changed
        changes.shared_infrastructure_changed = diff_counts.shared_test_infrastructure_changed

        incomplete_codes = {
            "source_analysis_failed",
            "unmapped_context",
            "empty_context",
            "unknown_coverage",
            "unsupported_concurrency",
            "test_parse_failed",
        }
        status = "complete"
        if any(w.code in incomplete_codes for w in warnings):
            status = "incomplete"
        if coverage.covered_only_by_unknown_contexts:
            status = "incomplete"

        report = Report(
            schema_version=SCHEMA_VERSION,
            tool_version=__version__,
            status=status,
            requested_refs=requested,
            resolved_refs=resolved,
            diff=diff_counts,
            coverage=coverage,
            tests=TestsSummary(
                outcomes=_outcomes(payload),
                changes=changes,
                pytest_exit_code=run.exit_code,
            ),
            findings=findings,
            line_evidence=evidence,
            warnings=warnings,
            caveats=default_caveats(),
            coverage_overrides=run.overrides,
        )
        return report
    finally:
        if owned_tmp:
            shutil.rmtree(work_dir, ignore_errors=True)
            unregister_temp_dir(work_dir)
