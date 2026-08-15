from __future__ import annotations

from verifypatch.requirements.openai_provider import OpenAIProvider
from verifypatch.requirements.anthropic_provider import AnthropicProvider
from verifypatch.requirements.model import ExtractionRequest, SourceSnapshot
from verifypatch.schema import load_schema


class _FakeOpenAI:
    def __init__(self, payload: str, refusal: bool = False, truncated: bool = False, error: Exception | None = None) -> None:
        self.payload = payload
        self.refusal = refusal
        self.truncated = truncated
        self.error = error
        self.last_kwargs = None

    @property
    def responses(self):
        return self

    def create(self, **kwargs):
        self.last_kwargs = kwargs
        if self.error:
            raise self.error
        assert kwargs["text"]["format"]["type"] == "json_schema"
        assert kwargs["text"]["format"]["strict"] is True
        assert kwargs["text"]["format"]["name"] == "verifypatch_requirements"
        assert "schema" in kwargs["text"]["format"]
        assert kwargs["model"]

        class Content:
            type = "refusal" if self.refusal else "output_text"
            refusal = "nope"
            text = self.payload

        class Item:
            content = [Content()]

        class Resp:
            output = [Item()]
            output_text = self.payload
            id = "req_123"
            incomplete_details = {} if self.truncated else None
            status = "incomplete" if self.truncated else "completed"

        return Resp()


class _FakeAnthropic:
    def __init__(self, payload: str, truncated: bool = False, error: Exception | None = None) -> None:
        self.payload = payload
        self.truncated = truncated
        self.error = error
        self.last_kwargs = None

    @property
    def messages(self):
        return self

    def create(self, **kwargs):
        self.last_kwargs = kwargs
        if self.error:
            raise self.error
        assert "output_config" in kwargs
        assert kwargs["output_config"]["format"]["type"] == "json_schema"
        assert "schema" in kwargs["output_config"]["format"]
        assert "extra_body" not in kwargs or "output_format" not in (kwargs.get("extra_body") or {})
        assert kwargs["model"] == "claude"

        class Block:
            type = "text"
            text = self.payload

        class Resp:
            content = [Block()]
            id = "msg_123"
            stop_reason = "max_tokens" if self.truncated else "end_turn"

        return Resp()


def _request() -> ExtractionRequest:
    return ExtractionRequest(
        sources=[
            SourceSnapshot(
                ref="s",
                path="README.md",
                start_line=1,
                end_line=1,
                text="must never be negative",
                digest="abc",
                kind="task",
            )
        ],
        schema=load_schema("requirements-v1"),
        model="test-model",
    )


def test_openai_uses_constrained_output():
    client = _FakeOpenAI('{"schema_version":"1","prompt_version":"requirements-extract-v1","items":[]}')
    provider = OpenAIProvider(model="test-model", client=client)
    response = provider.extract(_request())
    assert response.constrained_output is True
    assert response.request_id == "req_123"
    assert response.payload["items"] == []
    assert client.last_kwargs["text"]["format"]["type"] == "json_schema"


def test_openai_model_required():
    provider = OpenAIProvider(model=None, client=_FakeOpenAI("{}"))
    response = provider.extract(_request())
    assert response.error_code == "model_required"


def test_openai_does_not_select_a_model():
    provider = OpenAIProvider(model="", client=_FakeOpenAI("{}"))
    response = provider.extract(_request())
    assert response.error_code == "model_required"


def test_anthropic_uses_output_config_json_schema():
    client = _FakeAnthropic('{"schema_version":"1","prompt_version":"requirements-extract-v1","items":[]}')
    provider = AnthropicProvider(model="claude", client=client)
    response = provider.extract(_request())
    assert response.constrained_output is True
    assert client.last_kwargs["output_config"]["format"]["type"] == "json_schema"
    assert client.last_kwargs["model"] == "claude"


def test_anthropic_truncated():
    provider = AnthropicProvider(model="claude", client=_FakeAnthropic("{}", truncated=True))
    response = provider.extract(_request())
    assert response.truncated is True


def test_openai_malformed_payload():
    provider = OpenAIProvider(model="m", client=_FakeOpenAI("not-json"))
    response = provider.extract(_request())
    assert response.payload == {}


def test_openai_timeout_is_not_trusted():
    client = _FakeOpenAI("{}", error=TimeoutError("timed out"))
    provider = OpenAIProvider(model="test-model", client=client)
    response = provider.extract(_request())
    assert response.error_code == "timeout"
    assert response.payload == {}


def test_anthropic_timeout_is_not_trusted():
    client = _FakeAnthropic("{}", error=TimeoutError("timed out"))
    provider = AnthropicProvider(model="claude", client=client)
    response = provider.extract(_request())
    assert response.error_code == "timeout"
    assert response.payload == {}
