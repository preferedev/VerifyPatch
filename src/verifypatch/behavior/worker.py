from __future__ import annotations

import importlib
import inspect
import json
import sys
from typing import Any

from verifypatch.behavior.protocol import is_json_value, normalize_exception, preview


def invoke(module_name: str, qualname: str, args: list[Any], kwargs: dict[str, Any]) -> dict[str, Any]:
    module = importlib.import_module(module_name)
    target: Any = module
    for part in qualname.split("."):
        target = getattr(target, part)
    if inspect.iscoroutinefunction(target) or inspect.isasyncgenfunction(target):
        raise TypeError("async targets are not supported")
    result = target(*args, **kwargs)
    if inspect.isgenerator(result) or inspect.iscoroutine(result) or inspect.isasyncgen(result):
        raise TypeError("non-serializable result")
    if not is_json_value(result):
        raise TypeError("non-serializable result")
    return {"ok": True, "value": result, "preview": preview(result)}


def main() -> int:
    raw = sys.stdin.read()
    request = json.loads(raw)
    try:
        payload = invoke(
            request["module"],
            request["qualname"],
            list(request.get("args") or []),
            dict(request.get("kwargs") or {}),
        )
    except Exception as exc:
        payload = {"ok": False, "error": normalize_exception(exc), "preview": preview(normalize_exception(exc))}
    sys.stdout.write(json.dumps(payload))
    sys.stdout.write("\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
