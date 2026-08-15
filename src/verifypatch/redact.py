from __future__ import annotations

import re

from verifypatch.limits import MAX_OUTPUT_BYTES

_DEFAULT_SECRET_RE = re.compile(
    r"(?i)((?:api[_-]?key|token|secret|password|authorization)\s*[:=]\s*)(\S+)"
)


def redact_text(text: str, extra_patterns: list[str] | None = None) -> str:
    redacted = _DEFAULT_SECRET_RE.sub(r"\1[REDACTED]", text)
    for pattern in extra_patterns or []:
        redacted = re.sub(pattern, "[REDACTED]", redacted)
    if len(redacted.encode("utf-8")) > MAX_OUTPUT_BYTES:
        redacted = redacted.encode("utf-8")[:MAX_OUTPUT_BYTES].decode("utf-8", errors="replace")
    return redacted
