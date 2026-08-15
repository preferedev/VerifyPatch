from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol

from verifypatch.requirements import PROMPT_VERSION, REQUIREMENT_SCHEMA_VERSION


@dataclass
class SourceSnapshot:
    ref: str
    path: str
    start_line: int
    end_line: int
    text: str
    digest: str
    kind: str


@dataclass
class ExtractionRequest:
    sources: list[SourceSnapshot]
    schema: dict[str, Any]
    prompt_version: str = PROMPT_VERSION
    requirement_schema_version: str = REQUIREMENT_SCHEMA_VERSION
    model: str | None = None


@dataclass
class ProviderResponse:
    payload: dict[str, Any]
    provider: str
    model: str
    request_id: str | None = None
    constrained_output: bool = True
    truncated: bool = False
    refused: bool = False
    refusal_message: str | None = None
    error_code: str | None = None
    error_message: str | None = None
    raw_artifact: str | None = None


class RequirementProvider(Protocol):
    name: str

    def extract(self, request: ExtractionRequest) -> ProviderResponse:
        ...
