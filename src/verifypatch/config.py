from __future__ import annotations

import math
from dataclasses import dataclass, field, fields
from pathlib import Path
from typing import Any

from verifypatch.errors import AnalysisError
from verifypatch.limits import (
    DEFAULT_BEHAVIOR_TIMEOUT_SECONDS,
    DEFAULT_GENERATION_DEADLINE_MS,
    DEFAULT_GENERATION_EXEC_TIMEOUT_SECONDS,
    DEFAULT_GENERATION_SEED,
    DEFAULT_MUTATION_TIMEOUT_SECONDS,
    DEFAULT_OPTIONAL_TIMEOUT_SECONDS,
    DEFAULT_REQUIREMENTS_TIMEOUT_SECONDS,
    DEFAULT_TIMEOUT_SECONDS,
    MAX_BEHAVIOR_INPUTS_DEFAULT,
    MAX_EXAMPLES_DEFAULT,
    MAX_MUTANTS_DEFAULT,
    MAX_YAML_ALIASES,
    MAX_YAML_BYTES,
)
from verifypatch.toml import tomllib
from verifypatch.stage import STAGE_NAMES

DEFAULT_TEST_PATHS = ("tests",)
DEFAULT_BASE_SOURCES = (
    "README.md",
    "docs/**/*.md",
    "openapi.yaml",
    "schemas/**/*.json",
)
DEFAULT_REVIEW_FINDINGS = ("TEST_SKIP_ADDED", "TEST_XFAIL_ADDED", "ASSERT_TO_TRUTHY")
KNOWN_FINDING_IDS = (
    "TEST_SKIP_ADDED",
    "TEST_XFAIL_ADDED",
    "BROAD_EXCEPT_ADDED",
    "ASSERT_TO_TRUTHY",
    "TEST_REMOVED",
    "ASSERT_COUNT_DROP",
)
POLICY_INCOMPLETE_VALUES = ("block", "review", "not_evaluated", "pass")
DEFAULT_MUTATION_OPERATORS = ("comparison", "boolean", "arithmetic", "constants")


class ConfigError(AnalysisError):
    """Invalid v2 configuration."""


@dataclass
class VerifyPatchConfig:
    test_paths: list[str] = field(default_factory=lambda: list(DEFAULT_TEST_PATHS))
    test_globs: list[str] = field(default_factory=list)
    timeout_seconds: int = DEFAULT_TIMEOUT_SECONDS
    omit: list[str] = field(default_factory=list)


@dataclass
class RuntimeConfig:
    optional_timeout_seconds: int = DEFAULT_OPTIONAL_TIMEOUT_SECONDS
    artifacts_dir: str = ".verifypatch/artifacts"


@dataclass
class RequirementsConfig:
    enabled: bool = False
    provider: str = "openai"
    model: str | None = None
    task_files: list[str] = field(default_factory=list)
    base_sources: list[str] = field(default_factory=lambda: list(DEFAULT_BASE_SOURCES))
    minimum_confidence: str = "high"
    timeout_seconds: int = DEFAULT_REQUIREMENTS_TIMEOUT_SECONDS
    interface_stubs: bool = False


@dataclass
class GenerationConfig:
    enabled: bool = False
    max_examples: int = MAX_EXAMPLES_DEFAULT
    deadline_ms: int = DEFAULT_GENERATION_DEADLINE_MS
    timeout_seconds: int = DEFAULT_GENERATION_EXEC_TIMEOUT_SECONDS
    seed: int = DEFAULT_GENERATION_SEED


@dataclass
class MutationConfig:
    enabled: bool = False
    backend: str = "ast"
    fallback: str | None = None
    max_mutants: int = MAX_MUTANTS_DEFAULT
    timeout_seconds: int = DEFAULT_MUTATION_TIMEOUT_SECONDS
    per_mutant_timeout_seconds: int | str = "auto"
    workers: int = 1
    operators: list[str] = field(default_factory=lambda: list(DEFAULT_MUTATION_OPERATORS))
    exclude_ids: dict[str, str] = field(default_factory=dict)


@dataclass
class BehaviorTarget:
    callable: str
    inputs: list[dict[str, Any]] = field(default_factory=list)
    requirement_ids: list[str] = field(default_factory=list)


@dataclass
class BehaviorConfig:
    enabled: bool = False
    timeout_seconds: int = DEFAULT_BEHAVIOR_TIMEOUT_SECONDS
    max_inputs_per_target: int = MAX_BEHAVIOR_INPUTS_DEFAULT
    targets: list[BehaviorTarget] = field(default_factory=list)


@dataclass
class PolicyConfig:
    incomplete: str = "review"
    minimum_pr_untouched_changed_line_coverage: float | None = None
    minimum_independent_mutation_score: float | None = None
    block_on_findings: list[str] = field(default_factory=list)
    review_on_findings: list[str] = field(default_factory=lambda: list(DEFAULT_REVIEW_FINDINGS))
    block_on_deleted_tests: bool = False
    require_stages: list[str] = field(default_factory=list)
    block_on_generated_failures: bool = False
    block_on_potential_regressions: bool = False


@dataclass
class V2Config:
    version: int = 2
    runtime: RuntimeConfig = field(default_factory=RuntimeConfig)
    requirements: RequirementsConfig = field(default_factory=RequirementsConfig)
    generation: GenerationConfig = field(default_factory=GenerationConfig)
    mutation: MutationConfig = field(default_factory=MutationConfig)
    behavior: BehaviorConfig = field(default_factory=BehaviorConfig)
    policy: PolicyConfig = field(default_factory=PolicyConfig)
    source_path: Path | None = None
    pyproject_overrides: list[str] = field(default_factory=list)


def load_config(root: Path) -> VerifyPatchConfig:
    pyproject = root / "pyproject.toml"
    if not pyproject.is_file():
        return VerifyPatchConfig()
    data = tomllib.loads(pyproject.read_text(encoding="utf-8"))
    raw: dict[str, Any] = data.get("tool", {}).get("verifypatch", {})
    test_paths = list(raw.get("test_paths", DEFAULT_TEST_PATHS))
    test_globs = list(raw.get("test_globs", []))
    timeout = int(raw.get("timeout_seconds", DEFAULT_TIMEOUT_SECONDS))
    omit = list(raw.get("omit", []))
    return VerifyPatchConfig(
        test_paths=test_paths,
        test_globs=test_globs,
        timeout_seconds=timeout,
        omit=omit,
    )


def _field_names(cls: type) -> set[str]:
    return {item.name for item in fields(cls)}


def _reject_unknown(raw: dict[str, Any], allowed: set[str], prefix: str) -> None:
    extra = sorted(set(raw) - allowed)
    if extra:
        raise ConfigError(f"unknown configuration key {prefix + extra[0]!r}")


def _require_yaml() -> Any:
    try:
        import yaml
    except ImportError as exc:
        raise ConfigError(
            "PyYAML is required to load verifypatch.yml. Install verifypatch[v2] or PyYAML."
        ) from exc
    return yaml


class _StrictLoader:
    """yaml.SafeLoader that rejects duplicate keys and alias bombs."""

    def __init__(self, yaml_mod: Any) -> None:
        self.yaml = yaml_mod
        loader_cls = yaml_mod.SafeLoader

        class Strict(loader_cls):  # type: ignore[misc, valid-type]
            pass

        self.loader_cls = Strict
        self._patch()

    def _patch(self) -> None:
        def construct_mapping(loader: Any, node: Any, deep: bool = False) -> dict:
            mapping = {}
            for key_node, value_node in node.value:
                key = loader.construct_object(key_node, deep=deep)
                if key in mapping:
                    raise ConfigError(f"duplicate YAML key {key!r}")
                mapping[key] = loader.construct_object(value_node, deep=deep)
            return mapping

        self.loader_cls.construct_mapping = construct_mapping  # type: ignore[method-assign]

    def load(self, text: str) -> Any:
        return self.yaml.load(text, Loader=self.loader_cls)


def load_yaml_mapping(path: Path) -> dict[str, Any]:
    yaml_mod = _require_yaml()
    data = path.read_bytes()
    if len(data) > MAX_YAML_BYTES:
        raise ConfigError("verifypatch.yml exceeds the maximum allowed size")
    text = data.decode("utf-8")
    loader = yaml_mod.SafeLoader(text)
    aliases = 0
    while loader.check_event():
        event = loader.get_event()
        if event.__class__.__name__ == "AliasEvent":
            aliases += 1
            if aliases > MAX_YAML_ALIASES:
                raise ConfigError("YAML alias count exceeded conservative limit")
    loaded = _StrictLoader(yaml_mod).load(text)
    if loaded is None:
        return {}
    if not isinstance(loaded, dict):
        raise ConfigError("verifypatch.yml must be a mapping")
    return loaded


def _as_bool(value: Any, key: str) -> bool:
    if not isinstance(value, bool):
        raise ConfigError(f"{key} must be a boolean")
    return value


def _as_int(value: Any, key: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise ConfigError(f"{key} must be an integer")
    return value


def _as_str(value: Any, key: str) -> str:
    if not isinstance(value, str):
        raise ConfigError(f"{key} must be a string")
    return value


def _as_optional_str(value: Any, key: str) -> str | None:
    if value is None:
        return None
    return _as_str(value, key)


def _as_str_list(value: Any, key: str) -> list[str]:
    if not isinstance(value, list) or any(not isinstance(item, str) for item in value):
        raise ConfigError(f"{key} must be a list of strings")
    return list(value)


def _runtime_from(raw: dict[str, Any]) -> RuntimeConfig:
    _reject_unknown(raw, _field_names(RuntimeConfig), "runtime.")
    cfg = RuntimeConfig()
    if "optional_timeout_seconds" in raw:
        cfg.optional_timeout_seconds = _as_int(raw["optional_timeout_seconds"], "runtime.optional_timeout_seconds")
    if "artifacts_dir" in raw:
        cfg.artifacts_dir = _as_str(raw["artifacts_dir"], "runtime.artifacts_dir")
    return cfg


def _requirements_from(raw: dict[str, Any]) -> RequirementsConfig:
    _reject_unknown(raw, _field_names(RequirementsConfig), "requirements.")
    cfg = RequirementsConfig()
    if "enabled" in raw:
        cfg.enabled = _as_bool(raw["enabled"], "requirements.enabled")
    if "provider" in raw:
        cfg.provider = _as_str(raw["provider"], "requirements.provider")
    if "model" in raw:
        cfg.model = _as_optional_str(raw["model"], "requirements.model")
    if "task_files" in raw:
        cfg.task_files = _as_str_list(raw["task_files"], "requirements.task_files")
    if "base_sources" in raw:
        cfg.base_sources = _as_str_list(raw["base_sources"], "requirements.base_sources")
    if "minimum_confidence" in raw:
        cfg.minimum_confidence = _as_str(raw["minimum_confidence"], "requirements.minimum_confidence")
    if "timeout_seconds" in raw:
        cfg.timeout_seconds = _as_int(raw["timeout_seconds"], "requirements.timeout_seconds")
    if "interface_stubs" in raw:
        cfg.interface_stubs = _as_bool(raw["interface_stubs"], "requirements.interface_stubs")
    return cfg


def _generation_from(raw: dict[str, Any]) -> GenerationConfig:
    _reject_unknown(raw, _field_names(GenerationConfig), "generation.")
    cfg = GenerationConfig()
    if "enabled" in raw:
        cfg.enabled = _as_bool(raw["enabled"], "generation.enabled")
    if "max_examples" in raw:
        cfg.max_examples = _as_int(raw["max_examples"], "generation.max_examples")
    if "deadline_ms" in raw:
        cfg.deadline_ms = _as_int(raw["deadline_ms"], "generation.deadline_ms")
    if "timeout_seconds" in raw:
        cfg.timeout_seconds = _as_int(raw["timeout_seconds"], "generation.timeout_seconds")
    if "seed" in raw:
        cfg.seed = _as_int(raw["seed"], "generation.seed")
    return cfg


def _mutation_from(raw: dict[str, Any]) -> MutationConfig:
    _reject_unknown(raw, _field_names(MutationConfig), "mutation.")
    cfg = MutationConfig()
    if "enabled" in raw:
        cfg.enabled = _as_bool(raw["enabled"], "mutation.enabled")
    if "backend" in raw:
        cfg.backend = _as_str(raw["backend"], "mutation.backend")
    if "fallback" in raw:
        value = raw["fallback"]
        if value is None:
            cfg.fallback = None
        else:
            cfg.fallback = _as_str(value, "mutation.fallback")
            if cfg.fallback != "ast":
                raise ConfigError("mutation.fallback must be 'ast' or null")
    if "max_mutants" in raw:
        cfg.max_mutants = _as_int(raw["max_mutants"], "mutation.max_mutants")
    if "timeout_seconds" in raw:
        cfg.timeout_seconds = _as_int(raw["timeout_seconds"], "mutation.timeout_seconds")
    if "per_mutant_timeout_seconds" in raw:
        value = raw["per_mutant_timeout_seconds"]
        if value == "auto":
            cfg.per_mutant_timeout_seconds = "auto"
        else:
            cfg.per_mutant_timeout_seconds = _as_int(value, "mutation.per_mutant_timeout_seconds")
    if "workers" in raw:
        cfg.workers = _as_int(raw["workers"], "mutation.workers")
        if cfg.workers != 1:
            raise ConfigError("mutation.workers must be 1")
    if "operators" in raw:
        cfg.operators = _as_str_list(raw["operators"], "mutation.operators")
    if "exclude_ids" in raw:
        mapping = raw["exclude_ids"]
        if not isinstance(mapping, dict) or any(not isinstance(k, str) or not isinstance(v, str) for k, v in mapping.items()):
            raise ConfigError("mutation.exclude_ids must be a string-to-string mapping")
        cfg.exclude_ids = dict(mapping)
    return cfg


def _behavior_from(raw: dict[str, Any]) -> BehaviorConfig:
    _reject_unknown(raw, _field_names(BehaviorConfig), "behavior.")
    cfg = BehaviorConfig()
    if "enabled" in raw:
        cfg.enabled = _as_bool(raw["enabled"], "behavior.enabled")
    if "timeout_seconds" in raw:
        cfg.timeout_seconds = _as_int(raw["timeout_seconds"], "behavior.timeout_seconds")
    if "max_inputs_per_target" in raw:
        cfg.max_inputs_per_target = _as_int(raw["max_inputs_per_target"], "behavior.max_inputs_per_target")
    if "targets" in raw:
        if not isinstance(raw["targets"], list):
            raise ConfigError("behavior.targets must be a list")
        targets: list[BehaviorTarget] = []
        for index, item in enumerate(raw["targets"]):
            if not isinstance(item, dict):
                raise ConfigError(f"behavior.targets[{index}] must be a mapping")
            _reject_unknown(item, _field_names(BehaviorTarget), f"behavior.targets[{index}].")
            if "callable" not in item:
                raise ConfigError(f"behavior.targets[{index}].callable is required")
            target = BehaviorTarget(callable=_as_str(item["callable"], f"behavior.targets[{index}].callable"))
            if "inputs" in item:
                if not isinstance(item["inputs"], list):
                    raise ConfigError(f"behavior.targets[{index}].inputs must be a list")
                target.inputs = list(item["inputs"])
            if "requirement_ids" in item:
                target.requirement_ids = _as_str_list(
                    item["requirement_ids"], f"behavior.targets[{index}].requirement_ids"
                )
            targets.append(target)
        cfg.targets = targets
    return cfg


def _as_ratio(value: Any, key: str) -> float | None:
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ConfigError(f"{key} must be a finite number in [0.0, 1.0] or null")
    number = float(value)
    if not math.isfinite(number) or number < 0.0 or number > 1.0:
        raise ConfigError(f"{key} must be a finite number in [0.0, 1.0] or null")
    return number


def _policy_from(raw: dict[str, Any]) -> PolicyConfig:
    if "mode" in raw:
        raise ConfigError(
            "policy.mode is obsolete; --enforce is the sole switch that makes policy enforced"
        )
    _reject_unknown(raw, _field_names(PolicyConfig), "policy.")
    cfg = PolicyConfig()
    if "incomplete" in raw:
        cfg.incomplete = _as_str(raw["incomplete"], "policy.incomplete")
        if cfg.incomplete not in POLICY_INCOMPLETE_VALUES:
            raise ConfigError(
                "policy.incomplete must be one of: " + ", ".join(POLICY_INCOMPLETE_VALUES)
            )
    if "minimum_pr_untouched_changed_line_coverage" in raw:
        cfg.minimum_pr_untouched_changed_line_coverage = _as_ratio(
            raw["minimum_pr_untouched_changed_line_coverage"],
            "policy.minimum_pr_untouched_changed_line_coverage",
        )
    if "minimum_independent_mutation_score" in raw:
        cfg.minimum_independent_mutation_score = _as_ratio(
            raw["minimum_independent_mutation_score"],
            "policy.minimum_independent_mutation_score",
        )
    if "block_on_findings" in raw:
        cfg.block_on_findings = _as_str_list(raw["block_on_findings"], "policy.block_on_findings")
        extra = sorted(set(cfg.block_on_findings) - set(KNOWN_FINDING_IDS))
        if extra:
            raise ConfigError(f"unsupported policy.block_on_findings id {extra[0]!r}")
    if "review_on_findings" in raw:
        cfg.review_on_findings = _as_str_list(raw["review_on_findings"], "policy.review_on_findings")
        extra = sorted(set(cfg.review_on_findings) - set(KNOWN_FINDING_IDS))
        if extra:
            raise ConfigError(f"unsupported policy.review_on_findings id {extra[0]!r}")
    if "block_on_deleted_tests" in raw:
        cfg.block_on_deleted_tests = _as_bool(raw["block_on_deleted_tests"], "policy.block_on_deleted_tests")
    if "require_stages" in raw:
        cfg.require_stages = _as_str_list(raw["require_stages"], "policy.require_stages")
        if len(cfg.require_stages) != len(set(cfg.require_stages)):
            raise ConfigError("policy.require_stages must not contain duplicate stage names")
        unknown = [name for name in cfg.require_stages if name not in STAGE_NAMES]
        if unknown:
            raise ConfigError(f"unsupported policy.require_stages name {unknown[0]!r}")
    if "block_on_generated_failures" in raw:
        cfg.block_on_generated_failures = _as_bool(
            raw["block_on_generated_failures"], "policy.block_on_generated_failures"
        )
    if "block_on_potential_regressions" in raw:
        cfg.block_on_potential_regressions = _as_bool(
            raw["block_on_potential_regressions"], "policy.block_on_potential_regressions"
        )
    return cfg


def parse_v2_mapping(raw: dict[str, Any], source_path: Path | None = None) -> V2Config:
    _reject_unknown(
        raw,
        {"version", "runtime", "requirements", "generation", "mutation", "behavior", "policy"},
        "",
    )
    version = raw.get("version", 2)
    if version != 2:
        raise ConfigError("verifypatch.yml version must be 2")
    cfg = V2Config(source_path=source_path)
    if "runtime" in raw:
        if not isinstance(raw["runtime"], dict):
            raise ConfigError("runtime must be a mapping")
        cfg.runtime = _runtime_from(raw["runtime"])
    if "requirements" in raw:
        if not isinstance(raw["requirements"], dict):
            raise ConfigError("requirements must be a mapping")
        cfg.requirements = _requirements_from(raw["requirements"])
    if "generation" in raw:
        if not isinstance(raw["generation"], dict):
            raise ConfigError("generation must be a mapping")
        cfg.generation = _generation_from(raw["generation"])
    if "mutation" in raw:
        if not isinstance(raw["mutation"], dict):
            raise ConfigError("mutation must be a mapping")
        cfg.mutation = _mutation_from(raw["mutation"])
    if "behavior" in raw:
        if not isinstance(raw["behavior"], dict):
            raise ConfigError("behavior must be a mapping")
        cfg.behavior = _behavior_from(raw["behavior"])
    if "policy" in raw:
        if not isinstance(raw["policy"], dict):
            raise ConfigError("policy must be a mapping")
        cfg.policy = _policy_from(raw["policy"])
    return cfg


def load_v2_config(root: Path, config_path: Path | None = None) -> V2Config:
    path = config_path
    if path is None:
        default = root / "verifypatch.yml"
        if default.is_file():
            path = default
        else:
            return V2Config()
    if not path.is_file():
        raise ConfigError(f"configuration file not found: {path}")
    raw = load_yaml_mapping(path)
    cfg = parse_v2_mapping(raw, source_path=path)
    v1 = load_config(root)
    if v1.timeout_seconds != DEFAULT_TIMEOUT_SECONDS:
        cfg.pyproject_overrides.append("tool.verifypatch.timeout_seconds")
    return cfg


def apply_cli_overrides(cfg: V2Config, overrides: dict[str, Any]) -> V2Config:
    if overrides.get("requirements") is not None:
        cfg.requirements.enabled = bool(overrides["requirements"])
    if overrides.get("generate") is not None:
        cfg.generation.enabled = bool(overrides["generate"])
    if overrides.get("mutation") is not None:
        cfg.mutation.enabled = bool(overrides["mutation"])
    if overrides.get("behavior") is not None:
        cfg.behavior.enabled = bool(overrides["behavior"])
    if overrides.get("artifacts_dir"):
        cfg.runtime.artifacts_dir = str(overrides["artifacts_dir"])
    if overrides.get("optional_timeout") is not None:
        cfg.runtime.optional_timeout_seconds = int(overrides["optional_timeout"])
    return cfg
