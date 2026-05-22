import os

from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient

os.environ.setdefault("POSTGRES_DB", "test")
os.environ.setdefault("POSTGRES_USER", "test")
os.environ.setdefault("POSTGRES_PASSWORD", "test")
os.environ.setdefault("POSTGRES_IP", "localhost")
os.environ.setdefault("default_username", "admin")
os.environ.setdefault("default_password", "admin123456")
os.environ.setdefault("default_firstname", "Admin")
os.environ.setdefault("jwt_secret", "test-secret")
os.environ.setdefault("openai_api_key", "test")
os.environ.setdefault("jina_api_key", "test")

from core.exceptions import AppException, register_exception_handlers
from core.exceptions.error_codes import (
    CHAT_NOT_FOUND,
    LLM_SERVICE_UNAVAILABLE,
    NOT_FOUND_STATUS_CODE,
    SERVICE_UNAVAILABLE_STATUS_CODE,
)


def create_app():
    app = FastAPI()
    register_exception_handlers(app)

    @app.get("/app-error")
    def app_error():
        raise AppException(
            status_code=SERVICE_UNAVAILABLE_STATUS_CODE,
            code=LLM_SERVICE_UNAVAILABLE,
            message="LLM service is unavailable",
        )

    @app.get("/http-error")
    def http_error():
        raise HTTPException(status_code=404, detail="Item not found")

    @app.get("/coded-http-error")
    def coded_http_error():
        raise HTTPException(
            status_code=NOT_FOUND_STATUS_CODE,
            detail={
                "code": CHAT_NOT_FOUND,
                "message": "Chat not found",
                "user_message": "گفتگو پیدا نشد.",
                "details": {"chat_id": 10},
            },
        )

    @app.get("/validation")
    def validation_error(limit: int):
        return {"limit": limit}

    return app


def test_app_exception_returns_standard_error_shape():
    client = TestClient(create_app(), raise_server_exceptions=False)

    response = client.get("/app-error")

    assert response.status_code == 503
    body = response.json()
    assert body["error"]["code"] == LLM_SERVICE_UNAVAILABLE
    assert body["error"]["message"] == "LLM service is unavailable"
    assert body["error"]["user_message"] == "سرویس هوش مصنوعی فعلاً در دسترس نیست. لطفاً بعداً دوباره تلاش کنید."
    assert body["error"]["details"] is None
    assert "request_id" in body["error"]


def test_plain_http_exception_returns_standard_error_shape():
    client = TestClient(create_app(), raise_server_exceptions=False)

    response = client.get("/http-error")

    assert response.status_code == 404
    body = response.json()
    assert body["error"]["code"] == "NOT_FOUND"
    assert body["error"]["message"] == "Item not found"
    assert body["error"]["user_message"] == "مورد درخواستی پیدا نشد."


def test_coded_http_exception_keeps_error_code():
    client = TestClient(create_app(), raise_server_exceptions=False)

    response = client.get("/coded-http-error")

    assert response.status_code == 404
    body = response.json()
    assert body["error"]["code"] == CHAT_NOT_FOUND
    assert body["error"]["message"] == "Chat not found"
    assert body["error"]["user_message"] == "گفتگو پیدا نشد."
    assert body["error"]["details"] == {"chat_id": 10}


def test_validation_error_returns_standard_error_shape():
    client = TestClient(create_app(), raise_server_exceptions=False)

    response = client.get("/validation?limit=bad")

    assert response.status_code == 422
    body = response.json()
    assert body["error"]["code"] == "VALIDATION_ERROR"
    assert body["error"]["message"] == "Request validation failed"
    assert body["error"]["user_message"] == "اطلاعات واردشده معتبر نیست."
    assert isinstance(body["error"]["details"], list)
