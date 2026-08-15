from __future__ import annotations

from typing import Any

from verifypatch.requirements.model import ExtractionRequest, ProviderResponse
from verifypatch.requirements.prompts import load_prompt
from verifypatch.requirements.providers import MissingProviderDependency, classify_provider_error
from verifypatch.schema import load_schema


class AnthropicProvider:
    name = "anthropic"

    def __init__(self, model: str | None = None, client: Any | None = None) -> None:
        self.model = model
        self._client = client
        if client is None:
            try:
                import anthropic  # noqa: F401
            except ImportError as exc:
                raise MissingProviderDependency(
                    "The anthropic extra is not installed. Install verifypatch[anthropic] or verifypatch[v2]."
                ) from exc

    def _client_or_default(self) -> Any:
        if self._client is not None:
            return self._client
        from anthropic import Anthropic

        return Anthropic()

    def extract(self, request: ExtractionRequest) -> ProviderResponse:
        if not self.model:
            return ProviderResponse(
                payload={},
                provider=self.name,
                model="",
                constrained_output=True,
                error_code="model_required",
                error_message="requirements.model must be configured; VerifyPatch does not choose a default model.",
            )
        from verifypatch.requirements.firewall import delimit_sources

        schema = request.schema or load_schema("requirements-v1")
        prompt = load_prompt(request.prompt_version)
        user = delimit_sources(request.sources)
        client = self._client_or_default()
        try:
            response = client.messages.create(
                model=self.model,
                max_tokens=4096,
                system=prompt,
                messages=[{"role": "user", "content": user}],
                output_config={
                    "format": {
                        "type": "json_schema",
                        "schema": schema,
                    }
                },
            )
        except Exception as exc:
            return ProviderResponse(
                payload={},
                provider=self.name,
                model=self.model,
                constrained_output=True,
                error_code=classify_provider_error(exc),
                error_message=str(exc)[:500],
            )
        truncated = getattr(response, "stop_reason", None) == "max_tokens"
        request_id = getattr(response, "id", None)
        refusal = _anthropic_refusal(response)
        payload = _anthropic_payload(response)
        return ProviderResponse(
            payload=payload,
            provider=self.name,
            model=self.model,
            request_id=request_id,
            constrained_output=True,
            truncated=truncated,
            refused=refusal is not None,
            refusal_message=refusal,
        )


def _anthropic_refusal(response: Any) -> str | None:
    for block in getattr(response, "content", []) or []:
        if getattr(block, "type", None) == "refusal":
            return str(getattr(block, "refusal", "refused"))
    return None


def _anthropic_payload(response: Any) -> dict:
    import json

    parsed = getattr(response, "parsed_output", None)
    if isinstance(parsed, dict):
        return parsed
    for block in getattr(response, "content", []) or []:
        text = getattr(block, "text", None)
        if not text:
            continue
        try:
            loaded = json.loads(text)
        except json.JSONDecodeError:
            continue
        if isinstance(loaded, dict):
            return loaded
    return {}
