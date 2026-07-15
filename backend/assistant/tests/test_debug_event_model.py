import importlib.util
from pathlib import Path

from assistant.tests.fakes import make_user  # noqa: F401 - initializes env

import Models
from assistant.models import AgentRun, AssistantEvent
from db.base import Base


def test_assistant_event_metadata_registration_constraints_and_run_links():
    assert Models.AssistantEvent is AssistantEvent
    assert Base.metadata.tables["assistant_events"] is AssistantEvent.__table__
    assert {
        "chat_id", "agent_run_id", "message_id", "company_id", "user_id", "sequence",
        "event_type", "stage", "status", "severity", "payload", "duration_ms", "error_code",
    } <= set(AssistantEvent.__table__.c.keys())
    assert {
        "input_message_id", "output_message_id", "current_stage", "last_event_sequence",
        "started_at", "completed_at", "user_id",
    } <= set(AgentRun.__table__.c.keys())
    constraints = {constraint.name for constraint in AssistantEvent.__table__.constraints}
    run_constraints = {constraint.name for constraint in AgentRun.__table__.constraints}
    indexes = {index.name for index in AssistantEvent.__table__.indexes}
    assert "uq_assistant_events_agent_run_id_sequence" in constraints
    assert "uq_assistant_agent_runs_input_message_id" in run_constraints
    assert "ix_assistant_events_company_chat_created" in indexes
    assert "ix_assistant_events_run_sequence" in indexes


class _MigrationRecorder:
    def __init__(self):
        self.calls = []

    def __getattr__(self, name):
        def call(*args, **kwargs):
            self.calls.append((name, args, kwargs))
        return call


def test_migration_upgrade_adds_run_links_counter_backfill_and_event_table(monkeypatch):
    path = Path(__file__).parents[2] / "alembic/versions/5f6a7b8c9d0a_add_assistant_debug_events.py"
    spec = importlib.util.spec_from_file_location("assistant_debug_migration", path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    recorder = _MigrationRecorder()
    monkeypatch.setattr(module, "op", recorder)
    module.upgrade()

    assert module.down_revision == "4e5f6a7b8c9"
    added = [args[1].name for name, args, _ in recorder.calls if name == "add_column"]
    assert {"input_message_id", "output_message_id", "current_stage", "last_event_sequence"} <= set(added)
    assert any(name == "execute" and "created_by_user_id" in args[0] for name, args, _ in recorder.calls)
    assert any(name == "create_table" and args[0] == "assistant_events" for name, args, _ in recorder.calls)
