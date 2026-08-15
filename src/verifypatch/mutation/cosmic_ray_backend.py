from __future__ import annotations

from importlib.metadata import PackageNotFoundError, version
from pathlib import Path

from verifypatch.mutation.ast_backend import AstMutationBackend
from verifypatch.mutation.backend import MutationBackend, MutationSpec
from verifypatch.mutation.semantic import InvalidMutation, mutation_is_semantic
from verifypatch.stage import Reason

_CONSERVATIVE_COMPARISON = {
    "ReplaceComparisonOperator_Eq_NotEq",
    "ReplaceComparisonOperator_NotEq_Eq",
    "ReplaceComparisonOperator_Lt_LtE",
    "ReplaceComparisonOperator_LtE_Lt",
    "ReplaceComparisonOperator_Gt_GtE",
    "ReplaceComparisonOperator_GtE_Gt",
    "ReplaceComparisonOperator_Is_IsNot",
    "ReplaceComparisonOperator_IsNot_Is",
    "ReplaceComparisonOperator_In_NotIn",
    "ReplaceComparisonOperator_NotIn_In",
}
_CONSERVATIVE_ARITHMETIC = {
    "ReplaceBinaryOperator_Add_Sub",
    "ReplaceBinaryOperator_Sub_Add",
    "ReplaceBinaryOperator_Mul_Div",
    "ReplaceBinaryOperator_Div_Mul",
}
_BOOLEAN_OPERATORS = {
    "ReplaceTrueWithFalse",
    "ReplaceFalseWithTrue",
    "ReplaceAndWithOr",
    "ReplaceOrWithAnd",
}
_CONSTANT_OPERATORS = {
    "NumberReplacer",
}


def cosmic_ray_version() -> str | None:
    try:
        return version("cosmic-ray")
    except PackageNotFoundError:
        return None


def _allowlisted_names(allow: list[str]) -> list[str]:
    from cosmic_ray.plugins import operator_names

    selected: list[str] = []
    allow_set = set(allow)
    for name in operator_names():
        leaf = name.split("/", 1)[-1]
        if "comparison" in allow_set and leaf in _CONSERVATIVE_COMPARISON:
            selected.append(name)
        elif "arithmetic" in allow_set and leaf in _CONSERVATIVE_ARITHMETIC:
            selected.append(name)
        elif "boolean" in allow_set and leaf in _BOOLEAN_OPERATORS:
            selected.append(name)
        elif "constants" in allow_set and leaf in _CONSTANT_OPERATORS:
            selected.append(name)
    return selected


class _OccurrenceCollector:
    """Walk a Cosmic Ray/parso tree using the same visit-then-children order as MutationVisitor."""

    def __init__(self, operator) -> None:
        from cosmic_ray.ast import Visitor

        class Collector(Visitor):
            def __init__(self) -> None:
                self.sites: list[tuple[int, tuple, tuple]] = []
                self._count = 0

            def visit(self, node):
                for _index, pos in enumerate(operator.mutation_positions(node)):
                    start, end = pos
                    self.sites.append((self._count, start, end))
                    self._count += 1
                return node

        self._collector = Collector()

    def collect(self, tree) -> list[tuple[int, tuple, tuple]]:
        self._collector.walk(tree)
        return self._collector.sites


class CosmicRayBackend:
    name = "cosmic-ray"

    def __init__(self, operators: list[str] | None = None) -> None:
        import cosmic_ray  # noqa: F401  # required; ImportError is handled by load_backend

        self.operators = operators or ["comparison", "boolean", "arithmetic", "constants"]
        self.version = cosmic_ray_version() or "unknown"

    def list_mutations(self, root: Path, files: list[str]) -> list[MutationSpec]:
        from cosmic_ray.ast import get_ast
        from cosmic_ray.mutating import mutate_code
        from cosmic_ray.plugins import get_operator

        specs: list[MutationSpec] = []
        for rel in files:
            path = root / rel
            if not path.is_file():
                continue
            source = path.read_text(encoding="utf-8")
            try:
                tree = get_ast(source)
            except Exception as exc:
                raise RuntimeError(f"cosmic-ray failed to parse {rel}: {exc}") from exc
            for name in _allowlisted_names(self.operators):
                operator = get_operator(name)()
                sites = _OccurrenceCollector(operator).collect(tree)
                for occurrence, start, end in sites:
                    mutated = mutate_code(source, operator, occurrence)
                    if mutated is None:
                        continue
                    ok, _reason = mutation_is_semantic(source, mutated)
                    if not ok:
                        continue
                    specs.append(
                        MutationSpec(
                            path=rel,
                            start_pos=(int(start[0]), int(start[1])),
                            end_pos=(int(end[0]), int(end[1])),
                            operator=name,
                            occurrence=occurrence,
                            original="",
                            mutated="",
                            target_node=name.split("/", 1)[-1],
                        )
                    )
        return specs

    def apply(self, root: Path, spec: MutationSpec) -> None:
        from cosmic_ray.mutating import apply_mutation
        from cosmic_ray.plugins import get_operator

        path = root / spec.path
        operator = get_operator(spec.operator)()
        original, mutated = apply_mutation(path, operator, spec.occurrence)
        if mutated is None:
            raise InvalidMutation("cosmic-ray reported no mutation for this occurrence")
        ok, reason = mutation_is_semantic(original, mutated)
        if not ok:
            path.write_text(original, encoding="utf-8")
            raise InvalidMutation(reason)
        spec.original = original
        spec.mutated = mutated


def load_backend(name: str, operators: list[str], fallback: str | None = None) -> MutationBackend | Reason:
    if name in {"cosmic-ray", "cosmic_ray"}:
        try:
            import cosmic_ray  # noqa: F401
        except ImportError:
            if fallback == "ast":
                return AstMutationBackend(operators)
            return Reason(
                code="missing_dependency",
                message="cosmic-ray is not installed; install verifypatch[mutation] or set mutation.backend: ast",
            )
        return CosmicRayBackend(operators)
    if name == "ast":
        return AstMutationBackend(operators)
    return Reason(code="unknown_backend", message=f"unknown mutation backend {name!r}")
