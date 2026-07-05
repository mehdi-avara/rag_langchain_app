"""PROMPT §10.9 — the router only ever sees RBAC-permitted intents."""

from assistant.tests.fakes import ALL_FINANCIAL_PERMS, make_user

import financial_management.assistant_tools  # noqa: F401  (registers the toolset)
from assistant import registry


def _names(user):
    return {spec.name for spec in registry.assemble_intents(user)}


def test_full_permissions_expose_all_intents():
    user = make_user(ALL_FINANCIAL_PERMS)
    names = _names(user)
    assert "add_receipt" in names
    assert "search_receipts" in names
    assert "assistant_help" in names
    assert "general" in names
    assert "clarify" in names


def test_missing_create_permission_drops_add_receipt():
    perms = [p for p in ALL_FINANCIAL_PERMS if p != "financial_management:receipts:create"]
    user = make_user(perms)
    names = _names(user)
    # The restricted task is never named back to the user.
    assert "add_receipt" not in names
    # Read intents the user still holds remain available.
    assert "search_receipts" in names


def test_no_module_permissions_falls_back_to_general_clarify():
    user = make_user(["assistant:chat"])
    names = _names(user)
    assert names == {"assistant_help", "general", "clarify"}


def test_find_intent_respects_rbac():
    perms = [p for p in ALL_FINANCIAL_PERMS if p != "financial_management:receipts:create"]
    user = make_user(perms)
    assert registry.find_intent(user, "add_receipt") is None
    assert registry.find_intent(user, "search_receipts") is not None
