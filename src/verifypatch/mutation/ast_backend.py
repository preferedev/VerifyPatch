from __future__ import annotations

import ast
import sys
from pathlib import Path

from verifypatch.mutation.backend import MutationSpec
from verifypatch.mutation.semantic import (
    InvalidMutation,
    ast_span,
    linecol_at,
    mutation_is_semantic,
    offset_at,
    replace_span,
)


_COMPARE_TOKENS: dict[type[ast.cmpop], tuple[str, str]] = {
    ast.Eq: ("==", "!="),
    ast.NotEq: ("!=", "=="),
    ast.Lt: ("<", "<="),
    ast.LtE: ("<=", "<"),
    ast.Gt: (">", ">="),
    ast.GtE: (">=", ">"),
    ast.Is: ("is", "is not"),
    ast.IsNot: ("is not", "is"),
    ast.In: ("in", "not in"),
    ast.NotIn: ("not in", "in"),
}

_ARITH_TOKENS: dict[type[ast.operator], tuple[str, str]] = {
    ast.Add: ("+", "-"),
    ast.Sub: ("-", "+"),
    ast.Mult: ("*", "/"),
    ast.Div: ("/", "*"),
    ast.FloorDiv: ("//", "/"),
    ast.Mod: ("%", "*"),
}


def _preorder(node: ast.AST):
    yield node
    for child in ast.iter_child_nodes(node):
        yield from _preorder(child)


def _token_span(source: str, begin: int, end: int, token: str) -> tuple[tuple[int, int], tuple[int, int]] | None:
    chunk = source[begin:end]
    index = chunk.find(token)
    if index < 0:
        return None
    start = begin + index
    stop = start + len(token)
    return linecol_at(source, start), linecol_at(source, stop)


class AstMutationBackend:
    """Conservative source-span operators with shared enumeration/application identity."""

    name = "ast"
    version = f"python-{sys.version_info.major}.{sys.version_info.minor}"

    def __init__(self, operators: list[str] | None = None) -> None:
        self.operators = set(operators or ("comparison", "boolean", "arithmetic", "constants"))

    def list_mutations(self, root: Path, files: list[str]) -> list[MutationSpec]:
        specs: list[MutationSpec] = []
        for rel in files:
            path = root / rel
            if not path.is_file():
                continue
            source = path.read_text(encoding="utf-8")
            try:
                tree = ast.parse(source)
            except SyntaxError:
                continue
            specs.extend(self._sites(rel, source, tree))
        return specs

    def apply(self, root: Path, spec: MutationSpec) -> None:
        path = root / spec.path
        original = path.read_text(encoding="utf-8")
        try:
            tree = ast.parse(original)
        except SyntaxError as exc:
            raise InvalidMutation(f"original source does not parse: {exc}") from exc
        match = None
        for site in self._sites(spec.path, original, tree):
            if (
                site.operator == spec.operator
                and site.occurrence == spec.occurrence
                and site.start_pos == spec.start_pos
                and site.end_pos == spec.end_pos
                and site.target_node == spec.target_node
            ):
                match = site
                break
        if match is None:
            raise InvalidMutation("mutation identity did not match any AST site")
        mutated = replace_span(original, match.start_pos, match.end_pos, match.mutated)
        ok, reason = mutation_is_semantic(original, mutated)
        if not ok:
            raise InvalidMutation(reason)
        path.write_text(mutated, encoding="utf-8")

    def _sites(self, rel: str, source: str, tree: ast.AST) -> list[MutationSpec]:
        specs: list[MutationSpec] = []
        occurrence = {"comparison": 0, "boolean": 0, "arithmetic": 0, "constants": 0}
        for node in _preorder(tree):
            if "comparison" in self.operators and isinstance(node, ast.Compare):
                left: ast.expr = node.left
                for op, comparator in zip(node.ops, node.comparators):
                    pair = _COMPARE_TOKENS.get(type(op))
                    if pair is None:
                        left = comparator
                        continue
                    original_tok, mutated_tok = pair
                    begin = offset_at(
                        source,
                        getattr(left, "end_lineno", left.lineno),
                        getattr(left, "end_col_offset", 0) + 1,
                    )
                    end = offset_at(source, comparator.lineno, comparator.col_offset + 1)
                    span = _token_span(source, begin, end, original_tok)
                    if span is None:
                        left = comparator
                        continue
                    occurrence["comparison"] += 1
                    specs.append(
                        MutationSpec(
                            path=rel,
                            start_pos=span[0],
                            end_pos=span[1],
                            operator="comparison",
                            occurrence=occurrence["comparison"],
                            original=original_tok,
                            mutated=mutated_tok,
                            target_node=f"Compare.{type(op).__name__}",
                        )
                    )
                    left = comparator
            if "boolean" in self.operators and isinstance(node, ast.UnaryOp) and isinstance(node.op, ast.Not):
                operand = node.operand
                start, _ = ast_span(node)
                op_end = (operand.lineno, operand.col_offset + 1)
                begin = offset_at(source, start[0], start[1])
                end = offset_at(source, op_end[0], op_end[1])
                token = source[begin:end]
                if "not" not in token:
                    continue
                occurrence["boolean"] += 1
                specs.append(
                    MutationSpec(
                        path=rel,
                        start_pos=start,
                        end_pos=op_end,
                        operator="boolean",
                        occurrence=occurrence["boolean"],
                        original=token,
                        mutated="",
                        target_node="UnaryOp.Not",
                    )
                )
            if "arithmetic" in self.operators and isinstance(node, ast.BinOp):
                pair = _ARITH_TOKENS.get(type(node.op))
                if pair is not None:
                    original_tok, mutated_tok = pair
                    begin = offset_at(
                        source,
                        getattr(node.left, "end_lineno", node.left.lineno),
                        getattr(node.left, "end_col_offset", 0) + 1,
                    )
                    end = offset_at(source, node.right.lineno, node.right.col_offset + 1)
                    span = _token_span(source, begin, end, original_tok)
                    if span is not None:
                        occurrence["arithmetic"] += 1
                        specs.append(
                            MutationSpec(
                                path=rel,
                                start_pos=span[0],
                                end_pos=span[1],
                                operator="arithmetic",
                                occurrence=occurrence["arithmetic"],
                                original=original_tok,
                                mutated=mutated_tok,
                                target_node=f"BinOp.{type(node.op).__name__}",
                            )
                        )
            if "constants" in self.operators and isinstance(node, ast.Constant):
                value = node.value
                if isinstance(value, bool):
                    new_value = not value
                elif isinstance(value, int) and not isinstance(value, bool):
                    new_value = value + 1
                else:
                    continue
                start, end = ast_span(node)
                occurrence["constants"] += 1
                specs.append(
                    MutationSpec(
                        path=rel,
                        start_pos=start,
                        end_pos=end,
                        operator="constants",
                        occurrence=occurrence["constants"],
                        original=source[offset_at(source, start[0], start[1]) : offset_at(source, end[0], end[1])],
                        mutated=repr(new_value),
                        target_node="Constant",
                    )
                )
        return specs
