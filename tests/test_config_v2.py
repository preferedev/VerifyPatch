from __future__ import annotations

from pathlib import Path

import pytest

yaml = pytest.importorskip("yaml")

from verifypatch.config import ConfigError, load_v2_config, parse_v2_mapping, load_yaml_mapping


def test_default_v2_config_without_file(tmp_path: Path):
    cfg = load_v2_config(tmp_path)
    assert cfg.requirements.enabled is False
    assert cfg.generation.enabled is False
    assert cfg.mutation.enabled is False
    assert cfg.behavior.enabled is False
    assert cfg.policy.incomplete == "review"


def test_unknown_key_rejected(tmp_path: Path):
    path = tmp_path / "verifypatch.yml"
    path.write_text("version: 2\nunknown_top: 1\n", encoding="utf-8")
    with pytest.raises(ConfigError, match="unknown configuration key"):
        load_v2_config(tmp_path, path)


def test_duplicate_yaml_key_rejected(tmp_path: Path):
    path = tmp_path / "verifypatch.yml"
    path.write_text("version: 2\nversion: 2\n", encoding="utf-8")
    with pytest.raises(ConfigError, match="duplicate YAML key"):
        load_yaml_mapping(path)


def test_yaml_alias_bomb_rejected(tmp_path: Path):
    path = tmp_path / "verifypatch.yml"
    # Exponential alias expansion: each level doubles references.
    lines = ["a: &a []"]
    # Build a chain of aliases well above MAX_YAML_ALIASES.
    blob = "a: &a [x]\n"
    for i in range(40):
        blob += f"n{i}: &n{i} [*a, *a]\n"
        blob = blob.replace("*a", f"*n{i-1}" if i else "*a", 0)
    # Simpler: many explicit aliases
    text = "version: 2\nruntime:\n  artifacts_dir: &d artifacts\n"
    text += "\n".join(f"x{i}: *d" for i in range(40))
    path.write_text(text, encoding="utf-8")
    with pytest.raises(ConfigError, match="alias"):
        load_yaml_mapping(path)


def test_example_config_parses():
    root = Path(__file__).resolve().parents[1]
    cfg = load_v2_config(root, root / "verifypatch.example.yml")
    assert cfg.version == 2
    assert cfg.mutation.backend == "ast"
    assert cfg.mutation.fallback is None
    assert cfg.policy.review_on_findings


@pytest.mark.parametrize("value", [0, 0.0, 1, 1.0, 0.5])
def test_ratio_boundaries_accepted(value):
    cfg = parse_v2_mapping(
        {"version": 2, "policy": {"minimum_pr_untouched_changed_line_coverage": value}}
    )
    assert cfg.policy.minimum_pr_untouched_changed_line_coverage == float(value)


@pytest.mark.parametrize("value", [True, False, -0.01, 1.01, float("nan"), float("inf"), float("-inf"), "0.5"])
def test_ratio_rejected_values(value):
    with pytest.raises(ConfigError, match="finite number"):
        parse_v2_mapping(
            {"version": 2, "policy": {"minimum_pr_untouched_changed_line_coverage": value}}
        )


@pytest.mark.parametrize("value", ["block", "review", "not_evaluated", "pass"])
def test_incomplete_enum_accepted(value):
    cfg = parse_v2_mapping({"version": 2, "policy": {"incomplete": value}})
    assert cfg.policy.incomplete == value


def test_incomplete_enum_rejected():
    with pytest.raises(ConfigError, match="policy.incomplete"):
        parse_v2_mapping({"version": 2, "policy": {"incomplete": "warn"}})


def test_policy_mode_enforcing_rejected():
    with pytest.raises(ConfigError, match="policy.mode is obsolete"):
        parse_v2_mapping({"version": 2, "policy": {"mode": "enforcing"}})


def test_policy_mode_informational_rejected():
    with pytest.raises(ConfigError, match="policy.mode is obsolete"):
        parse_v2_mapping({"version": 2, "policy": {"mode": "informational"}})


def test_require_stages_known_name():
    cfg = parse_v2_mapping({"version": 2, "policy": {"require_stages": ["mutation"]}})
    assert cfg.policy.require_stages == ["mutation"]


def test_require_stages_duplicate_rejected():
    with pytest.raises(ConfigError, match="duplicate"):
        parse_v2_mapping({"version": 2, "policy": {"require_stages": ["mutation", "mutation"]}})


def test_require_stages_unknown_rejected():
    with pytest.raises(ConfigError, match="unsupported policy.require_stages"):
        parse_v2_mapping({"version": 2, "policy": {"require_stages": ["not-a-stage"]}})


def test_unknown_finding_id_rejected():
    with pytest.raises(ConfigError, match="unsupported policy.block_on_findings"):
        parse_v2_mapping({"version": 2, "policy": {"block_on_findings": ["NOT_A_FINDING"]}})


def test_yaml_nan_and_inf_thresholds_rejected(tmp_path: Path):
    path = tmp_path / "verifypatch.yml"
    path.write_text("version: 2\npolicy:\n  minimum_pr_untouched_changed_line_coverage: .nan\n", encoding="utf-8")
    with pytest.raises(ConfigError, match="finite number"):
        load_v2_config(tmp_path, path)
    path.write_text("version: 2\npolicy:\n  minimum_independent_mutation_score: .inf\n", encoding="utf-8")
    with pytest.raises(ConfigError, match="finite number"):
        load_v2_config(tmp_path, path)
