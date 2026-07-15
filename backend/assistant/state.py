"""The LangGraph graph state (PROMPT §8).

This ``AgentState`` (the live graph state) is distinct from the persisted
``AgentRun.status`` lifecycle. ``user`` / ``db`` / ``company_id`` are threaded
through every node so RBAC and scoping are always enforced (§5); never fetch a
privileged session inside a node.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional, TypedDict

from sqlalchemy.orm import Session

from Models import User
from settings import get_settings

from .redaction import sanitize_payload


class AgentState(TypedDict, total=False):
    # --- identity & request context (set once at entry) ---
    chat_id: int
    agent_run_id: int
    agent_run: Any                  # runtime-only ORM row; never snapshotted
    input_message_id: int
    user: User                      # carried into every node for RBAC (§5)
    user_id: int
    company_id: int
    db: Session                     # request-scoped session
    language: str                   # detected user language, BCP-47

    # --- the current turn's input ---
    question: str
    history: List[dict]             # recent prior chat messages as {role, content}
    rewritten_query: Optional[str]
    attachments: List[int]          # FileAsset ids attached to this message (§6)
    model_is_vlm: bool              # active chat model supports vision (§7)
    model_client: Any               # resolved AsyncOpenAI client (from ChatAIModels row)
    model_name: str                 # resolved model name (from ChatAIModels row)

    # --- router output ---
    selected_module: str
    selected_task: str
    module_confidence: float
    task_confidence: float
    intent: str
    slots: dict
    clarify_question: Optional[str]
    loaded_prompt_parts: List[str]
    specialist_instructions: List[str]

    # --- planning / multi-step control ---
    plan: List[str]
    current_step: str
    next_step: Optional[str]
    step_count: int

    # --- results produced by handlers ---
    retrieved_items: List[dict]
    summary: Optional[dict]
    pending_draft: Optional[dict]   # built but NOT committed
    partial_draft: Optional[dict]   # incomplete write: object-so-far + missing field nouns
    active_partial_draft: Optional[dict]  # latest incomplete draft from prior turn
    answer: str
    citations: List[Any]
    tool_calls: List[dict]
    validation_result: dict

    # --- file intake bookkeeping (§6/§7) ---
    intake_mode: Optional[str]      # inline | heavy | None
    extracted_text: Optional[str]
    image_blocks: List[dict]        # only when model_is_vlm

    # --- async / interruption ---
    task_id: Optional[str]
    error_code: Optional[str]


# Keys that must never be serialised into AgentRun.state (non-JSON / privileged).
NON_SERIALISABLE_KEYS = {
    "db", "user", "model_client", "agent_run", "request", "session",
    "exception", "raw_exception",
}

# A hard cap to prevent runaway loops in decide_next (PROMPT §8 note).
MAX_STEPS = 8


def snapshot_state(state: AgentState) -> dict:
    """Return a JSON-safe snapshot of the graph state for AgentRun.state."""
    filtered = {
        key: value
        for key, value in state.items()
        if key not in NON_SERIALISABLE_KEYS
    }
    safe = sanitize_payload(
        filtered,
        max_bytes=get_settings().assistant_state_snapshot_max_bytes,
    )
    return safe if isinstance(safe, dict) else {"value": safe}
