"""PROMPT §10.1 — build_*_draft resolves the right commit_target + checks permission early."""

import pytest

from assistant.tests.fakes import ALL_FINANCIAL_PERMS, make_user

from core.exceptions.app_exception import AppException
from core.exceptions.error_codes import PERMISSION_DENIED
from financial_management.assistant_tools import FinancialAssistantToolSet

toolset = FinancialAssistantToolSet()


def test_add_receipt_resolves_commit_target():
    user = make_user(ALL_FINANCIAL_PERMS)
    slots = {
        "description": "pump invoice",
        "amount": "1200000",
        "currency": "IRR",
        "direction": "output",
        "credit_card_id": 3,
        "receipt_date": "2026-06-01",
        "counterparty_name": "ACME",
    }
    draft = toolset.build_draft(intent="add_receipt", db=None, user=user, slots=slots, attachments=[])

    assert draft.valid is True
    assert draft.target_action == "create_receipt"
    assert draft.commit_target == {
        "method": "POST",
        "endpoint": "/financial_management/receipts",
        "permission": "financial_management:receipts:create",
    }
    assert draft.payload["amount"] == "1200000"
    assert draft.payload["currency"] == "IRR"
    assert draft.payload["direction"] == "output"


def test_add_receipt_missing_fields_returns_partial_object_and_noun_missing():
    user = make_user(ALL_FINANCIAL_PERMS)
    draft = toolset.build_draft(
        intent="add_receipt", db=None, user=user,
        slots={"description": "pump", "amount": "100"}, attachments=[],
    )
    assert draft.valid is False
    assert draft.clarify_question
    assert draft.commit_target == {}
    # The object completed so far is returned…
    assert draft.payload["description"] == "pump"
    assert draft.payload["amount"] == "100"
    # …and the still-missing fields are named as nouns.
    missing = draft.validation["missing"]
    assert "credit card" in missing
    assert "receipt date" in missing
    assert "counterparty" in missing
    assert "description" not in missing  # already provided


def test_update_receipt_uses_patch_with_entity_id():
    user = make_user(ALL_FINANCIAL_PERMS)
    draft = toolset.build_draft(
        intent="update_receipt", db=None, user=user, slots={"receipt_id": 42, "amount": "999"}, attachments=[]
    )
    assert draft.valid is True
    assert draft.commit_target["method"] == "PATCH"
    assert draft.commit_target["endpoint"] == "/financial_management/receipts/42"
    assert draft.commit_target["permission"] == "financial_management:receipts:update"


def test_attach_receipt_file_uses_complete_upload_endpoint():
    user = make_user(ALL_FINANCIAL_PERMS)
    draft = toolset.build_draft(
        intent="attach_receipt_file", db=None, user=user, slots={"receipt_id": 5}, attachments=[88]
    )
    assert draft.valid is True
    assert draft.commit_target["endpoint"] == "/financial_management/receipts/5/files/complete-upload/88"
    assert draft.attachments == [88]


def test_build_draft_checks_permission_early():
    # Lacks receipts:create -> early ensure_permission must raise PERMISSION_DENIED,
    # so an un-committable draft is never offered.
    perms = [p for p in ALL_FINANCIAL_PERMS if p != "financial_management:receipts:create"]
    user = make_user(perms)
    with pytest.raises(AppException) as exc:
        toolset.build_draft(intent="add_receipt", db=None, user=user, slots={}, attachments=[])
    assert exc.value.code == PERMISSION_DENIED


def test_add_card_and_customer_commit_targets():
    user = make_user(ALL_FINANCIAL_PERMS)
    card = toolset.build_draft(
        intent="add_card", db=None, user=user, slots={"title": "Main", "card_number": "6037"}, attachments=[]
    )
    assert card.commit_target["endpoint"] == "/financial_management/cards"

    cust = toolset.build_draft(
        intent="add_customer",
        db=None,
        user=user,
        slots={"name": "ACME", "phone_number1": "0912", "access_method": "phone"},
        attachments=[],
    )
    assert cust.commit_target["endpoint"] == "/financial_management/customers"
    assert cust.payload["access_method"] == "phone"
