"""Central JSON coercion, secret redaction, and bounded previews.

This module is used by both AgentRun snapshots and append-only events. It never
serialises arbitrary object reprs because they commonly contain credentials,
request/session internals, or uploaded content.
"""

from __future__ import annotations

import enum
import json
import re
from collections.abc import Mapping
from datetime import date, datetime
from decimal import Decimal
from typing import Any

from settings import get_settings


REDACTED = "***REDACTED***"
SENSITIVE_KEY_PARTS = {
    "authorization", "cookie", "credential", "password", "passwd", "secret",
    "token", "api_key", "apikey", "access_key", "private_key", "session",
}
CONTENT_KEY_PARTS = {
    "raw_prompt", "prompt_text", "file_content", "file_bytes", "binary",
    "image_data", "uploaded_file", "complete_file", "authorization_header", "extracted_text",
}
HIDDEN_REASONING_KEYS = {
    "chain_of_thought", "chain-of-thought", "reasoning", "hidden_reasoning",
    "scratchpad", "thought", "thoughts", "rationale",
}


def _normalise_key(key: Any) -> str:
    return str(key).strip().lower().replace("-", "_")


def _is_sensitive_key(key: Any) -> bool:
    name = _normalise_key(key)
    return name in CONTENT_KEY_PARTS or any(part in name for part in SENSITIVE_KEY_PARTS)


def _is_hidden_reasoning_key(key: Any) -> bool:
    return _normalise_key(key) in HIDDEN_REASONING_KEYS


def _large_text(value: str, preview_chars: int) -> dict[str, Any]:
    encoded = value.encode("utf-8", errors="replace")
    return {
        "type": "string",
        "char_count": len(value),
        "byte_size": len(encoded),
        "truncated": True,
        "redacted_preview": _redact_inline_secrets(value[:preview_chars]),
    }


INLINE_SECRET_PATTERNS = (
    re.compile(r"(?i)\bBearer\s+[A-Za-z0-9._~+\-/]+=*"),
    re.compile(r"(?i)\b(api[_-]?key|access[_-]?token|password|secret)\s*[:=]\s*[^\s,;]+"),
)


def _redact_inline_secrets(value: str) -> str:
    output = value
    for pattern in INLINE_SECRET_PATTERNS:
        output = pattern.sub(REDACTED, output)
    return output


def _coerce(value: Any, *, preview_chars: int, depth: int = 0) -> Any:
    if depth > 12:
        return {"type": type(value).__name__, "truncated": True, "reason": "max_depth"}
    if value is None or isinstance(value, (bool, int, float)):
        return value
    if isinstance(value, str):
        value = _redact_inline_secrets(value)
        return value if len(value) <= preview_chars * 4 else _large_text(value, preview_chars)
    if isinstance(value, (bytes, bytearray, memoryview)):
        return {"type": type(value).__name__, "byte_size": len(value), "redacted": True}
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, enum.Enum):
        return _coerce(value.value, preview_chars=preview_chars, depth=depth + 1)
    if isinstance(value, BaseException):
        return {
            "type": type(value).__name__,
            "error_code": getattr(value, "code", None),
            "redacted": True,
        }
    if isinstance(value, Mapping):
        output: dict[str, Any] = {}
        for key, item in value.items():
            name = str(key)
            if _is_hidden_reasoning_key(name):
                continue
            if _is_sensitive_key(name):
                output[name] = REDACTED
            else:
                output[name] = _coerce(item, preview_chars=preview_chars, depth=depth + 1)
        return output
    if isinstance(value, (list, tuple, set, frozenset)):
        values = list(value)
        visible = values[:100]
        result = [_coerce(item, preview_chars=preview_chars, depth=depth + 1) for item in visible]
        if len(values) > len(visible):
            result.append({"truncated": True, "omitted_count": len(values) - len(visible)})
        return result
    # Never call str()/repr() on arbitrary request, ORM, client, or session objects.
    return {"type": type(value).__name__, "redacted": True}


def sanitize_payload(
    value: Any,
    *,
    max_bytes: int | None = None,
    preview_chars: int | None = None,
) -> Any:
    """Return JSON-serialisable, redacted data within ``max_bytes``.

    If the complete structured value still exceeds the configured cap, retain
    safe top-level metadata instead of an unbounded partial serialisation.
    """
    settings = get_settings()
    limit = max(256, max_bytes or settings.assistant_event_payload_max_bytes)
    preview = max(16, preview_chars or settings.assistant_event_preview_chars)
    safe = _coerce(value, preview_chars=preview)
    encoded = json.dumps(safe, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    if len(encoded) <= limit:
        return safe
    metadata: dict[str, Any] = {
        "truncated": True,
        "byte_size": len(encoded),
        "max_bytes": limit,
        "type": type(value).__name__,
    }
    if isinstance(safe, dict):
        metadata["keys"] = list(safe)[:100]
        # Keep compact scalar correlation fields when possible.
        metadata["data"] = {
            key: item for key, item in safe.items()
            if isinstance(item, (type(None), bool, int, float, str))
        }
    elif isinstance(safe, list):
        metadata["count"] = len(safe)
    return metadata


def sanitize_event_payload(value: Any) -> dict[str, Any]:
    safe = sanitize_payload(value)
    return safe if isinstance(safe, dict) else {"value": safe}
