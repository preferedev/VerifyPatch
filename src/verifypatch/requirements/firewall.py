from __future__ import annotations

import ast
import fnmatch
from pathlib import Path

from verifypatch.artifacts import sha256_text
from verifypatch.config import V2Config
from verifypatch.gitops import git_ls_tree, git_show
from verifypatch.limits import MAX_PROMPT_CHARS, MAX_SOURCE_FILE_BYTES, MAX_SOURCE_FILES
from verifypatch.requirements.model import SourceSnapshot
from verifypatch.stage import Reason

DISALLOWED_SOURCE_KINDS = {
    "head_body",
    "pr_touched_test",
    "coverage",
    "mutation",
    "behavior",
    "secret",
}


def _digest_lines(text: str) -> str:
    return sha256_text(text)


def snapshot_from_text(ref: str, path: str, text: str, kind: str) -> SourceSnapshot:
    lines = text.splitlines() or [""]
    return SourceSnapshot(
        ref=ref,
        path=path,
        start_line=1,
        end_line=len(lines),
        text=text,
        digest=_digest_lines(text),
        kind=kind,
    )


def _safe_relpath(path: str) -> str | None:
    normalized = path.replace("\\", "/")
    if normalized.startswith("/") or normalized.startswith("~") or ".." in Path(normalized).parts:
        return None
    if normalized.startswith(".git/"):
        return None
    return normalized


def load_merge_base_sources(
    root: Path,
    merge_base: str,
    config: V2Config,
    pr_touched_tests: set[str],
) -> tuple[list[SourceSnapshot], Reason | None]:
    snapshots: list[SourceSnapshot] = []
    try:
        tracked = git_ls_tree(root, merge_base)
    except Exception:
        return snapshots, Reason(code="git_error", message="could not list merge-base sources")
    wanted: list[tuple[str, str]] = []
    for pattern in config.requirements.task_files:
        safe = _safe_relpath(pattern)
        if safe:
            wanted.append((safe, "task"))
    for pattern in config.requirements.base_sources:
        safe = _safe_relpath(pattern)
        if not safe:
            continue
        if any(ch in safe for ch in "*?["):
            for path in tracked:
                if fnmatch.fnmatch(path, safe):
                    wanted.append((path, "base_source"))
        else:
            wanted.append((safe, "base_source"))

    seen: set[str] = set()
    for path, kind in wanted:
        if path in seen:
            continue
        seen.add(path)
        if path in pr_touched_tests:
            continue
        text = git_show(root, merge_base, path)
        if text is None:
            continue
        encoded = text.encode("utf-8")
        if len(encoded) > MAX_SOURCE_FILE_BYTES:
            text = encoded[:MAX_SOURCE_FILE_BYTES].decode("utf-8", errors="replace")
        snapshots.append(snapshot_from_text(merge_base, path, text, kind))
        if len(snapshots) >= MAX_SOURCE_FILES:
            break
    return snapshots, None


def public_signatures(root: Path, merge_base: str, paths: list[str]) -> list[SourceSnapshot]:
    snapshots: list[SourceSnapshot] = []
    for path in paths:
        text = git_show(root, merge_base, path)
        if not text or not path.endswith(".py"):
            continue
        try:
            tree = ast.parse(text)
        except SyntaxError:
            continue
        lines = text.splitlines()
        chunks: list[str] = []
        for node in tree.body:
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                end = getattr(node, "end_lineno", node.lineno) or node.lineno
                # signature/docstring only: up to first body statement after docstring
                sig_end = node.lineno
                body = list(node.body)
                if body and isinstance(body[0], ast.Expr) and isinstance(getattr(body[0], "value", None), ast.Constant):
                    sig_end = getattr(body[0], "end_lineno", body[0].lineno) or body[0].lineno
                else:
                    sig_end = min(sig_end + 3, end)
                chunk = "\n".join(lines[node.lineno - 1 : sig_end])
                chunks.append(chunk)
        if chunks:
            blob = "\n\n".join(chunks)
            snapshots.append(snapshot_from_text(merge_base, path, blob, "signature"))
    return snapshots


def interface_stub(root: Path, head: str, path: str) -> SourceSnapshot | None:
    text = git_show(root, head, path)
    if not text:
        return None
    try:
        tree = ast.parse(text)
    except SyntaxError:
        return None
    parts: list[str] = []
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            args = ast.unparse(node.args) if hasattr(ast, "unparse") else ""
            deco = ""
            parts.append(f"def {node.name}({args}): ...")
            if node.returns is not None and hasattr(ast, "unparse"):
                parts[-1] = f"def {node.name}({args}) -> {ast.unparse(node.returns)}: ..."
            if node.body and isinstance(node.body[0], ast.Expr) and isinstance(getattr(node.body[0], "value", None), ast.Constant):
                parts.append(repr(node.body[0].value.value))
        elif isinstance(node, ast.ClassDef):
            parts.append(f"class {node.name}: ...")
    if not parts:
        return None
    blob = "\n".join(parts)
    return snapshot_from_text(head, path, blob, "interface_stub")


def has_specification_signal(sources: list[SourceSnapshot]) -> bool:
    if not sources:
        return False
    keywords = (
        "must",
        "should",
        "invariant",
        "never",
        "between",
        "example",
        "schema",
        "assert",
        "require",
        "bounds",
        "valid",
        "reject",
    )
    for source in sources:
        lowered = source.text.lower()
        if any(word in lowered for word in keywords):
            return True
        if source.path.endswith((".json", ".yaml", ".yml")) and source.text.strip():
            return True
    return False


def delimit_sources(sources: list[SourceSnapshot]) -> str:
    blocks = []
    for source in sources:
        blocks.append(
            "\n".join(
                [
                    f"<source kind={source.kind!r} ref={source.ref!r} path={source.path!r} "
                    f"lines={source.start_line}-{source.end_line} digest={source.digest}>",
                    source.text,
                    "</source>",
                ]
            )
        )
    blob = "\n\n".join(blocks)
    if len(blob) > MAX_PROMPT_CHARS:
        blob = blob[:MAX_PROMPT_CHARS]
    return blob


def cited_range_text(source: SourceSnapshot, start: int, end: int) -> str | None:
    """Return the exact cited lines, or None if the range is not ordered and in-bounds.

    Line numbers are 1-based and inclusive. The returned text is those lines joined
    by a single newline with no extra trailing newline after the last cited line.
    """
    if isinstance(start, bool) or isinstance(end, bool):
        return None
    if not isinstance(start, int) or not isinstance(end, int):
        return None
    if start < 1 or end < 1 or end < start:
        return None
    if start < source.start_line or end > source.end_line:
        return None
    lines = source.text.splitlines() or [""]
    rel_start = start - source.start_line
    rel_end = end - source.start_line + 1
    if rel_start < 0 or rel_end > len(lines):
        return None
    return "\n".join(lines[rel_start:rel_end])


def cited_range_digest(source: SourceSnapshot, start: int, end: int) -> str | None:
    """SHA-256 hex digest of the exact cited line range, or None if invalid."""
    cited = cited_range_text(source, start, end)
    if cited is None:
        return None
    return sha256_text(cited)


def citation_matches(
    source: SourceSnapshot,
    ref: str,
    path: str,
    start: int,
    end: int,
    digest: str,
) -> bool:
    """True only when ref, path, ordered in-bounds range, and range digest all match.

    ``digest`` is the SHA-256 of the exact cited line range, not the whole snapshot.
    ``source.digest`` authenticates the full snapshot text and must not be reused
    as a citation digest unless the cited range is that entire snapshot text.
    """
    if source.ref != ref:
        return False
    if source.path != path:
        return False
    expected = cited_range_digest(source, start, end)
    if expected is None or not digest:
        return False
    return expected == digest


def citations_match_sources(sources: list[SourceSnapshot], citations: list) -> bool:
    if not citations:
        return False
    for cite in citations:
        matched = any(
            citation_matches(
                source,
                cite.ref,
                cite.path,
                cite.start_line,
                cite.end_line,
                cite.digest,
            )
            for source in sources
        )
        if not matched:
            return False
    return True
