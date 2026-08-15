from __future__ import annotations

from verifypatch.config import RequirementsConfig
from verifypatch.errors import AnalysisError
from verifypatch.requirements.model import ExtractionRequest, ProviderResponse, RequirementProvider
from verifypatch.stage import Reason


class MissingProviderDependency(AnalysisError):
    pass


def classify_provider_error(exc: BaseException) -> str:
    name = type(exc).__name__.lower()
    text = str(exc).lower()
    if "timeout" in name or "timeout" in text:
        return "timeout"
    if "rate" in name or "rate_limit" in text or "429" in text:
        return "rate_limit"
    if "auth" in name or "unauthorized" in text or "401" in text:
        return "auth_error"
    return "provider_error"


class FakeProvider:
    name = "fake"

    def __init__(self, response: ProviderResponse | None = None) -> None:
        self._response = response
        self.calls: list[ExtractionRequest] = []

    def extract(self, request: ExtractionRequest) -> ProviderResponse:
        self.calls.append(request)
        if self._response is not None:
            return self._response
        return ProviderResponse(
            payload={
                "schema_version": "1",
                "prompt_version": request.prompt_version,
                "items": [],
                "refusal": {
                    "code": "insufficient_specification",
                    "message": "No source-backed behavior, invariant, boundary, example, or schema constraint.",
                },
            },
            provider=self.name,
            model=request.model or "fake",
            constrained_output=True,
            refused=True,
            refusal_message="insufficient_specification",
        )


def load_provider(config: RequirementsConfig, override: RequirementProvider | None = None) -> RequirementProvider | Reason:
    if override is not None:
        return override
    name = (config.provider or "openai").lower()
    if name == "fake":
        return FakeProvider()
    if name == "openai":
        from verifypatch.requirements.openai_provider import OpenAIProvider

        try:
            return OpenAIProvider(model=config.model)
        except MissingProviderDependency as exc:
            return Reason(code="missing_dependency", message=str(exc))
    if name == "anthropic":
        from verifypatch.requirements.anthropic_provider import AnthropicProvider

        try:
            return AnthropicProvider(model=config.model)
        except MissingProviderDependency as exc:
            return Reason(code="missing_dependency", message=str(exc))
    return Reason(code="unknown_provider", message=f"unknown requirements provider {config.provider!r}")
