"""Secret redaction for logs and reports."""

from __future__ import annotations

import re
from typing import Any

SECRET_PATTERNS = [
    re.compile(r"(?i)(api[_-]?key|token|password|secret|authorization|cookie)\s*[:=]\s*([^\s,;]+)"),
    re.compile(r"(?i)bearer\s+[a-z0-9\-._~+/]+=*"),
    re.compile(r"(?i)sk-[a-z0-9]{10,}"),
    re.compile(r"(?i)xox[baprs]-[a-z0-9-]{10,}"),
]

SENSITIVE_KEYS = {
    "api_key",
    "apikey",
    "token",
    "access_token",
    "refresh_token",
    "password",
    "secret",
    "authorization",
    "cookie",
    "cookies",
    "session",
    "mcp_auth_token",
    "openai_api_key",
    "anthropic_api_key",
    "gemini_api_key",
    "skyvern_api_key",
    "eventbrite_api_token",
    "personal_oauth_token",
    "private_token",
}


def redact_secrets(text: str) -> str:
    redacted = text
    for pattern in SECRET_PATTERNS:
        redacted = pattern.sub(lambda m: _mask_match(m), redacted)
    return redacted


def _mask_match(match: re.Match[str]) -> str:
    full = match.group(0)
    if "=" in full or ":" in full:
        sep = "=" if "=" in full else ":"
        key, _ = full.split(sep, 1)
        return f"{key}{sep}***REDACTED***"
    return "***REDACTED***"


def redact_mapping(data: Any) -> Any:
    if isinstance(data, dict):
        out: dict[str, Any] = {}
        for key, value in data.items():
            if str(key).lower() in SENSITIVE_KEYS:
                out[key] = "***REDACTED***"
            else:
                out[key] = redact_mapping(value)
        return out
    if isinstance(data, list):
        return [redact_mapping(item) for item in data]
    if isinstance(data, str):
        return redact_secrets(data)
    return data
