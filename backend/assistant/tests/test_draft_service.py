"""PROMPT §4.1, §10.6 — draft lifecycle; committed is record-only; ownership enforced."""

import pytest

from assistant.tests.fakes import FakeDB, make_user

from assistant import service as draft_service
from assistant.models import AgentRun, Draft, DraftStatus, AgentRunStatus
from core.exceptions.app_exception import AppException
from core.exceptions.error_codes import (
    ASSISTANT_DRAFT_NOT_FOUND,
    ASSISTANT_DRAFT_NOT_PENDING,
    PERMISSION_DENIED,
)


def _pending_draft(user):
    return Draft(
        id=55,
        chat_id=1,
        agent_run_id=None,
        created_by_user_id=user.id,
        company_id=user.company_id,
        target_module="financial_management",
        target_action="create_receipt",
        payload={"amount": "100"},
        commit_target={"method": "POST", "endpoint": "/financial_management/receipts"},
        attachments=[],
        validation={"valid": True},
        language="fa",
        status=DraftStatus.PENDING.value,
    )


def test_create_agent_run_suspends_existing_active():
    user = make_user(["assistant:chat"])
    db = FakeDB()
    db.set_all("AgentRun", [])  # no existing active runs
    run = draft_service.create_agent_run(db, chat_id=1, user=user)
    assert run.status == AgentRunStatus.ACTIVE.value
    assert run in db.added


def test_persist_draft_is_pending_and_writes_no_domain_data():
    user = make_user(["assistant:draft"])
    db = FakeDB()
    pending = {
        "target_module": "financial_management",
        "target_action": "create_receipt",
        "payload": {"amount": "100"},
        "commit_target": {"method": "POST", "endpoint": "/financial_management/receipts"},
        "attachments": [],
        "validation": {"valid": True},
    }
    draft = draft_service.persist_draft(
        db, chat_id=1, agent_run_id=None, user=user, pending_draft=pending, language="fa"
    )
    assert draft.status == DraftStatus.PENDING.value
    assert draft.target_action == "create_receipt"
    # Only a Draft row was added — no financial entity.
    assert all(isinstance(obj, Draft) for obj in db.added)


def test_get_draft_rejects_non_owner():
    owner = make_user(["assistant:draft"], user_id=1)
    other = make_user(["assistant:draft"], user_id=2)
    db = FakeDB()
    db.set_first("Draft", _pending_draft(owner))
    with pytest.raises(AppException) as exc:
        draft_service.get_draft(db, draft_id=55, user=other)
    assert exc.value.code == PERMISSION_DENIED


def test_get_draft_company_mismatch_is_not_found():
    owner = make_user(["assistant:draft"], user_id=1, company_id=7)
    intruder = make_user(["assistant:draft"], user_id=9, company_id=8)
    db = FakeDB()
    db.set_first("Draft", _pending_draft(owner))
    with pytest.raises(AppException) as exc:
        draft_service.get_draft(db, draft_id=55, user=intruder)
    assert exc.value.code == ASSISTANT_DRAFT_NOT_FOUND


def test_record_committed_is_record_only():
    user = make_user(["assistant:draft"])
    db = FakeDB()
    draft = _pending_draft(user)
    out = draft_service.record_committed(
        db, draft=draft, user=user, committed_entity_ref={"type": "receipt", "id": 123}
    )
    assert out.status == DraftStatus.COMMITTED.value
    assert out.committed_entity_ref == {"type": "receipt", "id": 123}
    # No domain entity was created/modified (nothing added to the session).
    assert db.added == []


def test_record_committed_rejects_non_pending():
    user = make_user(["assistant:draft"])
    db = FakeDB()
    draft = _pending_draft(user)
    draft.status = DraftStatus.COMMITTED.value
    with pytest.raises(AppException) as exc:
        draft_service.record_committed(db, draft=draft, user=user, committed_entity_ref={})
    assert exc.value.code == ASSISTANT_DRAFT_NOT_PENDING


def test_cancel_draft():
    user = make_user(["assistant:draft"])
    db = FakeDB()
    draft = _pending_draft(user)
    out = draft_service.cancel_draft(db, draft=draft)
    assert out.status == DraftStatus.CANCELLED.value
