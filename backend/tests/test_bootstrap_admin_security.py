from __future__ import annotations

import ast
import os
from pathlib import Path
from types import SimpleNamespace

import pytest

from db import init_db


class FakeQuery:
    def __init__(self, result):
        self.result = result

    def filter(self, *args, **kwargs):
        return self

    def filter_by(self, **kwargs):
        return self

    def first(self):
        return self.result


class FakeDB:
    def __init__(self, query_results):
        self.query_results = list(query_results)
        self.added = []
        self.commit_count = 0
        self.rollback_count = 0
        self.close_count = 0
        self.flush_count = 0

    def query(self, *args):
        if not self.query_results:
            raise AssertionError(
                "Unexpected database query"
            )

        return FakeQuery(
            self.query_results.pop(0)
        )

    def add(self, value):
        self.added.append(value)

    def flush(self):
        self.flush_count += 1

        for value in self.added:
            if getattr(value, "id", None) is None:
                value.id = 101

    def commit(self):
        self.commit_count += 1

    def rollback(self):
        self.rollback_count += 1

    def close(self):
        self.close_count += 1


class FakeUser:
    id = object()

    def __init__(
        self,
        *,
        company_id,
        username,
        First_name,
        pw_hash,
        role,
    ):
        self.id = None
        self.company_id = company_id
        self.username = username
        self.First_name = First_name
        self.pw_hash = pw_hash
        self.role = role
        self.roles = []


def configure_valid_bootstrap(
    monkeypatch,
) -> None:
    monkeypatch.setattr(
        init_db.settings,
        "bootstrap_admin_enabled",
        True,
    )

    monkeypatch.setattr(
        init_db.settings,
        "default_username",
        "bootstrap-owner",
    )

    monkeypatch.setattr(
        init_db.settings,
        "default_password",
        "Long-Random-Test-Password-2026",
    )

    monkeypatch.setattr(
        init_db.settings,
        "default_firstname",
        "Bootstrap",
    )


def test_bootstrap_settings_are_fail_closed() -> None:
    settings_path = (
        Path(__file__).resolve().parents[1]
        / "settings.py"
    )

    tree = ast.parse(
        settings_path.read_text(
            encoding="utf-8",
        ),
        filename=str(settings_path),
    )

    values = {}

    for node in tree.body:
        if not isinstance(node, ast.ClassDef):
            continue

        if node.name != "Settings":
            continue

        for item in node.body:
            if (
                isinstance(item, ast.AnnAssign)
                and isinstance(
                    item.target,
                    ast.Name,
                )
                and isinstance(
                    item.value,
                    ast.Constant,
                )
            ):
                values[
                    item.target.id
                ] = item.value.value

    assert (
        values["bootstrap_admin_enabled"]
        is False
    )

    assert values["default_username"] == ""
    assert values["default_password"] == ""
    assert values["default_firstname"] == ""


def test_api_startup_requires_explicit_flag() -> None:
    api_path = (
        Path(__file__).resolve().parents[1]
        / "api.py"
    )

    tree = ast.parse(
        api_path.read_text(
            encoding="utf-8",
        ),
        filename=str(api_path),
    )

    functions = [
        node
        for node in tree.body
        if isinstance(
            node,
            (
                ast.FunctionDef,
                ast.AsyncFunctionDef,
            ),
        )
        and node.name
        == "seed_default_user_on_startup"
    ]

    assert len(functions) == 1

    function = functions[0]

    assert len(function.body) == 1
    assert isinstance(function.body[0], ast.If)

    assert (
        ast.unparse(function.body[0].test)
        == "settings.bootstrap_admin_enabled"
    )


def test_disabled_bootstrap_does_not_open_database(
    monkeypatch,
) -> None:
    monkeypatch.setattr(
        init_db.settings,
        "bootstrap_admin_enabled",
        False,
    )

    def forbidden_session():
        raise AssertionError(
            "Disabled bootstrap opened a database session"
        )

    monkeypatch.setattr(
        init_db,
        "SessionLocal",
        forbidden_session,
    )

    init_db.seed_default_user()


def test_missing_credentials_fail_before_database(
    monkeypatch,
) -> None:
    monkeypatch.setattr(
        init_db.settings,
        "bootstrap_admin_enabled",
        True,
    )

    monkeypatch.setattr(
        init_db.settings,
        "default_username",
        "",
    )

    monkeypatch.setattr(
        init_db.settings,
        "default_password",
        "",
    )

    monkeypatch.setattr(
        init_db.settings,
        "default_firstname",
        "",
    )

    def forbidden_session():
        raise AssertionError(
            "Invalid bootstrap opened a database session"
        )

    monkeypatch.setattr(
        init_db,
        "SessionLocal",
        forbidden_session,
    )

    with pytest.raises(
        RuntimeError,
        match="username is required",
    ):
        init_db.seed_default_user()


def test_short_password_fails_before_database(
    monkeypatch,
) -> None:
    configure_valid_bootstrap(
        monkeypatch
    )

    monkeypatch.setattr(
        init_db.settings,
        "default_password",
        "admin123456",
    )

    def forbidden_session():
        raise AssertionError(
            "Invalid bootstrap opened a database session"
        )

    monkeypatch.setattr(
        init_db,
        "SessionLocal",
        forbidden_session,
    )

    with pytest.raises(
        RuntimeError,
        match="at least 16 characters",
    ):
        init_db.seed_default_user()


def test_existing_user_database_is_never_modified(
    monkeypatch,
) -> None:
    configure_valid_bootstrap(
        monkeypatch
    )

    db = FakeDB(
        query_results=[
            object(),
        ]
    )

    monkeypatch.setattr(
        init_db,
        "SessionLocal",
        lambda: db,
    )

    with pytest.raises(
        RuntimeError,
        match="user table is empty",
    ):
        init_db.seed_default_user()

    assert db.added == []
    assert db.commit_count == 0
    assert db.rollback_count == 1
    assert db.close_count == 1


def test_missing_global_admin_role_rolls_back(
    monkeypatch,
) -> None:
    configure_valid_bootstrap(
        monkeypatch
    )

    company = SimpleNamespace(
        id=44
    )

    db = FakeDB(
        query_results=[
            None,
            None,
        ]
    )

    monkeypatch.setattr(
        init_db,
        "SessionLocal",
        lambda: db,
    )

    monkeypatch.setattr(
        init_db,
        "_get_or_create_default_company",
        lambda session: company,
    )

    with pytest.raises(
        RuntimeError,
        match="global system admin role",
    ):
        init_db.seed_default_user()

    assert db.added == []
    assert db.commit_count == 0
    assert db.rollback_count == 1
    assert db.close_count == 1


def test_bootstrap_creates_admin_only_on_empty_database(
    monkeypatch,
) -> None:
    configure_valid_bootstrap(
        monkeypatch
    )

    company = SimpleNamespace(
        id=44
    )

    admin_role = SimpleNamespace(
        name="admin",
        company_id=None,
        is_system=True,
        is_active=True,
    )

    db = FakeDB(
        query_results=[
            None,
            admin_role,
        ]
    )

    provision_calls = []

    monkeypatch.setattr(
        init_db,
        "SessionLocal",
        lambda: db,
    )

    monkeypatch.setattr(
        init_db,
        "_get_or_create_default_company",
        lambda session: company,
    )

    monkeypatch.setattr(
        init_db,
        "User",
        FakeUser,
    )

    monkeypatch.setattr(
        init_db.bcrypt,
        "hash",
        lambda password: "hashed-password",
    )

    monkeypatch.setattr(
        init_db,
        "provision_company_defaults",
        lambda session,
        target_company,
        created_by_user_id: (
            provision_calls.append(
                (
                    session,
                    target_company,
                    created_by_user_id,
                )
            )
        ),
    )

    init_db.seed_default_user()

    assert len(db.added) == 1

    user = db.added[0]

    assert user.company_id == company.id
    assert user.roles == [admin_role]
    assert user.pw_hash == "hashed-password"
    assert db.commit_count == 1
    assert db.rollback_count == 0
    assert db.close_count == 1

    assert provision_calls == [
        (
            db,
            company,
            user.id,
        )
    ]


def test_env_example_contains_no_credentials() -> None:
    path = Path(
        os.environ[
            "SEC3C_ENV_EXAMPLE_PATH"
        ]
    )

    values = {}

    for line in path.read_text(
        encoding="utf-8",
    ).splitlines():
        stripped = line.strip()

        if (
            not stripped
            or stripped.startswith("#")
            or "=" not in stripped
        ):
            continue

        key, value = stripped.split(
            "=",
            1,
        )

        values[
            key.strip()
        ] = value.strip()

    assert (
        values[
            "bootstrap_admin_enabled"
        ]
        == "false"
    )

    assert values["default_username"] == ""
    assert values["default_password"] == ""
    assert values["default_firstname"] == ""
