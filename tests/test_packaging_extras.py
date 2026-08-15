from __future__ import annotations

from pathlib import Path

try:
    import tomllib
except ModuleNotFoundError:  # pragma: no cover
    import tomli as tomllib


ROOT = Path(__file__).resolve().parents[1]


def test_optional_extras_are_independently_declared():
    data = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    extras = data["project"]["optional-dependencies"]
    openai_pkgs = {item.split(">")[0].split("=")[0] for item in extras["openai"]}
    anthropic_pkgs = {item.split(">")[0].split("=")[0] for item in extras["anthropic"]}
    generation_pkgs = {item.split(">")[0].split("=")[0] for item in extras["generation"]}
    mutation_pkgs = {item.split(">")[0].split("=")[0] for item in extras["mutation"]}
    assert openai_pkgs == {"openai"}
    assert anthropic_pkgs == {"anthropic"}
    assert generation_pkgs == {"hypothesis"}
    assert mutation_pkgs == {"cosmic-ray"}
    assert "openai" not in extras["anthropic"][0]
    assert "anthropic" not in extras["openai"][0]
    assert "hypothesis" not in extras["openai"][0]
    assert "cosmic-ray" not in extras["openai"][0]
    for name in ("openai", "anthropic", "generation", "mutation", "v2"):
        assert name in extras
        assert extras[name]
    anthropic = extras["anthropic"][0]
    assert anthropic.startswith("anthropic>=0.")
    assert "<1" in anthropic
    assert "anthropic>=1" not in anthropic
    v2 = extras["v2"]
    assert any(item.startswith("anthropic>=0.") for item in v2)
    assert not any(item == "anthropic>=1" or item.startswith("anthropic>=1,") for item in v2)
    assert extras["generation"] == ["hypothesis>=6"]
    assert extras["mutation"][0].startswith("cosmic-ray>=8.7")
    assert extras["openai"][0].startswith("openai>=1")


def test_package_data_excludes_pycache():
    data = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    excluded = data["tool"]["setuptools"]["exclude-package-data"]["*"]
    assert any("__pycache__" in item or "py[cod]" in item for item in excluded)


def test_package_version_is_release():
    data = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    assert data["project"]["version"] == "0.2.0"
    assert data["project"]["license"] == "Apache-2.0"


def test_license_is_spdx_expression():
    data = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    assert data["project"]["license"] == "Apache-2.0"
    assert data["project"]["license-files"] == ["LICENSE"]


def test_python_314_is_in_ci_matrix():
    text = (ROOT / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")
    assert '"3.14"' in text
