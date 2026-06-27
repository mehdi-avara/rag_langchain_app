"""Shared test doubles for the assistant tests.

Follows the repo's existing FakeDB/FakeQuery convention (see
``tests/test_financial_receipt_asset_routes.py``) so tests run without a real
database, LLM, or S3.
"""

from __future__ import annotations

import os

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

from datetime import datetime
from types import SimpleNamespace
from typing import Iterable


class FakePermission:
    def __init__(self, name: str):
        self.name = name


class FakeRole:
    def __init__(self, permissions: Iterable[str], is_active: bool = True):
        self.is_active = is_active
        self.permissions = [FakePermission(name) for name in permissions]


def make_user(permissions: Iterable[str], *, user_id: int = 1, company_id: int = 7):
    """A User-like object whose ``roles -> permissions`` drive get_user_permissions."""
    return SimpleNamespace(
        id=user_id,
        company_id=company_id,
        roles=[FakeRole(permissions)],
        role="user",
    )


ALL_FINANCIAL_PERMS = [
    "assistant:chat",
    "assistant:draft",
    "assistant:files",
    "financial_management:receipts:search",
    "financial_management:receipts:read",
    "financial_management:receipts:ask",
    "financial_management:receipts:create",
    "financial_management:receipts:update",
    "financial_management:cards:create",
    "financial_management:cards:update",
    "financial_management:customers:create",
    "financial_management:customers:update",
    "financial_management:receipt_comments:create",
    "financial_management:receipt_files:create",
]


class FakeQuery:
    def __init__(self, db, target):
        self.db = db
        self.target = target

    def filter(self, *args, **kwargs):
        return self

    def order_by(self, *args, **kwargs):
        return self

    def first(self):
        return self.db.results.get(("first", self.target.__name__))

    def all(self):
        return self.db.results.get(("all", self.target.__name__), [])


class FakeDB:
    """Minimal Session stand-in for the draft/run service unit tests."""

    def __init__(self):
        self.results = {}
        self.added = []
        self.committed = 0
        self.refreshed = []

    def set_first(self, model_name: str, value):
        self.results[("first", model_name)] = value

    def set_all(self, model_name: str, value):
        self.results[("all", model_name)] = value

    def query(self, target):
        return FakeQuery(self, target)

    def add(self, obj):
        if getattr(obj, "id", None) is None:
            obj.id = 1000 + len(self.added)
        self.added.append(obj)

    def commit(self):
        self.committed += 1

    def refresh(self, obj):
        if getattr(obj, "created_at", None) is None:
            obj.created_at = datetime(2026, 6, 27, 12, 0, 0)
        if getattr(obj, "updated_at", None) is None:
            obj.updated_at = datetime(2026, 6, 27, 12, 0, 0)
        self.refreshed.append(obj)
