from __future__ import annotations

import configparser
import os
import shlex
from pathlib import Path

from verifypatch.errors import UnsupportedError
from verifypatch.toml import tomllib

DISABLED_XDIST_VALUES = {"0", "no", "false", "off"}


def _disabled(value: str) -> bool:
    return value.lower() in DISABLED_XDIST_VALUES


def _flag_value(token: str, prefix: str, index: int, tokens: list[str]) -> str | None:
    if token == prefix:
        if index + 1 < len(tokens) and not tokens[index + 1].startswith("-"):
            return tokens[index + 1]
        return ""
    if token.startswith(prefix + "="):
        return token.split("=", 1)[1]
    return None


def _tokens_indicate_xdist(tokens: list[str]) -> bool:
    for index, token in enumerate(tokens):
        if token.startswith("-n") and not token.startswith("--"):
            rest = token[2:]
            if rest.startswith("="):
                rest = rest[1:]
            if rest == "":
                nxt = tokens[index + 1] if index + 1 < len(tokens) else ""
                if nxt.startswith("-") or nxt == "":
                    return True
                if not _disabled(nxt):
                    return True
                continue
            if not _disabled(rest):
                return True
            continue
        for prefix in ("--numprocesses", "--dist", "--maxprocesses", "--max-worker-restart"):
            value = _flag_value(token, prefix, index, tokens)
            if value is None:
                continue
            if prefix == "--dist":
                if value == "":
                    return True
                return value.lower() not in DISABLED_XDIST_VALUES
            if prefix in {"--maxprocesses", "--max-worker-restart"}:
                return True
            if not _disabled(value):
                return True
        if "xdist" in token and "no:xdist" not in token and "no:pytest_xdist" not in token:
            return True
    return False


def parse_addopts(value: str | list[str] | None) -> list[str]:
    if value is None:
        return []
    if isinstance(value, list):
        return [str(item) for item in value]
    return shlex.split(str(value), posix=True)


def collect_pytest_addopts(root: Path, extra_args: list[str]) -> list[str]:
    tokens: list[str] = []
    env = os.environ.get("PYTEST_ADDOPTS")
    if env:
        tokens.extend(parse_addopts(env))
    pyproject = root / "pyproject.toml"
    if pyproject.is_file():
        data = tomllib.loads(pyproject.read_text(encoding="utf-8"))
        ini = data.get("tool", {}).get("pytest", {}).get("ini_options", {})
        tokens.extend(parse_addopts(ini.get("addopts")))
    for name in ("pytest.ini", "tox.ini", "setup.cfg"):
        path = root / name
        if not path.is_file():
            continue
        parser = configparser.ConfigParser()
        parser.read(path)
        for section in ("pytest", "tool:pytest"):
            if parser.has_section(section) and parser.has_option(section, "addopts"):
                tokens.extend(parse_addopts(parser.get(section, "addopts")))
    tokens.extend(extra_args)
    return tokens


def reject_xdist(root: Path, extra_args: list[str]) -> None:
    tokens = collect_pytest_addopts(root, extra_args)
    if _tokens_indicate_xdist(tokens):
        raise UnsupportedError(
            "pytest-xdist / distributed coverage is not supported in VerifyPatch v1. "
            "Remove -n/--dist from pytest arguments, PYTEST_ADDOPTS, and pytest configuration."
        )
