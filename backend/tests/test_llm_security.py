from __future__ import annotations

import ast
import inspect
import os
import textwrap
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi import HTTPException


os.environ.setdefault(
    "POSTGRES_DB",
    "security_unit_test",
)
os.environ.setdefault(
    "POSTGRES_USER",
    "security_unit_test",
)
os.environ.setdefault(
    "POSTGRES_PASSWORD",
    "security_unit_test",
)
os.environ.setdefault(
    "POSTGRES_IP",
    "127.0.0.1",
)
os.environ.setdefault(
    "default_username",
    "security-admin",
)
os.environ.setdefault(
    "default_password",
    "security-password",
)
os.environ.setdefault(
    "default_firstname",
    "Security",
)
os.environ.setdefault(
    "jwt_secret",
    "security-unit-test-secret",
)
os.environ.setdefault(
    "openai_api_key",
    "security-test-key",
)
os.environ.setdefault(
    "jina_api_key",
    "security-test-key",
)

from assistant import intake
from core import llm_security
from core.llm_security import (
    LLMEndpointSecurityError,
    allowed_llm_base_urls,
    normalize_llm_base_url,
    validate_llm_base_url,
)
from deps import require_platform_permission
from routs import chat_ai_models


def settings(
    *,
    base_url: str = (
        "https://llm.example.test/v1"
    ),
    allowed: str = "",
):
    return SimpleNamespace(
        openai_base_url=base_url,
        llm_allowed_base_urls=allowed,
    )


def permission(
    name: str,
):
    return SimpleNamespace(
        name=name
    )


def role(
    *,
    permission_name: str,
    active: bool = True,
    system: bool = True,
    company_id=None,
):
    return SimpleNamespace(
        is_active=active,
        is_system=system,
        company_id=company_id,
        permissions=[
            permission(
                permission_name
            )
        ],
    )


def user_with_role(
    role_value,
):
    return SimpleNamespace(
        roles=[
            role_value
        ]
    )


def test_platform_permission_accepts_only_active_global_system_role():
    checker = require_platform_permission(
        "llm:update"
    )

    user = user_with_role(
        role(
            permission_name="llm:update",
        )
    )

    assert checker(
        current_user=user
    ) is user


@pytest.mark.parametrize(
    "role_value",
    [
        role(
            permission_name="llm:update",
            active=False,
        ),
        role(
            permission_name="llm:update",
            system=False,
        ),
        role(
            permission_name="llm:update",
            company_id=7,
        ),
    ],
)
def test_platform_permission_rejects_non_platform_roles(
    role_value,
):
    checker = require_platform_permission(
        "llm:update"
    )

    with pytest.raises(
        HTTPException
    ) as exc:
        checker(
            current_user=user_with_role(
                role_value
            )
        )

    assert exc.value.status_code == 403
    assert (
        exc.value.detail["code"]
        == "PLATFORM_PERMISSION_REQUIRED"
    )


def test_normalize_llm_base_url_removes_default_port_and_trailing_slash():
    assert normalize_llm_base_url(
        "https://LLM.Example.Test:443/v1/"
    ) == "https://llm.example.test/v1"


@pytest.mark.parametrize(
    "value",
    [
        "",
        "ftp://llm.example.test/v1",
        "https://user@example.test/v1",
        "https://llm.example.test/v1?target=x",
        "https://llm.example.test/v1#fragment",
        "https://llm.example.test/v1/../admin",
        "https://llm.example.test/v1//admin",
        "https://llm.example.test\\@internal/v1",
    ],
)
def test_normalize_llm_base_url_rejects_ambiguous_values(
    value,
):
    with pytest.raises(
        LLMEndpointSecurityError
    ):
        normalize_llm_base_url(
            value
        )


def test_validator_accepts_only_exact_configured_base_urls():
    config = settings(
        allowed=(
            "https://secondary.example.test/v1"
        )
    )

    assert validate_llm_base_url(
        "https://llm.example.test/v1/",
        config,
    ) == "https://llm.example.test/v1"

    assert validate_llm_base_url(
        "https://secondary.example.test/v1",
        config,
    ) == (
        "https://secondary.example.test/v1"
    )

    with pytest.raises(
        LLMEndpointSecurityError
    ):
        validate_llm_base_url(
            "https://llm.example.test/admin",
            config,
        )

    with pytest.raises(
        LLMEndpointSecurityError
    ):
        validate_llm_base_url(
            "https://different.example.test/v1",
            config,
        )


def test_allowed_urls_include_configured_base_url():
    assert allowed_llm_base_urls(
        settings()
    ) == frozenset(
        {
            "https://llm.example.test/v1"
        }
    )


def test_route_endpoint_validation_returns_safe_error(
    monkeypatch,
):
    monkeypatch.setattr(
        chat_ai_models,
        "settings",
        settings(),
    )

    assert (
        chat_ai_models._validated_endpoint(
            "https://llm.example.test/v1/"
        )
        == "https://llm.example.test/v1"
    )

    with pytest.raises(
        HTTPException
    ) as exc:
        chat_ai_models._validated_endpoint(
            "http://127.0.0.1/v1"
        )

    assert exc.value.status_code == 400
    assert (
        exc.value.detail["code"]
        == "LLM_ENDPOINT_NOT_ALLOWED"
    )


def test_client_builder_disables_redirects_and_retries(
    monkeypatch,
):
    captured = {}

    class FakeHTTPClient:
        pass

    def fake_http_client(
        **kwargs,
    ):
        captured[
            "http_client_options"
        ] = kwargs

        return FakeHTTPClient()

    def fake_openai(
        **kwargs,
    ):
        captured[
            "openai_options"
        ] = kwargs

        return SimpleNamespace(
            options=kwargs
        )

    monkeypatch.setattr(
        llm_security.httpx,
        "AsyncClient",
        fake_http_client,
    )

    monkeypatch.setattr(
        llm_security,
        "AsyncOpenAI",
        fake_openai,
    )

    llm_security.build_async_openai_client(
        api_key="test-key",
        base_url=(
            "https://llm.example.test/v1"
        ),
        settings=settings(),
        timeout=45,
    )

    assert captured[
        "http_client_options"
    ]["follow_redirects"] is False

    assert captured[
        "openai_options"
    ]["max_retries"] == 0

    assert captured[
        "openai_options"
    ]["base_url"] == (
        "https://llm.example.test/v1"
    )


def test_llm_routes_require_platform_permissions():
    source = Path(
        chat_ai_models.__file__
    ).read_text(
        encoding="utf-8"
    )

    assert (
        source.count(
            "require_platform_permission("
        )
        == 4
    )

    assert (
        "require_permission("
        not in source
    )


def test_assistant_runtime_validates_stored_endpoint_and_does_not_log_it():
    source = inspect.getsource(
        intake.resolve_chat_model
    )

    assert (
        "validate_llm_base_url"
        in source
    )

    assert (
        "build_async_openai_client"
        in source
    )

    assert (
        " at %s "
        not in source
    )

    tree = ast.parse(
        textwrap.dedent(
            source
        )
    )

    logger_calls = [
        node
        for node in ast.walk(
            tree
        )
        if isinstance(
            node,
            ast.Call,
        )
        and isinstance(
            node.func,
            ast.Attribute,
        )
        and isinstance(
            node.func.value,
            ast.Name,
        )
        and node.func.value.id == "logger"
    ]

    assert logger_calls

    for logger_call in logger_calls:
        logger_contract = ast.dump(
            logger_call,
            include_attributes=False,
        )

        assert (
            "id='base_url'"
            not in logger_contract
        )

        assert (
            "attr='openai_base_url'"
            not in logger_contract
        )
