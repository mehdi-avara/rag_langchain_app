from assistant.tests.fakes import make_user  # sets required test environment

from assistant.redaction import REDACTED, sanitize_payload
from assistant.state import snapshot_state


def test_sensitive_payloads_reasoning_files_and_non_json_objects_are_redacted():
    safe = sanitize_payload({
        "authorization": "Bearer top-secret",
        "nested": {"api_key": "key-123", "password": "pw"},
        "note": "access_token=abc123 harmless tail",
        "extracted_text": "complete uploaded document",
        "file_bytes": b"binary-data",
        "chain_of_thought": "hidden reasoning",
        "object": object(),
    })
    assert safe["authorization"] == REDACTED
    assert safe["nested"]["api_key"] == REDACTED
    assert safe["nested"]["password"] == REDACTED
    assert "abc123" not in safe["note"]
    assert safe["extracted_text"] == REDACTED
    assert safe["file_bytes"] == REDACTED
    assert "chain_of_thought" not in safe
    assert safe["object"] == {"type": "object", "redacted": True}


def test_payload_size_limit_becomes_bounded_metadata():
    safe = sanitize_payload({"rows": [{"value": "x" * 500} for _ in range(100)]}, max_bytes=512)
    assert safe["truncated"] is True
    assert safe["byte_size"] > safe["max_bytes"]
    assert safe["type"] == "dict"


def test_state_snapshot_uses_same_redaction_and_excludes_runtime_objects():
    state = snapshot_state({
        "db": object(), "user": make_user([]), "model_client": object(),
        "request": object(), "question": "Bearer secret-token", "extracted_text": "full file",
        "exception": RuntimeError("credential=secret"), "slots": {"password": "nope"},
    })
    assert not {"db", "user", "model_client", "request", "exception"} & set(state)
    assert "secret-token" not in state["question"]
    assert state["extracted_text"] == REDACTED
    assert state["slots"]["password"] == REDACTED

