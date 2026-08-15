from __future__ import annotations

from verifypatch.config import BehaviorTarget, V2Config
from verifypatch.errors import AnalysisError


def validate_targets(config: V2Config) -> list[BehaviorTarget]:
    targets = []
    for target in config.behavior.targets:
        if ":" not in target.callable:
            raise AnalysisError(f"behavior target {target.callable!r} must be module:qualname")
        module, qual = target.callable.split(":", 1)
        if not module or not qual:
            raise AnalysisError(f"behavior target {target.callable!r} is invalid")
        if len(target.inputs) > config.behavior.max_inputs_per_target:
            raise AnalysisError(f"behavior target {target.callable} exceeds max_inputs_per_target")
        for index, item in enumerate(target.inputs):
            if not isinstance(item, dict):
                raise AnalysisError(f"{target.callable} inputs[{index}] must be a mapping")
            if "args" in item and not isinstance(item["args"], list):
                raise AnalysisError(f"{target.callable} inputs[{index}].args must be a list")
            if "kwargs" in item and not isinstance(item["kwargs"], dict):
                raise AnalysisError(f"{target.callable} inputs[{index}].kwargs must be a mapping")
        targets.append(target)
    return targets
