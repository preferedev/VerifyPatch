from __future__ import annotations

from pathlib import Path

from verifypatch.config import PolicyConfig, V2Config, load_v2_config, parse_v2_mapping, load_yaml_mapping


def load_policy(root: Path, config_path: Path | None = None) -> PolicyConfig:
    cfg = load_v2_config(root, config_path)
    return cfg.policy


def policy_from_mapping(raw: dict) -> PolicyConfig:
    cfg = parse_v2_mapping({"version": 2, "policy": raw})
    return cfg.policy
