"""Staged assistant graph with RBAC-filtered module/task routing.

Flow:

    module_router -> task_finder -> executor -> validator -> end

The executor deliberately reuses the established read/write/help/general/clarify
handlers. The graph never commits domain data; write handlers only build drafts.
"""

from __future__ import annotations

import logging

from langgraph.graph import StateGraph

from . import registry, router
from .state import AgentState

logger = logging.getLogger(__name__)


def _log_context(state: AgentState, **extra) -> dict:
    context = {
        "chat_id": state.get("chat_id"),
        "agent_run_id": state.get("agent_run_id"),
        "user_id": state.get("user_id") or getattr(state.get("user"), "id", None),
        "company_id": state.get("company_id") or getattr(state.get("user"), "company_id", None),
        "selected_module": state.get("selected_module"),
        "selected_task": state.get("selected_task"),
        "intent": state.get("intent"),
    }
    context.update(extra)
    return {key: value for key, value in context.items() if value is not None}


async def module_router_node(state: AgentState) -> AgentState:
    user = state["user"]
    modules = registry.assemble_module_descriptors(user)
    logger.info("assistant.module_router.started", extra=_log_context(state))
    result = await router.classify_module(
        question=state.get("question", ""),
        modules=modules,
        has_attachments=bool(state.get("attachments")),
        image_blocks=state.get("image_blocks") or [],
        history=state.get("history") or [],
        client=state.get("model_client"),
        model=state.get("model_name"),
    )
    selected_module = result.get("module") or "clarify"
    output = {
        **state,
        "selected_module": selected_module,
        "module_confidence": result.get("confidence", 0.0),
        "language": result.get("language") or state.get("language") or "en",
        "clarify_question": result.get("clarify_question"),
        "current_step": "module_router",
        "step_count": int(state.get("step_count", 0)) + 1,
        "loaded_prompt_parts": [
            *(state.get("loaded_prompt_parts") or []),
            "global",
            "module_router",
            "files",
            *(f"module:{item.module}" for item in modules),
        ],
    }
    logger.info(
        "assistant.module_router.selected",
        extra=_log_context(output, confidence=output["module_confidence"]),
    )
    return output


async def task_finder_node(state: AgentState) -> AgentState:
    user = state["user"]
    selected_module = state.get("selected_module") or "clarify"
    logger.info("assistant.task_finder.started", extra=_log_context(state))

    if selected_module == "clarify":
        result = {
            "intent": "clarify",
            "language": state.get("language") or "en",
            "confidence": 0.0,
            "slots": {},
            "clarify_question": state.get("clarify_question"),
        }
        tasks = []
    elif selected_module == "general":
        intent = "assistant_help" if router._looks_like_capability_question(state.get("question", "")) else "general"
        result = {
            "intent": intent,
            "language": state.get("language") or "en",
            "confidence": state.get("module_confidence", 0.0),
            "slots": {},
            "clarify_question": None,
        }
        tasks = []
    else:
        toolset = registry.get_toolset(selected_module)
        module_descriptor = toolset.module_descriptor() if toolset is not None else None
        tasks = registry.assemble_task_descriptors(user, selected_module)
        if module_descriptor is None or not tasks:
            result = {
                "intent": "clarify",
                "language": state.get("language") or "en",
                "confidence": 0.0,
                "slots": {},
                "clarify_question": state.get("clarify_question"),
            }
        else:
            result = await router.classify_task(
                question=state.get("question", ""),
                module=module_descriptor,
                tasks=tasks,
                has_attachments=bool(state.get("attachments")),
                image_blocks=state.get("image_blocks") or [],
                history=state.get("history") or [],
                client=state.get("model_client"),
                model=state.get("model_name"),
            )

    slots = dict(state.get("slots") or {})
    slots.update(result.get("slots") or {})
    selected_task = result.get("intent") or "clarify"
    selected_toolset = registry.get_toolset(selected_module)
    specialist_instructions = (
        list(selected_toolset.specialist_instructions(selected_task))
        if selected_toolset is not None and selected_task != "clarify"
        else []
    )
    output = {
        **state,
        "selected_task": selected_task,
        "intent": selected_task,
        "task_confidence": result.get("confidence", 0.0),
        "language": result.get("language") or state.get("language") or "en",
        "slots": slots,
        "specialist_instructions": specialist_instructions,
        "clarify_question": result.get("clarify_question") or state.get("clarify_question"),
        "current_step": "task_finder",
        "step_count": int(state.get("step_count", 0)) + 1,
        "loaded_prompt_parts": [
            *(state.get("loaded_prompt_parts") or []),
            "task_finder",
            *(f"task:{item.intent}" for item in tasks),
            *( [f"specialist:{selected_module}:{selected_task}"] if selected_task != "clarify" else [] ),
        ],
    }
    logger.info(
        "assistant.task_finder.selected",
        extra=_log_context(output, confidence=output["task_confidence"]),
    )
    return output


def _resolve_kind(state: AgentState) -> str:
    user = state["user"]
    intent = state.get("selected_task") or state.get("intent")
    spec = registry.find_intent(user, intent) if intent else None
    if intent == "assistant_help":
        return "help"
    if intent == "general":
        return "general"
    if spec is None:
        return "clarify"
    if spec.kind in {"write", "file"}:
        return "write"
    if spec.kind == "read":
        return "read"
    if spec.kind == "help":
        return "help"
    if spec.kind == "general":
        return "general"
    return "clarify"


async def read_node(state: AgentState) -> AgentState:
    user, db = state["user"], state["db"]
    intent = state.get("selected_task") or state["intent"]
    spec = registry.find_intent(user, intent)
    if spec is None or spec.module != state.get("selected_module"):
        return await clarify_node({**state, "clarify_question": "Could you clarify what you want to do?"})
    toolset = registry.get_toolset(spec.module)
    result = await toolset.handle_read(intent=intent, db=db, user=user, slots=state.get("slots") or {})
    return {
        **state,
        "current_step": intent,
        "retrieved_items": result.get("retrieved_items") or [],
        "summary": result.get("summary"),
        "answer": result.get("answer") or "",
        "citations": result.get("citations") or [],
        "tool_calls": [
            *(state.get("tool_calls") or []),
            {"module": spec.module, "intent": intent, "kind": "read"},
        ],
    }


async def write_node(state: AgentState) -> AgentState:
    user, db = state["user"], state["db"]
    intent = state.get("selected_task") or state["intent"]
    spec = registry.find_intent(user, intent)
    if spec is None or spec.module != state.get("selected_module"):
        return await clarify_node({**state, "clarify_question": "Could you clarify what you want to change?"})
    toolset = registry.get_toolset(spec.module)
    slots = dict(state.get("slots") or {})
    active_partial = state.get("active_partial_draft") or {}
    if active_partial.get("target_action") == spec.target_action:
        merged_slots = dict(active_partial.get("payload") or {})
        merged_slots.update(slots)
        slots = merged_slots

    draft_data = toolset.build_draft(
        intent=intent,
        db=db,
        user=user,
        slots=slots,
        attachments=state.get("attachments") or [],
    )
    tool_calls = [
        *(state.get("tool_calls") or []),
        {"module": spec.module, "intent": intent, "kind": "draft_builder"},
    ]
    if not draft_data.valid:
        clarify_question = draft_data.clarify_question or "Could you provide the missing details?"
        return {
            **state,
            "current_step": intent,
            "intent": "clarify",
            "clarify_question": clarify_question,
            "pending_draft": None,
            "partial_draft": {
                "target_module": draft_data.target_module,
                "target_action": draft_data.target_action,
                "payload": draft_data.payload,
                "missing": draft_data.validation.get("missing", []),
                "validation": draft_data.validation,
            },
            "answer": clarify_question,
            "tool_calls": tool_calls,
        }

    return {
        **state,
        "current_step": intent,
        "pending_draft": {
            "target_module": draft_data.target_module,
            "target_action": draft_data.target_action,
            "payload": draft_data.payload,
            "commit_target": draft_data.commit_target,
            "attachments": draft_data.attachments,
            "validation": draft_data.validation,
        },
        "partial_draft": None,
        "answer": "",
        "tool_calls": tool_calls,
    }


async def general_node(state: AgentState) -> AgentState:
    return {**state, "current_step": "general", "retrieved_items": [], "citations": [], "answer": ""}


def _help_answer(state: AgentState) -> str:
    specs = [
        spec for spec in registry.assemble_intents(state["user"])
        if spec.kind in {"read", "write", "file"}
    ]
    if not specs:
        return "I can answer general questions, but no module actions are currently available with your permissions."
    read_names = [spec.name for spec in specs if spec.kind == "read"]
    write_names = [spec.name for spec in specs if spec.kind in {"write", "file"}]
    parts = ["I can help with the actions available to your account."]
    if read_names:
        parts.append("Read/search: " + ", ".join(read_names) + ".")
    if write_names:
        parts.append("Drafts for review: " + ", ".join(write_names) + ".")
    parts.append("For writes, I prepare a draft first; you review and confirm before anything changes.")
    return " ".join(parts)


async def help_node(state: AgentState) -> AgentState:
    return {
        **state,
        "current_step": "assistant_help",
        "intent": "assistant_help",
        "answer": _help_answer(state),
        "retrieved_items": [],
        "citations": [],
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


async def executor_node(state: AgentState) -> AgentState:
    logger.info("assistant.executor.started", extra=_log_context(state))
    kind = _resolve_kind(state)
    handler = {
        "read": read_node,
        "write": write_node,
        "help": help_node,
        "general": general_node,
        "clarify": clarify_node,
    }[kind]
    output = await handler(state)
    logger.info("assistant.executor.completed", extra=_log_context(output, task_kind=kind))
    return output


def _clarify_invalid(state: AgentState, errors: list[str]) -> AgentState:
    question = state.get("clarify_question") or "I need a little more information to continue safely."
    return {
        **state,
        "intent": "clarify",
        "pending_draft": None,
        "clarify_question": question,
        "answer": question,
        "validation_result": {"valid": False, "errors": errors, "outcome": "clarify"},
    }


async def validator_node(state: AgentState) -> AgentState:
    errors: list[str] = []
    output: AgentState = state
    selected_task = state.get("selected_task")
    spec = registry.find_intent(state["user"], selected_task) if selected_task else None
    kind = spec.kind if spec is not None else ("general" if selected_task in {"general", "assistant_help"} else "clarify")

    if kind in {"write", "file"}:
        pending, partial = state.get("pending_draft"), state.get("partial_draft")
        if pending:
            required = {"target_module", "target_action", "payload", "commit_target", "validation"}
            missing = sorted(required - set(pending))
            if missing:
                errors.append("pending_draft missing: " + ", ".join(missing))
            if pending.get("target_module") != spec.module:
                errors.append("pending_draft target_module does not match selected task")
            if spec.target_action and pending.get("target_action") != spec.target_action:
                errors.append("pending_draft target_action does not match selected task")
            if not isinstance(pending.get("payload"), dict):
                errors.append("pending_draft payload must be an object")
            commit_target = pending.get("commit_target") if isinstance(pending.get("commit_target"), dict) else {}
            target_missing = sorted(
                key for key in {"method", "endpoint", "permission"}
                if not isinstance(commit_target.get(key), str) or not commit_target.get(key).strip()
            )
            if target_missing:
                errors.append("commit_target missing: " + ", ".join(target_missing))
            if commit_target.get("permission") and commit_target.get("permission") != spec.permission:
                errors.append("commit_target permission does not match selected task")
            validation = pending.get("validation") if isinstance(pending.get("validation"), dict) else {}
            if validation.get("valid") is not True:
                errors.append("pending_draft validation is not valid")
            if "committed_entity_ref" in pending or pending.get("status") == "committed":
                errors.append("executor returned a committed domain result")
            if any(
                call.get("kind") in {"commit", "domain_write"}
                for call in state.get("tool_calls") or []
                if isinstance(call, dict)
            ):
                errors.append("executor attempted a domain write")
        elif not partial:
            errors.append("write task returned neither pending_draft nor partial_draft")
        if errors:
            output = _clarify_invalid(state, errors)
        elif partial:
            output = {
                **state,
                "intent": "clarify",
                "validation_result": {"valid": True, "errors": [], "outcome": "partial_draft"},
            }
        else:
            output = {
                **state,
                "validation_result": {"valid": True, "errors": [], "outcome": "pending_draft"},
            }
            logger.info("assistant.draft.created", extra=_log_context(output, target_action=pending.get("target_action")))
    elif kind == "read":
        items = state.get("retrieved_items") or []
        citations = state.get("citations") or []
        if items and not citations:
            citations = [item.get("citation_key") for item in items if isinstance(item, dict) and item.get("citation_key")]
        output = {
            **state,
            "citations": citations,
            "validation_result": {"valid": True, "errors": [], "outcome": "read"},
        }
    elif kind in {"general", "help"}:
        output = {**state, "validation_result": {"valid": True, "errors": [], "outcome": kind}}
    else:
        output = {
            **state,
            "intent": "clarify",
            "answer": state.get("answer") or state.get("clarify_question") or "Could you clarify your request?",
            "validation_result": {"valid": True, "errors": [], "outcome": "clarify"},
        }

    if output.get("intent") == "clarify":
        logger.info("assistant.clarification.required", extra=_log_context(output))
    logger.info(
        "assistant.validator.completed",
        extra=_log_context(output, validation_outcome=output.get("validation_result", {}).get("outcome")),
    )
    return output


def end_node(state: AgentState) -> AgentState:
    return state


# Compatibility names for imports from the previous graph implementation.
router_node = module_router_node


def build_assistant_graph():
    workflow = StateGraph(AgentState)
    workflow.add_node("module_router", module_router_node)
    workflow.add_node("task_finder", task_finder_node)
    workflow.add_node("executor", executor_node)
    workflow.add_node("validator", validator_node)
    workflow.add_node("end", end_node)
    workflow.add_edge("module_router", "task_finder")
    workflow.add_edge("task_finder", "executor")
    workflow.add_edge("executor", "validator")
    workflow.add_edge("validator", "end")
    workflow.set_entry_point("module_router")
    workflow.set_finish_point("end")
    return workflow.compile()
