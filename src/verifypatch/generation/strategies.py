from __future__ import annotations

from typing import Any


def hypothesis_available() -> bool:
    try:
        import hypothesis  # noqa: F401
    except ImportError:
        return False
    return True


def from_type_strategy(annotation: Any) -> Any:
    from hypothesis import strategies as st

    return st.from_type(annotation)
