from __future__ import annotations

import os

import pytest

from verifypatch.requirements.model import ExtractionRequest, SourceSnapshot
from verifypatch.schema import load_schema

pytestmark = pytest.mark.live_provider


def _request() -> ExtractionRequest:
    return ExtractionRequest(
        sources=[
            SourceSnapshot(
                ref="live",
                path="README.md",
                start_line=1,
                end_line=1,
                text="Prices must never be negative.",
                digest="abc",
                kind="task",
            )
        ],
        schema=load_schema("requirements-v1"),
        model=os.environ.get("VERIFYPATCH_LIVE_MODEL") or "",
    )


def test_live_openai_structured_output():
    if not os.environ.get("OPENAI_API_KEY") or not os.environ.get("VERIFYPATCH_LIVE_MODEL"):
        pytest.skip("OPENAI_API_KEY and VERIFYPATCH_LIVE_MODEL required")
    from verifypatch.requirements.openai_provider import OpenAIProvider

    response = OpenAIProvider(model=os.environ["VERIFYPATCH_LIVE_MODEL"]).extract(_request())
    assert response.error_code != "model_required"
    assert response.constrained_output is True


def test_live_anthropic_structured_output():
    if not os.environ.get("ANTHROPIC_API_KEY") or not os.environ.get("VERIFYPATCH_LIVE_MODEL"):
        pytest.skip("ANTHROPIC_API_KEY and VERIFYPATCH_LIVE_MODEL required")
    from verifypatch.requirements.anthropic_provider import AnthropicProvider

    response = AnthropicProvider(model=os.environ["VERIFYPATCH_LIVE_MODEL"]).extract(_request())
    assert response.error_code != "model_required"
    assert response.constrained_output is True
