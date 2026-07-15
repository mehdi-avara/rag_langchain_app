from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from threading import Lock

from assistant.tests.fakes import make_user  # noqa: F401 - initializes env

from assistant.models import AgentRun, AssistantEvent
from assistant.observability import list_run_events, record_event, record_model_call, record_route, record_tool_call


class _ScalarResult:
    def __init__(self, value):
        self.value = value

    def scalar_one_or_none(self):
        return self.value


class AtomicSession:
    def __init__(self):
        self.lock = Lock()
        self.counter = 0
        self.events = []
        self.next_id = 1

    def execute(self, statement):
        # Production sends one UPDATE assistant_agent_runs ... RETURNING statement.
        assert "UPDATE assistant_agent_runs" in str(statement)
        assert "RETURNING" in str(statement)
        with self.lock:
            self.counter += 1
            return _ScalarResult(self.counter)

    def add(self, event):
        with self.lock:
            event.id = self.next_id
            self.next_id += 1
            event.created_at = datetime.utcnow()
            self.events.append(event)

    def commit(self):
        pass

    def refresh(self, event):
        pass


def _run():
    return AgentRun(
        id=11, chat_id=4, created_by_user_id=2, user_id=2, company_id=7,
        input_message_id=41, status="active", last_event_sequence=0,
    )


def test_concurrent_sequence_allocation_is_unique_and_orderable():
    db, run = AtomicSession(), _run()

    def write(index):
        return record_event(db, run, event_type="tool.completed", stage="executor", payload={"index": index})

    with ThreadPoolExecutor(max_workers=8) as pool:
        events = list(pool.map(write, range(50)))

    sequences = sorted(event.sequence for event in events)
    assert sequences == list(range(1, 51))
    assert len({(event.agent_run_id, event.sequence) for event in events}) == 50
    assert all(event.message_id == 41 for event in events)


class Query:
    def __init__(self, rows):
        self.rows = list(rows)

    def filter(self, *clauses):
        for clause in clauses:
            key = clause.left.key
            value = clause.right.value
            if clause.operator.__name__ == "gt":
                self.rows = [row for row in self.rows if getattr(row, key) > value]
            else:
                self.rows = [row for row in self.rows if getattr(row, key) == value]
        return self

    def order_by(self, *args):
        self.rows.sort(key=lambda row: row.sequence)
        return self

    def limit(self, value):
        self.rows = self.rows[:value]
        return self

    def all(self):
        return self.rows


class QuerySession:
    def __init__(self, rows):
        self.rows = rows

    def query(self, model):
        assert model is AssistantEvent
        return Query(self.rows)


def test_cursor_tenant_and_run_filters_never_mix_events():
    rows = [
        AssistantEvent(id=1, agent_run_id=1, company_id=7, sequence=1),
        AssistantEvent(id=2, agent_run_id=1, company_id=7, sequence=2),
        AssistantEvent(id=3, agent_run_id=2, company_id=7, sequence=3),
        AssistantEvent(id=4, agent_run_id=1, company_id=8, sequence=4),
    ]
    result = list_run_events(QuerySession(rows), run_id=1, company_id=7, after_sequence=1, limit=100)
    assert [(event.agent_run_id, event.company_id, event.sequence) for event in result] == [(1, 7, 2)]


def test_structured_route_model_tool_cross_module_draft_and_validation_events():
    db, run = AtomicSession(), _run()
    record_route(
        db, run, event_type="task_finder.selected", stage="task_finder",
        route_from="purchase_management", route_to="create_purchase_request",
        selected_module="purchase_management", selected_task="create_purchase_request",
        confidence=0.91, allowed_candidates=["create_purchase_request", "search_purchase_orders"],
        decision_summary="Selected the permitted purchase-request draft task.",
    )
    record_model_call(
        db, run, stage="task_finder", status="completed", provider="openai_compatible",
        model="router-model", input_tokens=10, output_tokens=4, total_tokens=14,
        prompt_version="task-finder-v1", prompt_digest="abc", response_format="json_object",
    )
    record_tool_call(
        db, run, stage="executor", status="completed", tool_identifier="purchase.create_request",
        owning_module="purchase_management", operation="create_purchase_request",
        input_summary={"field_names": ["item_id"]}, output_summary={"draft_fields": 4},
        produced_draft=True, searched_another_module=True,
    )
    record_event(
        db, run, event_type="cross_module_search.started", stage="executor", status="started",
        payload={"candidate_identifiers": ["material_management"]},
    )
    record_event(
        db, run, event_type="cross_module_search.completed", stage="executor",
        payload={"searched_modules": ["material_management"], "result_count": 1},
    )
    record_event(db, run, event_type="draft.created", stage="validator", payload={"draft_id": 5})
    record_event(db, run, event_type="validator.completed", stage="validator", payload={"valid": True})

    assert [event.event_type for event in db.events] == [
        "task_finder.selected", "model.completed", "tool.completed",
        "cross_module_search.started", "cross_module_search.completed",
        "draft.created", "validator.completed",
    ]
    route_payload = db.events[0].payload
    assert route_payload["confidence"] == 0.91
    assert route_payload["allowed_candidates"] == ["create_purchase_request", "search_purchase_orders"]
    assert "reasoning" not in route_payload
    tool_payload = db.events[2].payload
    assert tool_payload["produced_draft"] is True
    assert tool_payload["searched_another_module"] is True
