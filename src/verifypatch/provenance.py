from __future__ import annotations

from pathlib import Path

from verifypatch.classify import (
    PathClass,
    ancestor_conftest_paths,
    under_directory,
)
from verifypatch.config import VerifyPatchConfig
from verifypatch.coverage_run import (
    CoverageSettings,
    contexts_by_line,
    executable_statements,
    path_excluded_from_coverage,
)
from verifypatch.gitops import GitDiff, posix_relpath
from verifypatch.model import (
    CoverageSummary,
    LineClassification,
    LineEvidence,
    WarningRecord,
)


def _rel_from_root(root: Path, maybe_path: str | None) -> str | None:
    if not maybe_path:
        return None
    path = Path(maybe_path)
    try:
        return posix_relpath(str(path.resolve().relative_to(root.resolve())))
    except ValueError:
        return posix_relpath(maybe_path)


def taint_reasons(
    test_file: str,
    changed: dict[str, PathClass],
    config: VerifyPatchConfig,
) -> list[str]:
    reasons: list[str] = []
    classified = changed.get(test_file)
    if classified and classified.kind in {"test_file", "conftest"}:
        reasons.append(f"test_file_changed:{test_file}")
    for conftest in ancestor_conftest_paths(test_file):
        if conftest in changed and changed[conftest].kind == "conftest":
            reasons.append(f"conftest_changed:{conftest}")
    for path, kind in changed.items():
        if kind.kind != "shared_test_helper":
            continue
        helper_dir = str(Path(path).parent).replace("\\", "/")
        if helper_dir in {".", ""}:
            reasons.append(f"helper_changed_unresolved:{path}")
            continue
        if under_directory(test_file, helper_dir):
            reasons.append(f"helper_changed:{path}")
    return reasons


def classify_context(
    context: str,
    node_files: dict[str, str | None],
    root: Path,
    changed: dict[str, PathClass],
    config: VerifyPatchConfig,
) -> tuple[str, list[str]]:
    """Return (pr_untouched|pr_touched|unknown, notes)."""
    if not context or context.strip() == "":
        return "unknown", ["empty_context"]
    if context not in node_files:
        return "unknown", [f"unmapped_context:{context}"]
    rel = _rel_from_root(root, node_files.get(context))
    if not rel:
        return "unknown", [f"unmapped_test_file:{context}"]
    reasons = taint_reasons(rel, changed, config)
    if any(note.startswith("helper_changed_unresolved:") for note in reasons):
        return "unknown", reasons
    if reasons:
        return "pr_touched", reasons
    return "pr_untouched", []


def partition_line(labels: set[str]) -> LineClassification:
    if "pr_untouched" in labels:
        return "pr_untouched"
    if "pr_touched" in labels and "unknown" not in labels:
        return "pr_touched_only"
    if "pr_touched" in labels and "unknown" in labels:
        # Independent evidence does not exist; mixed touched+unknown is unknown.
        return "unknown_only"
    if "unknown" in labels:
        return "unknown_only"
    return "uncovered"


def build_line_evidence(
    root: Path,
    diff: GitDiff,
    classified_files: dict[str, PathClass],
    config: VerifyPatchConfig,
    coverage_file: Path,
    node_files: dict[str, str | None],
    warnings: list[WarningRecord],
    exclude_regex: str | None = None,
    coverage_settings: CoverageSettings | None = None,
) -> list[LineEvidence]:
    production_changed = [
        item
        for item in diff.files
        if item.status != "deleted"
        and classified_files.get(item.path, PathClass(item.path, "other")).kind == "production"
    ]
    evidence: list[LineEvidence] = []
    for item in production_changed:
        if coverage_settings is not None and path_excluded_from_coverage(item.path, coverage_settings):
            warnings.append(
                WarningRecord(
                    code="coverage_path_excluded",
                    message=(
                        f"{item.path} is omitted or outside the customer coverage source; "
                        "it is excluded from the changed-line denominator."
                    ),
                    path=item.path,
                )
            )
            continue
        abs_path = root / item.path
        if not abs_path.is_file():
            warnings.append(
                WarningRecord(
                    code="missing_head_file",
                    message=f"Changed production file {item.path} is missing on HEAD.",
                    path=item.path,
                )
            )
            continue
        try:
            statements = executable_statements(
                abs_path,
                cov=coverage_settings.coverage if coverage_settings is not None else None,
                exclude=exclude_regex,
            )
        except Exception as exc:  # noqa: BLE001 - parser failures become warnings
            warnings.append(
                WarningRecord(
                    code="source_analysis_failed",
                    message=f"Could not analyze executable lines in {item.path}: {exc}",
                    path=item.path,
                )
            )
            continue
        changed_exec = sorted(line for line in item.added_lines if line in statements)
        ctx_map = contexts_by_line(coverage_file, item.path)
        for line in changed_exec:
            raw_contexts = ctx_map.get(line, set())
            labels: set[str] = set()
            notes: list[str] = []
            covering: list[str] = []
            if not raw_contexts:
                labels.add("uncovered")
            for context in sorted(raw_contexts):
                if not context:
                    labels.add("unknown")
                    notes.append("empty_context")
                    continue
                covering.append(context)
                label, extra = classify_context(
                    context, node_files, root, classified_files, config
                )
                labels.add(label)
                notes.extend(extra)
            classification = partition_line(labels)
            if classification == "unknown_only":
                if "empty_context" in notes:
                    warnings.append(
                        WarningRecord(
                            code="empty_context",
                            message=(
                                f"{item.path}:{line} was covered only by an empty coverage context."
                            ),
                            path=item.path,
                        )
                    )
                elif any(note.startswith("unmapped_context:") for note in notes):
                    warnings.append(
                        WarningRecord(
                            code="unmapped_context",
                            message=(
                                f"{item.path}:{line} was covered by a context that could not be mapped to a collected test."
                            ),
                            path=item.path,
                        )
                    )
                else:
                    warnings.append(
                        WarningRecord(
                            code="unknown_coverage",
                            message=(
                                f"{item.path}:{line} was covered only by unknown or ambiguous contexts."
                            ),
                            path=item.path,
                        )
                    )
            evidence.append(
                LineEvidence(
                    path=item.path,
                    line=line,
                    classification=classification,
                    covering_node_ids=covering,
                    notes=sorted(set(notes)),
                )
            )
    return evidence


def summarize_coverage(evidence: list[LineEvidence]) -> CoverageSummary:
    counts = {
        "pr_untouched": 0,
        "pr_touched_only": 0,
        "unknown_only": 0,
        "uncovered": 0,
    }
    for row in evidence:
        counts[row.classification] += 1
    total = sum(counts.values())
    ratio = None if total == 0 else counts["pr_untouched"] / total
    summary = CoverageSummary(
        changed_executable_lines=total,
        covered_by_pr_untouched_tests=counts["pr_untouched"],
        covered_only_by_pr_touched_tests=counts["pr_touched_only"],
        covered_only_by_unknown_contexts=counts["unknown_only"],
        uncovered=counts["uncovered"],
        pr_untouched_changed_line_coverage=ratio,
    )
    summary.assert_invariant()
    return summary
