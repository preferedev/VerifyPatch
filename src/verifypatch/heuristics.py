from __future__ import annotations

import ast
from dataclasses import dataclass
from pathlib import Path

from verifypatch.gitops import FileDiff
from verifypatch.model import Finding, WarningRecord


COMPARE_OPS = (ast.Eq, ast.NotEq, ast.Is, ast.IsNot)


@dataclass
class TestFn:
    qname: str
    name: str
    lineno: int
    node: ast.AST
    source_segment: str


def _read(path: Path) -> str | None:
    try:
        return path.read_text(encoding="utf-8")
    except OSError:
        return None


def parse_module(path: Path) -> tuple[ast.AST | None, str | None, str | None]:
    source = _read(path)
    if source is None:
        return None, None, f"could not read {path}"
    try:
        return ast.parse(source), source, None
    except SyntaxError as exc:
        return None, source, f"syntax error in {path}: {exc.msg}"


def _is_test_function(name: str) -> bool:
    return name.startswith("test_")


def _is_test_class(name: str) -> bool:
    return name.startswith("Test")


def iter_test_functions(tree: ast.AST, source: str) -> list[TestFn]:
    found: list[TestFn] = []

    def add(qname: str, node: ast.FunctionDef | ast.AsyncFunctionDef) -> None:
        found.append(
            TestFn(
                qname=qname,
                name=node.name,
                lineno=node.lineno,
                node=node,
                source_segment=ast.get_source_segment(source, node) or "",
            )
        )

    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and _is_test_function(node.name):
            add(node.name, node)
        elif isinstance(node, ast.ClassDef) and _is_test_class(node.name):
            for child in node.body:
                if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)) and _is_test_function(
                    child.name
                ):
                    add(f"{node.name}::{child.name}", child)
    return found


def _attr_chain(node: ast.AST) -> list[str]:
    if isinstance(node, ast.Name):
        return [node.id]
    if isinstance(node, ast.Attribute):
        return _attr_chain(node.value) + [node.attr]
    return []


def _call_name(node: ast.AST) -> str:
    return ".".join(_attr_chain(node))


def _decorator_names(fn: ast.FunctionDef | ast.AsyncFunctionDef) -> list[str]:
    names = []
    for dec in fn.decorator_list:
        target = dec.func if isinstance(dec, ast.Call) else dec
        names.append(_call_name(target))
    return names


def _has_skip_decorator(fn: ast.FunctionDef | ast.AsyncFunctionDef) -> bool:
    for name in _decorator_names(fn):
        if name.endswith("mark.skip") or name.endswith("mark.skipif") or name in {
            "skip",
            "skipif",
        }:
            return True
    return False


def _has_xfail_decorator(fn: ast.FunctionDef | ast.AsyncFunctionDef) -> bool:
    for name in _decorator_names(fn):
        if name.endswith("mark.xfail") or name.endswith("xfail"):
            return True
    return False


def _calls_named(fn: ast.AST, names: set[str]) -> list[ast.Call]:
    found = []
    for node in ast.walk(fn):
        if isinstance(node, ast.Call):
            called = _call_name(node.func)
            if called in names or any(called.endswith("." + n) for n in names):
                found.append(node)
    return found


def _broad_excepts(fn: ast.AST) -> list[ast.ExceptHandler]:
    found = []
    for node in ast.walk(fn):
        if isinstance(node, ast.ExceptHandler):
            if node.type is None:
                found.append(node)
            elif isinstance(node.type, ast.Name) and node.type.id == "Exception":
                found.append(node)
    return found


def _direct_asserts(fn: ast.AST) -> list[ast.Assert]:
    return [node for node in ast.walk(fn) if isinstance(node, ast.Assert)]


def _is_equality_assert(node: ast.Assert) -> bool:
    test = node.test
    if isinstance(test, ast.Compare) and len(test.ops) == 1:
        return isinstance(test.ops[0], COMPARE_OPS)
    return False


def _is_bare_truthy_assert(node: ast.Assert) -> bool:
    test = node.test
    if isinstance(test, ast.Compare):
        return False
    return True


def _match_tests(base: list[TestFn], head: list[TestFn]) -> tuple[list[tuple[TestFn, TestFn]], list[TestFn], list[TestFn]]:
    head_by_q = {item.qname: item for item in head}
    matched = []
    removed = []
    used = set()
    for item in base:
        if item.qname in head_by_q:
            matched.append((item, head_by_q[item.qname]))
            used.add(item.qname)
        else:
            removed.append(item)
    added = [item for item in head if item.qname not in used]
    # conservative rename: only if exactly one unmatched on each side with unique names
    if len(removed) == 1 and len(added) == 1:
        matched.append((removed[0], added[0]))
        removed = []
        added = []
    return matched, removed, added


def analyze_test_file(
    path: str,
    base_text: str | None,
    head_text: str | None,
    warnings: list[WarningRecord],
) -> list[Finding]:
    findings: list[Finding] = []
    if base_text is None and head_text is None:
        return findings
    base_tree = head_tree = None
    base_err = head_err = None
    if base_text is not None:
        try:
            base_tree = ast.parse(base_text)
        except SyntaxError as exc:
            base_err = exc
    if head_text is not None:
        try:
            head_tree = ast.parse(head_text)
        except SyntaxError as exc:
            head_err = exc
    if base_err is not None or head_err is not None:
        warnings.append(
            WarningRecord(
                code="test_parse_failed",
                message=f"Could not parse {path} on {'base' if base_err else 'head'}; findings skipped.",
                path=path,
            )
        )
        return findings
    if base_tree is None or head_tree is None:
        # added or deleted file handled by TEST_REMOVED at caller for deletion
        if base_tree is not None and head_tree is None:
            for fn in iter_test_functions(base_tree, base_text or ""):
                findings.append(
                    Finding(
                        id="TEST_REMOVED",
                        severity="notice",
                        path=path,
                        line=fn.lineno,
                        test_node_id=fn.qname,
                        before=fn.source_segment,
                        after=None,
                        detail=f"Test {fn.qname} was removed.",
                    )
                )
        return findings

    base_fns = iter_test_functions(base_tree, base_text or "")
    head_fns = iter_test_functions(head_tree, head_text or "")
    matched, removed, _added = _match_tests(base_fns, head_fns)
    for fn in removed:
        findings.append(
            Finding(
                id="TEST_REMOVED",
                severity="notice",
                path=path,
                line=fn.lineno,
                test_node_id=fn.qname,
                before=fn.source_segment,
                after=None,
                detail=f"Test {fn.qname} can no longer be matched on HEAD.",
            )
        )
    for base_fn, head_fn in matched:
        b = base_fn.node
        h = head_fn.node
        assert isinstance(b, (ast.FunctionDef, ast.AsyncFunctionDef))
        assert isinstance(h, (ast.FunctionDef, ast.AsyncFunctionDef))
        if (not _has_skip_decorator(b) and _has_skip_decorator(h)) or (
            not _calls_named(b, {"pytest.skip", "skip"}) and _calls_named(h, {"pytest.skip", "skip"})
        ):
            findings.append(
                Finding(
                    id="TEST_SKIP_ADDED",
                    severity="review",
                    path=path,
                    line=head_fn.lineno,
                    test_node_id=head_fn.qname,
                    before=base_fn.source_segment,
                    after=head_fn.source_segment,
                    detail=f"Skip was added to {head_fn.qname}.",
                )
            )
        if (not _has_xfail_decorator(b) and _has_xfail_decorator(h)) or (
            not _calls_named(b, {"pytest.xfail", "xfail"})
            and _calls_named(h, {"pytest.xfail", "xfail"})
        ):
            findings.append(
                Finding(
                    id="TEST_XFAIL_ADDED",
                    severity="review",
                    path=path,
                    line=head_fn.lineno,
                    test_node_id=head_fn.qname,
                    before=base_fn.source_segment,
                    after=head_fn.source_segment,
                    detail=f"xfail was added to {head_fn.qname}.",
                )
            )
        if len(_broad_excepts(h)) > len(_broad_excepts(b)):
            findings.append(
                Finding(
                    id="BROAD_EXCEPT_ADDED",
                    severity="review",
                    path=path,
                    line=head_fn.lineno,
                    test_node_id=head_fn.qname,
                    before=base_fn.source_segment,
                    after=head_fn.source_segment,
                    detail=f"A bare except or except Exception was added in {head_fn.qname}.",
                )
            )
        base_asserts = _direct_asserts(b)
        head_asserts = _direct_asserts(h)
        if len(head_asserts) < len(base_asserts):
            findings.append(
                Finding(
                    id="ASSERT_COUNT_DROP",
                    severity="notice",
                    path=path,
                    line=head_fn.lineno,
                    test_node_id=head_fn.qname,
                    before=base_fn.source_segment,
                    after=head_fn.source_segment,
                    detail=(
                        f"Direct assert count dropped from {len(base_asserts)} to "
                        f"{len(head_asserts)} in {head_fn.qname}."
                    ),
                )
            )
        eq_base = [a for a in base_asserts if _is_equality_assert(a)]
        truthy_head = [a for a in head_asserts if _is_bare_truthy_assert(a)]
        if eq_base and truthy_head and len(eq_base) >= 1:
            # If an equality assert disappeared and a truthy assert appeared.
            if len([a for a in head_asserts if _is_equality_assert(a)]) < len(eq_base):
                findings.append(
                    Finding(
                        id="ASSERT_TO_TRUTHY",
                        severity="review",
                        path=path,
                        line=head_fn.lineno,
                        test_node_id=head_fn.qname,
                        before=base_fn.source_segment,
                        after=head_fn.source_segment,
                        detail=(
                            f"An equality/identity assertion in {head_fn.qname} "
                            "became a bare truthiness assertion."
                        ),
                    )
                )
    return findings


def git_show(root: Path, sha: str, path: str) -> str | None:
    import subprocess

    result = subprocess.run(
        ["git", "-C", str(root), "show", f"{sha}:{path}"],
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        return None
    return result.stdout


def collect_findings(
    root: Path,
    merge_base: str,
    head: str,
    files: list[FileDiff],
    is_test_path,
    warnings: list[WarningRecord],
) -> list[Finding]:
    findings: list[Finding] = []
    seen: set[tuple[str | None, str]] = set()
    for item in files:
        head_path = item.path
        base_path = item.old_path or item.path
        if not (is_test_path(head_path) or is_test_path(base_path)):
            continue
        key = (item.old_path, item.path)
        if key in seen:
            continue
        seen.add(key)
        if item.status == "deleted":
            base_text = git_show(root, merge_base, base_path)
            head_text = None
            report_path = base_path
        elif item.status == "renamed":
            base_text = git_show(root, merge_base, base_path)
            head_text = git_show(root, head, head_path)
            report_path = head_path
        else:
            base_text = git_show(root, merge_base, head_path)
            head_text = git_show(root, head, head_path)
            report_path = head_path
        findings.extend(analyze_test_file(report_path, base_text, head_text, warnings))
    return findings
