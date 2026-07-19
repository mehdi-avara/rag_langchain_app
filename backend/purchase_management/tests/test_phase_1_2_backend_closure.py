from __future__ import annotations

import ast
import importlib.util
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from core.exceptions.error_codes import (
    PURCHASE_ORDER_INVALID_STRUCTURE,
    PURCHASE_ORDER_NOT_FOUND,
    PURCHASE_PHASE_NOT_FOUND,
)
from purchase_management.services import (
    _assert_purchase_order_ready_for_submission,
)
from shared.currency.services import (
    quantize_exchange_rate,
    quantize_money,
)


BACKEND_ROOT = Path(__file__).parents[2]


def _load_closure_migration():
    matches = list(
        (
            BACKEND_ROOT
            / "alembic"
            / "versions"
        ).glob(
            "*_close_phase_1_2_backend_contracts.py"
        )
    )

    assert len(matches) == 1

    spec = importlib.util.spec_from_file_location(
        "phase_1_2_backend_closure_migration",
        matches[0],
    )

    assert spec is not None
    assert spec.loader is not None

    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    return module


def _http_exception_raise_scopes(
    relative_path: str,
) -> list[str]:
    source = (
        BACKEND_ROOT
        / relative_path
    ).read_text(encoding="utf-8")
    tree = ast.parse(source)
    scopes: list[str] = []

    class Visitor(ast.NodeVisitor):
        def __init__(self):
            self.scope: list[str] = []

        def visit_FunctionDef(self, node):
            self.scope.append(node.name)
            self.generic_visit(node)
            self.scope.pop()

        def visit_AsyncFunctionDef(self, node):
            self.scope.append(node.name)
            self.generic_visit(node)
            self.scope.pop()

        def visit_Raise(self, node):
            call = node.exc

            if (
                isinstance(call, ast.Call)
                and isinstance(
                    call.func,
                    ast.Name,
                )
                and call.func.id
                == "HTTPException"
            ):
                scopes.append(
                    self.scope[-1]
                    if self.scope
                    else "<module>"
                )

            self.generic_visit(node)

    Visitor().visit(tree)

    return scopes


def test_shared_currency_rounding_is_canonical():
    assert quantize_money(
        Decimal("12.345"),
        2,
    ) == Decimal("12.35")

    assert quantize_money(
        Decimal("12.344"),
        2,
    ) == Decimal("12.34")

    assert quantize_exchange_rate(
        Decimal("1.12345678906")
    ) == Decimal("1.1234567891")


def test_purchase_services_have_no_local_rounding():
    source = (
        BACKEND_ROOT
        / "purchase_management"
        / "services.py"
    ).read_text(encoding="utf-8")

    assert "ROUND_HALF_UP" not in source
    assert "_quantize_decimal" not in source
    assert "RATE_QUANTUM" not in source
    assert "PRICE_QUANTUM" not in source
    assert "quantize_money" in source
    assert "quantize_exchange_rate" in source


def test_purchase_assistant_uses_material_service_boundary():
    source = (
        BACKEND_ROOT
        / "purchase_management"
        / "assistant_tools.py"
    ).read_text(encoding="utf-8")

    assert (
        "from material_management.models"
        not in source
    )
    assert (
        "from material_management.services"
        in source
    )


def test_purchase_http_exceptions_are_catalogued():
    service_scopes = (
        _http_exception_raise_scopes(
            "purchase_management/services.py"
        )
    )
    direct_mr_scopes = (
        _http_exception_raise_scopes(
            "purchase_management/"
            "direct_mr_service.py"
        )
    )

    assert service_scopes == [
        "purchase_error"
    ]
    assert direct_mr_scopes == []


def test_purchase_not_found_codes_are_registered():
    assert (
        PURCHASE_ORDER_NOT_FOUND
        == "PURCHASE_ORDER_NOT_FOUND"
    )
    assert (
        PURCHASE_PHASE_NOT_FOUND
        == "PURCHASE_PHASE_NOT_FOUND"
    )


def test_legacy_header_only_order_is_preserved_but_not_submittable():
    legacy_order = SimpleNamespace(
        supplier_id=9,
        lines=[],
        phases=[],
    )

    with pytest.raises(
        HTTPException
    ) as error:
        _assert_purchase_order_ready_for_submission(
            legacy_order
        )

    assert error.value.status_code == 422
    assert error.value.detail["code"] == (
        PURCHASE_ORDER_INVALID_STRUCTURE
    )


def test_closure_migration_backfills_split_permission(
    monkeypatch,
):
    migration = _load_closure_migration()
    statements: list[str] = []

    monkeypatch.setattr(
        migration.op,
        "execute",
        lambda statement: statements.append(
            str(statement)
        ),
    )

    migration.upgrade()

    assert len(statements) == 2

    sql = " ".join(
        " ".join(statements).split()
    )

    assert (
        "purchase_management:phases:split"
        in sql
    )
    assert "INSERT INTO permissions" in sql
    assert "ON CONFLICT (name)" in sql
    assert "INSERT INTO role_permission" in sql
    assert "role.name = 'admin'" in sql
    assert "role.company_id IS NULL" in sql


def test_closure_migration_downgrade_preserves_runtime_rbac(
    monkeypatch,
):
    migration = _load_closure_migration()
    statements: list[str] = []

    monkeypatch.setattr(
        migration.op,
        "execute",
        lambda statement: statements.append(
            str(statement)
        ),
    )

    migration.downgrade()

    assert statements == []
