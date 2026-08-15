from __future__ import annotations

from pathlib import Path

PROMPT_VERSION = "requirements-extract-v1"
_PROMPT_FILE = Path(__file__).with_name("prompts") / "extract_v1.txt"


def load_prompt(version: str = PROMPT_VERSION) -> str:
    if version != PROMPT_VERSION:
        raise ValueError(f"unknown prompt version {version!r}")
    return _PROMPT_FILE.read_text(encoding="utf-8")
