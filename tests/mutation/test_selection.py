from __future__ import annotations

from verifypatch.mutation import score
from verifypatch.mutation.backend import MutationSpec
from verifypatch.mutation.selection import cap_specs, filter_changed_lines, mutant_id


def _spec(path: str, line: int, occurrence: int = 1) -> MutationSpec:
    return MutationSpec(
        path=path,
        start_pos=(line, 1),
        end_pos=(line, 2),
        operator="comparison",
        occurrence=occurrence,
        original="Eq",
        mutated="NotEq",
    )


def test_filter_changed_lines():
    specs = [_spec("a.py", 3), _spec("a.py", 9), _spec("b.py", 1)]
    kept = filter_changed_lines(specs, {"a.py": {3, 4}})
    assert [item.start_pos[0] for item in kept] == [3]


def test_scores_exclude_timeout_invalid_error_not_run():
    assert score(2, 4) == 0.5
    assert score(0, 0) is None
    # timeouts are not in the denominator: valid_executed = killed + survived only
    assert score(1, 1) == 1.0


def test_deterministic_cap_order():
    specs = [_spec("a.py", i, i) for i in range(1, 20)]
    first = [mutant_id("abc", item) for item in cap_specs(specs, "abc", 5)]
    second = [mutant_id("abc", item) for item in cap_specs(specs, "abc", 5)]
    assert first == second
    assert len(first) == 5
