from __future__ import annotations

import argparse
import json
import shlex
import sys
from pathlib import Path

from verifypatch.engine import run_check
from verifypatch.errors import AnalysisError, VerifyPatchError, UnsupportedError
from verifypatch.model import SCHEMA_VERSION_V2, Report
from verifypatch.report import write_reports
from verifypatch.schema import bundled_schema_names, load_schema_text
from verifypatch.stage import default_pipeline
from verifypatch.behavior import empty_behavior
from verifypatch.generation import empty_generated_tests
from verifypatch.mutation import empty_mutation
from verifypatch.policy import empty_policy
from verifypatch.requirements import empty_requirements


def _add_check_flags(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--base", required=True, help="Base git ref or SHA.")
    parser.add_argument("--head", default="HEAD", help="Head git ref or SHA (default: HEAD).")
    parser.add_argument("--root", default=".", help="Repository root (default: current directory).")
    parser.add_argument("--json-out", default="verifypatch.json")
    parser.add_argument("--md-out", default="verifypatch.md")
    parser.add_argument(
        "--pytest-args",
        default="",
        help="Extra arguments forwarded to pytest (quoted string).",
    )
    parser.add_argument(
        "--timeout",
        type=int,
        default=None,
        help="Wall-clock timeout in seconds for the pytest coverage run (default: 600).",
    )
    parser.add_argument(
        "--schema-version",
        choices=("1", "2"),
        default=None,
        help="Report schema version. check defaults to 1; verify defaults to 2.",
    )


def _add_v2_flags(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--config", default=None, help="Path to verifypatch.yml (default: verifypatch.yml when present).")
    parser.add_argument("--requirements", dest="requirements", action="store_true", default=None)
    parser.add_argument("--no-requirements", dest="requirements", action="store_false")
    parser.add_argument("--generate", dest="generate", action="store_true", default=None)
    parser.add_argument("--no-generate", dest="generate", action="store_false")
    parser.add_argument("--mutation", dest="mutation", action="store_true", default=None)
    parser.add_argument("--no-mutation", dest="mutation", action="store_false")
    parser.add_argument("--behavior", dest="behavior", action="store_true", default=None)
    parser.add_argument("--no-behavior", dest="behavior", action="store_false")
    parser.add_argument("--enforce", action="store_true", default=False)
    parser.add_argument("--artifacts-dir", default=None)
    parser.add_argument("--optional-timeout", type=int, default=None)
    parser.add_argument(
        "--requirements-only",
        action="store_true",
        default=False,
        help="Extract requirements from merge-base sources without executing head tests.",
    )
    parser.add_argument(
        "--requirements-file",
        default=None,
        help="Load a previously extracted requirements artifact instead of calling a provider.",
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="verifypatch",
        description="Measure PR-untouched evidence provenance for Python/pytest changes.",
    )
    sub = parser.add_subparsers(dest="command", required=True)
    check = sub.add_parser("check", help="Analyze base...head and write JSON/Markdown reports.")
    _add_check_flags(check)

    verify = sub.add_parser("verify", help="Run the configured v2 pipeline.")
    _add_check_flags(verify)
    _add_v2_flags(verify)

    policy = sub.add_parser("policy", help="Evaluate an existing JSON report.")
    policy.add_argument("--report", required=True, help="Path to verifypatch.json")
    policy.add_argument("--config", default=None)
    policy.add_argument("--root", default=".")
    policy.add_argument("--enforce", action="store_true", default=False)
    policy.add_argument("--json-out", default=None)
    policy.add_argument("--md-out", default=None)

    schema = sub.add_parser("schema", help="Print a bundled JSON schema.")
    schema.add_argument(
        "name",
        nargs="?",
        default="report-v1",
        help="report-v1 | report-v2 | requirements-v1",
    )
    return parser


def _promote_v2(report: Report) -> Report:
    report.schema_version = SCHEMA_VERSION_V2
    if report.pipeline is None:
        report.pipeline = default_pipeline()
    if report.requirements is None:
        report.requirements = empty_requirements()
    if report.generated_tests is None:
        report.generated_tests = empty_generated_tests()
    if report.mutation is None:
        report.mutation = empty_mutation()
    if report.behavioral_comparison is None:
        report.behavioral_comparison = empty_behavior()
    if report.policy is None:
        report.policy = empty_policy()
    if report.artifacts is None:
        report.artifacts = {"directory": ".verifypatch/artifacts", "items": []}
    return report


def _run_check_command(args: argparse.Namespace) -> tuple[int, Report | None]:
    pytest_args = shlex.split(args.pytest_args or "")
    root = Path(args.root)
    try:
        report = run_check(
            root=root,
            base=args.base,
            head=args.head,
            pytest_args=pytest_args,
            timeout=args.timeout,
        )
    except UnsupportedError as exc:
        print(f"verifypatch: {exc}", file=sys.stderr)
        return 2, None
    except AnalysisError as exc:
        print(f"verifypatch: {exc}", file=sys.stderr)
        return 2, None
    except VerifyPatchError as exc:
        print(f"verifypatch: {exc}", file=sys.stderr)
        return 2, None
    if args.schema_version == "2":
        _promote_v2(report)
    return (2 if report.status == "error" else 0), report


def _write(report: Report, json_out: Path, md_out: Path) -> int:
    if not json_out.is_absolute():
        json_out = Path.cwd() / json_out
    if not md_out.is_absolute():
        md_out = Path.cwd() / md_out
    try:
        write_reports(report, json_out, md_out)
    except ValueError as exc:
        print(f"verifypatch: {exc}", file=sys.stderr)
        return 2
    print(f"Wrote {json_out}")
    print(f"Wrote {md_out}")
    if report.status == "error":
        return 2
    return 0


def main(argv: list[str] | None = None) -> int:
    from verifypatch.cleanup import install_cleanup_handlers

    install_cleanup_handlers()
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.command == "schema":
        mapping = {
            "report-v1": "1",
            "v1": "1",
            "1": "1",
            "report-v2": "2",
            "v2": "2",
            "2": "2",
            "requirements-v1": "requirements-v1",
            "requirements": "requirements-v1",
        }
        key = mapping.get(args.name)
        if key is None:
            print(f"verifypatch: unknown schema {args.name!r}; choose from {sorted(bundled_schema_names())}", file=sys.stderr)
            return 2
        sys.stdout.write(load_schema_text(key))
        if not load_schema_text(key).endswith("\n"):
            sys.stdout.write("\n")
        return 0

    if args.command == "check":
        code, report = _run_check_command(args)
        if report is None:
            return code
        written = _write(report, Path(args.json_out), Path(args.md_out))
        return code if code else written

    if args.command == "verify":
        from verifypatch.pipeline import config_for_verify, run_verify

        root = Path(args.root)
        config_path = Path(args.config) if args.config else None
        overrides = {
            "requirements": args.requirements,
            "generate": args.generate,
            "mutation": args.mutation,
            "behavior": args.behavior,
            "enforce": args.enforce,
            "artifacts_dir": args.artifacts_dir,
            "optional_timeout": args.optional_timeout,
        }
        try:
            v2 = config_for_verify(root, config_path, overrides)
            report = run_verify(
                root,
                args.base,
                args.head,
                shlex.split(args.pytest_args or ""),
                args.timeout,
                v2,
                enforce=args.enforce,
                requirements_only=bool(args.requirements_only),
                requirements_file=Path(args.requirements_file) if args.requirements_file else None,
            )
        except UnsupportedError as exc:
            print(f"verifypatch: {exc}", file=sys.stderr)
            return 2
        except AnalysisError as exc:
            print(f"verifypatch: {exc}", file=sys.stderr)
            return 2
        except VerifyPatchError as exc:
            print(f"verifypatch: {exc}", file=sys.stderr)
            return 2
        if args.schema_version == "1":
            print("verifypatch: verify always emits schema v2", file=sys.stderr)
        code = _write(report, Path(args.json_out), Path(args.md_out))
        if code:
            return code
        if args.enforce and report.policy and report.policy.decision == "block":
            return 3
        return 0

    if args.command == "policy":
        from verifypatch.config import load_v2_config
        from verifypatch.model import Report as ReportModel
        from verifypatch.policy.evaluate import evaluate_policy
        from verifypatch.report import validate_report, write_reports

        payload = json.loads(Path(args.report).read_text(encoding="utf-8"))
        validate_report(payload)
        root = Path(args.root)
        config_path = Path(args.config) if args.config else None
        cfg = load_v2_config(root, config_path)
        # Reconstruct a Report-like object for evaluation from the JSON payload.
        from verifypatch.engine import error_report  # unused; use dataclass rebuild via types
        from verifypatch.model import (
            CoverageSummary,
            DiffCounts,
            Finding,
            LineEvidence,
            RequestedRefs,
            ResolvedRefs,
            TestChanges,
            TestOutcomes,
            TestsSummary,
            WarningRecord,
        )

        tests = payload["tests"]
        report = Report(
            schema_version=str(payload["schema_version"]),
            tool_version=payload["tool_version"],
            status=payload["status"],
            requested_refs=RequestedRefs(**payload["requested_refs"]),
            resolved_refs=ResolvedRefs(**payload["resolved_refs"]) if payload.get("resolved_refs") else None,
            diff=DiffCounts(**payload["diff"]),
            coverage=CoverageSummary(**payload["coverage"]),
            tests=TestsSummary(
                outcomes=TestOutcomes(**tests["outcomes"]),
                changes=TestChanges(**tests["changes"]),
                pytest_exit_code=tests.get("pytest_exit_code"),
            ),
            findings=[Finding(**item) for item in payload.get("findings") or []],
            line_evidence=[LineEvidence(**item) for item in payload.get("line_evidence") or []],
            warnings=[WarningRecord(**item) for item in payload.get("warnings") or []],
            caveats=list(payload.get("caveats") or []),
        )
        if payload.get("pipeline"):
            from verifypatch.stage import PipelineSummary, StageResult, Reason, ArtifactRef

            stages = []
            for raw in payload["pipeline"]["stages"]:
                skip = Reason(**raw["skip_reason"]) if raw.get("skip_reason") else None
                err = Reason(**raw["error_reason"]) if raw.get("error_reason") else None
                arts = [ArtifactRef(**item) for item in raw.get("artifacts") or []]
                stages.append(
                    StageResult(
                        name=raw["name"],
                        status=raw["status"],
                        started_at=raw.get("started_at"),
                        ended_at=raw.get("ended_at"),
                        duration_ms=raw.get("duration_ms"),
                        configured_deadline_seconds=raw.get("configured_deadline_seconds"),
                        effective_deadline_seconds=raw.get("effective_deadline_seconds"),
                        warnings=list(raw.get("warnings") or []),
                        skip_reason=skip,
                        error_reason=err,
                        artifacts=arts,
                        tool_versions=dict(raw.get("tool_versions") or {}),
                    )
                )
            report.pipeline = PipelineSummary(
                stages=stages,
                optional_deadline_seconds=payload["pipeline"].get("optional_deadline_seconds", 900),
                optional_deadline_exhausted=payload["pipeline"].get("optional_deadline_exhausted", False),
            )
        if payload.get("generated_tests"):
            from verifypatch.generation import GeneratedTestResult, GeneratedTestsResult

            report.generated_tests = GeneratedTestsResult(
                seed=payload["generated_tests"].get("seed", 0),
                items=[GeneratedTestResult(**item) for item in payload["generated_tests"].get("items") or []],
            )
        if payload.get("mutation"):
            from verifypatch.mutation import MutantRecord, MutationResult, MutationSummary

            summary = MutationSummary(**payload["mutation"]["summary"])
            report.mutation = MutationResult(
                backend=payload["mutation"].get("backend"),
                backend_version=payload["mutation"].get("backend_version"),
                summary=summary,
                mutants=[MutantRecord(**item) for item in payload["mutation"].get("mutants") or []],
            )
        if payload.get("behavioral_comparison"):
            from verifypatch.behavior import BehaviorComparison, BehavioralResult

            report.behavioral_comparison = BehavioralResult(
                items=[BehaviorComparison(**item) for item in payload["behavioral_comparison"].get("items") or []]
            )
        result = evaluate_policy(report, cfg.policy, enforced=args.enforce)
        report.policy = result
        if report.schema_version != "1":
            report.schema_version = SCHEMA_VERSION_V2
            _promote_v2(report)
        json_out = Path(args.json_out) if args.json_out else Path(args.report)
        md_out = Path(args.md_out) if args.md_out else json_out.with_suffix(".md")
        code = _write(report, json_out, md_out)
        if code:
            return code
        if args.enforce and result.decision == "block":
            return 3
        return 0

    parser.error("unknown command")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
