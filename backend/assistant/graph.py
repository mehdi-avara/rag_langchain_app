"""Assistant LangGraph control flow (PROMPT §8).

Modelled on the seed agent (``core/agents/langgraph.py``): a ``StateGraph`` with
typed state and async nodes. Flow:

    router -> (read | write | general | clarify) -> decide_next -> end

The graph produces **structured** results (intent, retrieved_items, summary,
pending_draft, citations) and, where cheap, the answer text. The runner streams
the final NL answer and emits the structured payloads as whole objects (§8.2).

The graph NEVER commits a write — reaching a write step ends the turn with
``pending_draft`` set (PROMPT §4). RBAC is enforced inside the handlers, which
re-check the permission before calling a service / building a draft (§5).
"""

from __future__ import annotations

import logging

from langgraph.graph import StateGraph

from . import registry, router
from .state import MAX_STEPS, AgentState

logger = logging.getLogger(__name__)


async def router_node(state: AgentState) -> AgentState:
    user = state["user"]
    question = state.get("question", "")
    attachments = state.get("attachments") or []

    intents = registry.assemble_intents(user)
    result = await router.classify(
        question=question,
        intents=intents,
        has_attachments=bool(attachments),
    )

    # Merge router-extracted slots with any pre-seeded slots (e.g. ids from the request).
    slots = dict(state.get("slots") or {})
    slots.update(result.get("slots") or {})

    return {
        **state,
        "intent": result["intent"],
        "language": result.get("language") or state.get("language") or "en",
        "slots": slots,
        "clarify_question": result.get("clarify_question"),
        "current_step": "router",
        "step_count": int(state.get("step_count", 0)) + 1,
    }


def _resolve_kind(state: AgentState) -> str:
    user = state["user"]
    intent = state.get("intent")
    spec = registry.find_intent(user, intent) if intent else None
    if spec is None:
        return "clarify"
    if spec.kind in {"write", "file"}:
        return "write"
    if spec.kind == "read":
        return "read"
    if spec.kind == "general":
        return "general"
    return "clarify"


async def read_node(state: AgentState) -> AgentState:
    user = state["user"]
    db = state["db"]
    intent = state["intent"]
    spec = registry.find_intent(user, intent)
    toolset = registry.get_toolset(spec.module)

    result = await toolset.handle_read(intent=intent, db=db, user=user, slots=state.get("slots") or {})

    return {
        **state,
        "current_step": intent,
        "retrieved_items": result.get("retrieved_items") or [],
        "summary": result.get("summary"),
        "answer": result.get("answer") or "",
        "citations": result.get("citations") or [],
    }


async def write_node(state: AgentState) -> AgentState:
    user = state["user"]
    db = state["db"]
    intent = state["intent"]
    spec = registry.find_intent(user, intent)
    toolset = registry.get_toolset(spec.module)

    draft_data = toolset.build_draft(
        intent=intent,
        db=db,
        user=user,
        slots=state.get("slots") or {},
        attachments=state.get("attachments") or [],
    )

    if not draft_data.valid:
        # Prefer clarify over an un-committable draft (PROMPT §3).
        return {
            **state,
            "current_step": intent,
            "intent": "clarify",
            "clarify_question": draft_data.clarify_question or "Could you provide the missing details?",
            "pending_draft": None,
            "answer": "",
        }

    pending_draft = {
        "target_module": draft_data.target_module,
        "target_action": draft_data.target_action,
        "payload": draft_data.payload,
        "commit_target": draft_data.commit_target,
        "attachments": draft_data.attachments,
        "validation": draft_data.validation,
    }

    return {
        **state,
        "current_step": intent,
        "pending_draft": pending_draft,
        "answer": "",
    }


async def general_node(state: AgentState) -> AgentState:
    # The model's own knowledge — the runner streams this from the model and the
    # frontend marks it as model knowledge (cite nothing).
    return {
        **state,
        "current_step": "general",
        "retrieved_items": [],
        "citations": [],
        "answer": "",
    }


async def clarify_node(state: AgentState) -> AgentState:
    question = state.get("clarify_question") or "Could you clarify your request?"
    return {
        **state,
        "current_step": "clarify",
        "intent": "clarify",
        "answer": question,
        "retrieved_items": [],
        "citations": [],
    }


def decide_next(state: AgentState) -> AgentState:
    # Single-step taxonomy for Phase 0: each handler completes the turn. The
    # step_count cap guards against runaway loops if this is extended (§8).
    next_step = None if int(state.get("step_count", 0)) >= MAX_STEPS else None
    return {**state, "next_step": next_step}


def end_node(state: AgentState) -> AgentState:
    return state


def build_assistant_graph():
    workflow = StateGraph(AgentState)

    workflow.add_node("router", router_node)
    workflow.add_node("read", read_node)
    workflow.add_node("write", write_node)
    workflow.add_node("general", general_node)
    workflow.add_node("clarify", clarify_node)
    workflow.add_node("decide_next", decide_next)
    workflow.add_node("end", end_node)

    workflow.add_conditional_edges(
        "router",
        _resolve_kind,
        {
            "read": "read",
            "write": "write",
            "general": "general",
            "clarify": "clarify",
        },
    )

    for handler in ("read", "write", "general", "clarify"):
        workflow.add_edge(handler, "decide_next")

    workflow.add_edge("decide_next", "end")
    workflow.set_entry_point("router")
    workflow.set_finish_point("end")

    return workflow.compile()
