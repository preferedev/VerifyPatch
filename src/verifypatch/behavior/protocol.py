from __future__ import annotations

import json
from typing import Any


JSON_TYPES = (type(None), bool, int, float, str, list, dict)


def is_json_value(value: Any) -> bool:
    if isinstance(value, (type(None), bool, int, float, str)):
        return True
    if isinstance(value, list):
        return all(is_json_value(item) for item in value)
    if isinstance(value, dict):
        return all(isinstance(k, str) and is_json_value(v) for k, v in value.items())
    return False


def preview(value: Any, limit: int = 500) -> str:
    try:
        text = json.dumps(value, default=str, ensure_ascii=False)
    except TypeError:
        text = repr(value)
    return text[:limit]


def normalize_exception(exc: BaseException) -> dict[str, str]:
    return {"type": type(exc).__name__, "message": str(exc)[:500]}
