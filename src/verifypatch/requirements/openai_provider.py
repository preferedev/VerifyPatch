from __future__ import annotations

from typing import Any

from verifypatch.requirements.model import ExtractionRequest, ProviderResponse
from verifypatch.requirements.prompts import load_prompt
from verifypatch.requirements.providers import MissingProviderDependency, classify_provider_error
from verifypatch.schema import load_schema


class OpenAIProvider:
    name = "openai"

    def __init__(self, model: str | None = None, client: Any | None = None) -> None:
        self.model = model
        self._client = client
        if client is None:
            try:
                import openai  # noqa: F401
            except ImportError as exc:
                raise MissingProviderDependency(
                    "The openai extra is not installed. Install verifypatch[openai] or verifypatch[v2]."
                ) from exc

    def _client_or_default(self) -> Any:
        if self._client is not None:
            return self._client
        from openai import OpenAI

        return OpenAI()

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
            response = client.responses.create(
                model=self.model,
                input=[
                    {"role": "system", "content": prompt},
                    {"role": "user", "content": user},
                ],
                text={
                    "format": {
                        "type": "json_schema",
                        "name": "verifypatch_requirements",
                        "strict": True,
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
        truncated = bool(getattr(response, "incomplete_details", None)) or getattr(response, "status", None) == "incomplete"
        request_id = getattr(response, "id", None)
        refusal = _openai_refusal(response)
        payload = _openai_payload(response)
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


def _openai_refusal(response: Any) -> str | None:
    output = getattr(response, "output", None) or []
    for item in output:
        for content in getattr(item, "content", []) or []:
            if getattr(content, "type", None) == "refusal":
                return str(getattr(content, "refusal", "refused"))
    return None


def _openai_payload(response: Any) -> dict:
    import json

    text = getattr(response, "output_text", None)
    if not text:
        return {}
    try:
        loaded = json.loads(text)
    except json.JSONDecodeError:
        return {}
    return loaded if isinstance(loaded, dict) else {}
