"""FK-resolution task — patch_draft create-callback + lookup_customer/lookup_card intents."""

import asyncio

import pytest

from assistant.tests.fakes import ALL_FINANCIAL_PERMS, FakeDB, FakeProvider, make_user

from assistant import service as draft_service
from assistant import registry
from assistant.models import Draft, DraftStatus
from assistant.module_interface import Candidate, ResourceSpec, get_resource, register_resource
import financial_management.assistant_tools as ft  # noqa: F401 (registers resources/toolset)

toolset = ft.FinancialAssistantToolSet()


def _c(cid, match_text, label=None):
    return Candidate(id=cid, match_text=match_text, label=label or match_text)


# ---------------------------------------------------------------------------
# patch_draft create-callback
# ---------------------------------------------------------------------------

def _pending_with_reference(user):
    return Draft(
        id=70,
        chat_id=1,
        agent_run_id=None,
        created_by_user_id=user.id,
        company_id=user.company_id,
        target_module="financial_management",
        target_action="create_receipt",
        payload={"amount": "100"},
        commit_target={"method": "POST", "endpoint": "/financial_management/receipts"},
        attachments=[],
        validation={
            "valid": True,
            "references": [{
                "field": "credit_card_id", "raw": "Mellat", "status": "missing",
                "chosen": None, "alternatives": [], "create_suggestion": {}, "note": None,
            }],
            "references_pending": ["credit_card_id"],
        },
        language="fa",
        status=DraftStatus.PENDING.value,
    )


def test_patch_draft_callback_writes_id_and_clears_pending():
    user = make_user(["assistant:draft"])
    db = FakeDB()
    draft = _pending_with_reference(user)

    out = draft_service.patch_draft(
        db,
        draft=draft,
        resolved_references={"credit_card_id": {"id": 12, "label": "Mellat — ••••4821"}},
    )

    assert out.payload["credit_card_id"] == 12
    ref = out.validation["references"][0]
    assert ref["status"] == "resolved"
    assert ref["chosen"] == {"id": 12, "label": "Mellat — ••••4821"}
    assert out.validation["references_pending"] == []


def test_patch_draft_callback_ignores_malformed_entries():
    user = make_user(["assistant:draft"])
    db = FakeDB()
    draft = _pending_with_reference(user)
    out = draft_service.patch_draft(
        db, draft=draft, resolved_references={"credit_card_id": {"label": "no id here"}}
    )
    # No id -> skipped; pending unchanged.
    assert "credit_card_id" not in out.payload
    assert out.validation["references_pending"] == ["credit_card_id"]


# ---------------------------------------------------------------------------
# lookup intents
# ---------------------------------------------------------------------------

@pytest.fixture
def swap_customer_provider():
    saved = get_resource("financial_customer")
    provider_holder = {}

    def install(candidates):
        provider = FakeProvider(candidates)
        provider_holder["p"] = provider
        register_resource(ResourceSpec(
            key="financial_customer",
            read_permission=saved.read_permission,
            provider=provider,
            create_permission=saved.create_permission,
            create_endpoint=saved.create_endpoint,
            create_method=saved.create_method,
            suggestion_from=saved.suggestion_from,
        ))
        return provider

    yield install
    if saved is not None:
        register_resource(saved)


def test_lookup_customer_returns_items_with_labels(swap_customer_provider):
    swap_customer_provider([
        _c(5, "Ali Rezaei", "Ali Rezaei — 0912"),
        _c(6, "Ali Akbari", "Ali Akbari — 0935"),
    ])
    user = make_user(ALL_FINANCIAL_PERMS)
    out = asyncio.run(
        toolset.handle_read(intent="lookup_customer", db=None, user=user, slots={"query": "Ali"})
    )
    assert [i["citation_key"] for i in out["retrieved_items"]] == ["customer:5", "customer:6"]
    assert out["retrieved_items"][0]["title"] == "Ali Rezaei — 0912"
    assert out["answer"] == ""  # model composes the NL reply from items


def test_lookup_intents_dropped_without_read_permission():
    perms = [p for p in ALL_FINANCIAL_PERMS if p != "financial_management:customers:read"]
    user = make_user(perms)
    names = {spec.name for spec in registry.assemble_intents(user)}
    assert "lookup_customer" not in names
    # A card lookup the user still holds remains available.
    assert "lookup_card" in names
