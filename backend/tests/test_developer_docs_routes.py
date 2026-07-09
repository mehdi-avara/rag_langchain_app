import os
import sys
from pathlib import Path
from types import SimpleNamespace

from fastapi import FastAPI
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

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import deps
from core.exceptions import register_exception_handlers
from routs.developer_docs import router


def make_user(permissions=None):
    role = SimpleNamespace(
        is_active=True,
        permissions=[
            SimpleNamespace(name=permission)
            for permission in permissions or []
        ],
    )
    return SimpleNamespace(id=1, role="developer", company_id=1, roles=[role])


def create_app() -> FastAPI:
    app = FastAPI()
    register_exception_handlers(app)
    app.include_router(router)
    return app


def client_for(app, user):
    app.dependency_overrides[deps.get_current_user] = lambda: user
    return TestClient(app)


def test_list_developer_docs_requires_permission():
    app = create_app()
    client = client_for(app, make_user(permissions=[]))

    try:
        response = client.get("/developer-docs")
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 403
    assert response.json()["error"]["code"] == "PERMISSION_DENIED"


def test_list_developer_docs_returns_docs_for_authorized_user():
    app = create_app()
    client = client_for(app, make_user(permissions=["developer_docs:read"]))

    try:
        response = client.get("/developer-docs")
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200
    paths = {item["path"] for item in response.json()}
    assert "CMMS_BACKEND_PLAN.md" in paths


def test_get_developer_doc_returns_file_for_authorized_user():
    app = create_app()
    client = client_for(app, make_user(permissions=["developer_docs:read"]))

    try:
        response = client.get("/developer-docs/CMMS_BACKEND_PLAN.md")
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200
    assert b"# CMMS Backend Plan" in response.content


def test_get_developer_doc_blocks_path_traversal():
    app = create_app()
    client = client_for(app, make_user(permissions=["developer_docs:read"]))

    try:
        response = client.get("/developer-docs/%2e%2e/AGENTS.md")
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 404


def test_get_developer_doc_blocks_hidden_files():
    app = create_app()
    client = client_for(app, make_user(permissions=["developer_docs:read"]))

    try:
        response = client.get("/developer-docs/.DS_Store")
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 404
