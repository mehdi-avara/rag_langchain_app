from __future__ import annotations

import re
from typing import Any
from urllib.parse import (
    unquote,
    urlsplit,
    urlunsplit,
)

import httpx
from openai import AsyncOpenAI


class LLMEndpointSecurityError(
    ValueError
):
    pass


_CONTROL_CHARACTER_PATTERN = re.compile(
    r"[\x00-\x1f\x7f]"
)


def normalize_llm_base_url(
    value: str,
) -> str:
    if not isinstance(
        value,
        str,
    ):
        raise LLMEndpointSecurityError(
            "LLM base URL must be a string"
        )

    candidate = value.strip()

    if not candidate:
        raise LLMEndpointSecurityError(
            "LLM base URL is required"
        )

    if (
        _CONTROL_CHARACTER_PATTERN.search(
            candidate
        )
        or "\\" in candidate
    ):
        raise LLMEndpointSecurityError(
            "LLM base URL contains invalid characters"
        )

    try:
        parsed = urlsplit(
            candidate
        )
    except ValueError as exc:
        raise LLMEndpointSecurityError(
            "LLM base URL is invalid"
        ) from exc

    scheme = parsed.scheme.lower()

    if scheme not in {
        "http",
        "https",
    }:
        raise LLMEndpointSecurityError(
            "LLM base URL scheme is not allowed"
        )

    if (
        parsed.username is not None
        or parsed.password is not None
    ):
        raise LLMEndpointSecurityError(
            "LLM base URL must not contain user information"
        )

    if parsed.query or parsed.fragment:
        raise LLMEndpointSecurityError(
            "LLM base URL must not contain a query or fragment"
        )

    hostname = parsed.hostname

    if not hostname:
        raise LLMEndpointSecurityError(
            "LLM base URL hostname is required"
        )

    hostname = hostname.lower().rstrip(
        "."
    )

    if not hostname or "%" in hostname:
        raise LLMEndpointSecurityError(
            "LLM base URL hostname is invalid"
        )

    try:
        port = parsed.port
    except ValueError as exc:
        raise LLMEndpointSecurityError(
            "LLM base URL port is invalid"
        ) from exc

    if (
        scheme == "https"
        and port == 443
    ) or (
        scheme == "http"
        and port == 80
    ):
        port = None

    try:
        ascii_hostname = hostname.encode(
            "idna"
        ).decode(
            "ascii"
        )
    except UnicodeError as exc:
        raise LLMEndpointSecurityError(
            "LLM base URL hostname is invalid"
        ) from exc

    if ":" in ascii_hostname:
        normalized_host = (
            f"[{ascii_hostname}]"
        )
    else:
        normalized_host = ascii_hostname

    netloc = normalized_host

    if port is not None:
        netloc = f"{netloc}:{port}"

    path = parsed.path or ""

    if "//" in path:
        raise LLMEndpointSecurityError(
            "LLM base URL path is ambiguous"
        )

    decoded_segments = [
        unquote(segment)
        for segment in path.split("/")
    ]

    if any(
        segment in {
            ".",
            "..",
        }
        for segment in decoded_segments
    ):
        raise LLMEndpointSecurityError(
            "LLM base URL path traversal is not allowed"
        )

    normalized_path = path.rstrip(
        "/"
    )

    return urlunsplit(
        (
            scheme,
            netloc,
            normalized_path,
            "",
            "",
        )
    )


def allowed_llm_base_urls(
    settings: Any,
) -> frozenset[str]:
    configured_values = [
        settings.openai_base_url,
    ]

    extra_values = getattr(
        settings,
        "llm_allowed_base_urls",
        "",
    )

    if extra_values:
        configured_values.extend(
            value.strip()
            for value in re.split(
                r"[,\n]",
                str(extra_values),
            )
            if value.strip()
        )

    return frozenset(
        normalize_llm_base_url(
            value
        )
        for value in configured_values
    )


def validate_llm_base_url(
    value: str,
    settings: Any,
) -> str:
    normalized = normalize_llm_base_url(
        value
    )

    if normalized not in allowed_llm_base_urls(
        settings
    ):
        raise LLMEndpointSecurityError(
            "LLM base URL is not in the configured allowlist"
        )

    return normalized


def build_async_openai_client(
    *,
    api_key: str,
    base_url: str,
    settings: Any,
    timeout: float | int,
) -> AsyncOpenAI:
    validated_base_url = (
        validate_llm_base_url(
            base_url,
            settings,
        )
    )

    http_client = httpx.AsyncClient(
        follow_redirects=False,
    )

    return AsyncOpenAI(
        api_key=api_key,
        base_url=validated_base_url,
        timeout=timeout,
        max_retries=0,
        http_client=http_client,
    )
