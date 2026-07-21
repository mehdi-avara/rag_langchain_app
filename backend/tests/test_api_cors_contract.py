import os

from fastapi import HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.testclient import TestClient


os.environ.setdefault("POSTGRES_DB", "test")
os.environ.setdefault("POSTGRES_USER", "test")
os.environ.setdefault("POSTGRES_PASSWORD", "test")
os.environ.setdefault("POSTGRES_IP", "localhost")
os.environ.setdefault("default_username", "admin")
os.environ.setdefault(
    "default_password",
    "admin123456",
)
os.environ.setdefault("default_firstname", "Admin")
os.environ.setdefault("jwt_secret", "test-secret")
os.environ.setdefault("openai_api_key", "test")
os.environ.setdefault("jina_api_key", "test")


from api import app, application


ORIGIN = "https://porsa.mahta-tech.com"


@app.get(
    "/__test_cors_expected_error__",
    include_in_schema=False,
)
def expected_error():
    raise HTTPException(
        status_code=422,
        detail="Controlled validation error",
    )


@app.get(
    "/__test_cors_unhandled_error__",
    include_in_schema=False,
)
def unhandled_error():
    raise RuntimeError(
        "Controlled unhandled error"
    )


def test_exported_application_is_outer_cors_wrapper():
    assert isinstance(application, CORSMiddleware)
    assert application.app is app


def test_expected_error_has_cors_header():
    client = TestClient(
        application,
        raise_server_exceptions=False,
    )

    response = client.get(
        "/__test_cors_expected_error__",
        headers={"Origin": ORIGIN},
    )

    assert response.status_code == 422

    assert (
        response.headers[
            "access-control-allow-origin"
        ]
        == ORIGIN
    )

    assert (
        response.json()["error"]["code"]
        == "BAD_REQUEST"
    )


def test_unhandled_error_has_cors_header():
    client = TestClient(
        application,
        raise_server_exceptions=False,
    )

    response = client.get(
        "/__test_cors_unhandled_error__",
        headers={"Origin": ORIGIN},
    )

    assert response.status_code == 500

    assert (
        response.headers[
            "access-control-allow-origin"
        ]
        == ORIGIN
    )

    body = response.json()

    assert (
        body["error"]["code"]
        == "INTERNAL_SERVER_ERROR"
    )

    assert (
        body["error"]["details"]
        is None
    )


def test_unknown_origin_is_not_reflected():
    client = TestClient(
        application,
        raise_server_exceptions=False,
    )

    response = client.get(
        "/__test_cors_unhandled_error__",
        headers={
            "Origin": "https://untrusted.example"
        },
    )

    assert response.status_code == 500

    assert (
        "access-control-allow-origin"
        not in response.headers
    )
