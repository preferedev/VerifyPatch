from __future__ import annotations

import ast
import difflib


class InvalidMutation(Exception):
    """The requested mutation could not be applied as a real semantic AST change."""


def parse_module(source: str) -> ast.AST:
    return ast.parse(source)


def semantic_dump(tree: ast.AST) -> str:
    return ast.dump(tree, include_attributes=False)


def mutation_is_semantic(original: str, mutated: str) -> tuple[bool, str]:
    """Return (ok, reason). ok means mutated source parses and the AST changed."""
    try:
        original_tree = parse_module(original)
    except SyntaxError as exc:
        return False, f"original source does not parse: {exc}"
    try:
        mutated_tree = parse_module(mutated)
    except SyntaxError as exc:
        return False, f"mutated source does not parse: {exc}"
    if semantic_dump(original_tree) == semantic_dump(mutated_tree):
        return False, "mutation did not change the semantic AST"
    return True, "ok"


def compact_diff(original: str, mutated: str, path: str) -> str:
    lines = list(
        difflib.unified_diff(
            original.splitlines(),
            mutated.splitlines(),
            fromfile=f"a/{path}",
            tofile=f"b/{path}",
            lineterm="",
            n=0,
        )
    )
    return "\n".join(lines[:80])


def offset_at(source: str, line: int, col1: int) -> int:
    """Convert 1-based line/column to a 0-based source offset."""
    if line < 1:
        return 0
    pos = 0
    current = 1
    while current < line:
        newline = source.find("\n", pos)
        if newline < 0:
            return len(source)
        pos = newline + 1
        current += 1
    return min(len(source), pos + max(col1 - 1, 0))


def linecol_at(source: str, offset: int) -> tuple[int, int]:
    """Convert a 0-based offset to 1-based (line, column)."""
    offset = max(0, min(offset, len(source)))
    line = source.count("\n", 0, offset) + 1
    last_nl = source.rfind("\n", 0, offset)
    col = offset + 1 if last_nl < 0 else offset - last_nl
    return line, col


def replace_span(source: str, start: tuple[int, int], end: tuple[int, int], new: str) -> str:
    begin = offset_at(source, start[0], start[1])
    stop = offset_at(source, end[0], end[1])
    if begin > stop:
        raise InvalidMutation("invalid source span")
    return source[:begin] + new + source[stop:]


def ast_span(node: ast.AST) -> tuple[tuple[int, int], tuple[int, int]]:
    lineno = getattr(node, "lineno", None)
    end_lineno = getattr(node, "end_lineno", lineno)
    col = getattr(node, "col_offset", 0)
    end_col = getattr(node, "end_col_offset", col)
    if lineno is None or end_lineno is None:
        raise InvalidMutation("AST node is missing source position")
    return (lineno, col + 1), (end_lineno, end_col + 1)
