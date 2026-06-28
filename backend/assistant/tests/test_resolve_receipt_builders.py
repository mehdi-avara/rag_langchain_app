"""FK-resolution task — card/customer resolution wired into the receipt builders."""

import pytest

from assistant.tests.fakes import ALL_FINANCIAL_PERMS, FakeProvider, make_user

from assistant.module_interface import Candidate, ResourceSpec, get_resource, register_resource
from financial_management.assistant_tools import FinancialAssistantToolSet

toolset = FinancialAssistantToolSet()


def _c(cid, match_text, label=None):
    return Candidate(id=cid, match_text=match_text, label=label or match_text)


@pytest.fixture
def swap_resources():
    """Swap real financial_card/financial_customer providers for fakes, then restore."""
    keys = ("financial_card", "financial_customer")
    saved = {k: get_resource(k) for k in keys}
    providers = {}

    def install(key, candidates):
        orig = saved[key]
        provider = FakeProvider(candidates)
        providers[key] = provider
        register_resource(ResourceSpec(
            key=key,
            read_permission=orig.read_permission,
            provider=provider,
            create_permission=orig.create_permission,
            create_endpoint=orig.create_endpoint,
            create_method=orig.create_method,
            suggestion_from=orig.suggestion_from,
        ))
        return provider

    yield install, providers
    for k, spec in saved.items():
        if spec is not None:
            register_resource(spec)


def _base_slots(**extra):
    slots = {
        "description": "pump invoice",
        "amount": "1200000",
        "currency": "IRR",
        "direction": "output",
        "receipt_date": "2026-06-01",
    }
    slots.update(extra)
    return slots


def _build(slots):
    user = make_user(ALL_FINANCIAL_PERMS)
    return toolset.build_draft(intent="add_receipt", db=None, user=user, slots=slots, attachments=[])


def test_card_text_resolves_single_match(swap_resources):
    install, _ = swap_resources
    install("financial_card", [_c(12, "Mellat", "Mellat — Bank Mellat — ••••4821 — Ali")])
    # explicit customer id so the counterparty side resolves cleanly (no pending).
    draft = _build(_base_slots(credit_card_query="Ali's Mellat card", customer_id=7))
    assert draft.valid is True
    assert draft.payload["credit_card_id"] == 12
    assert draft.validation["references_pending"] == []


def test_card_text_two_matches_is_pending_but_valid(swap_resources):
    install, _ = swap_resources
    install("financial_card", [_c(12, "Bank Mellat"), _c(19, "Mellat Pasargad")])
    draft = _build(_base_slots(credit_card_query="mellat", customer_id=7))
    assert draft.valid is True                          # still persisted/streamed
    assert "credit_card_id" not in draft.payload        # not auto-written (ambiguous)
    assert "credit_card_id" in draft.validation["references_pending"]


def test_card_text_no_match_is_missing_with_create_suggestion(swap_resources):
    install, _ = swap_resources
    install("financial_card", [])
    draft = _build(_base_slots(credit_card_query="Nonexistent Bank", customer_id=7))
    refs = draft.validation["references"]
    card_ref = next(r for r in refs if r["field"] == "credit_card_id")
    assert card_ref["status"] == "missing"
    assert card_ref["create_suggestion"]["endpoint"] == "/financial_management/cards"
    assert "credit_card_id" in draft.validation["references_pending"]


def test_explicit_card_id_skips_search(swap_resources):
    install, providers = swap_resources
    card_provider = install("financial_card", [_c(99, "should not be used")])
    install("financial_customer", [])
    draft = _build(_base_slots(credit_card_id=3, customer_id=7))
    assert draft.payload["credit_card_id"] == 3
    assert card_provider.calls == []  # explicit id -> no search


def test_counterparty_text_matches_customer(swap_resources):
    install, _ = swap_resources
    install("financial_customer", [_c(5, "Ali Rezaei", "Ali Rezaei — 0912")])
    draft = _build(_base_slots(credit_card_id=3, counterparty="Ali Rezaei"))
    assert draft.payload["customer_id"] == 5
    assert "counterparty_name" not in draft.payload  # matched -> id used


def test_counterparty_text_no_match_keeps_name(swap_resources):
    install, _ = swap_resources
    install("financial_customer", [])
    draft = _build(_base_slots(credit_card_id=3, counterparty="Bob Unknown"))
    assert draft.payload.get("counterparty_name") == "Bob Unknown"
    assert "customer_id" not in draft.payload
    assert draft.valid is True  # counterparty satisfied by the free-text name
