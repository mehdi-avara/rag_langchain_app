"""Staged assistant graph with RBAC-filtered module/task routing.

Flow:

    module_router -> task_finder -> executor -> validator -> end

The executor deliberately reuses the established read/write/help/general/clarify
handlers. The graph never commits domain data; write handlers only build drafts.
"""

from __future__ import annotations

import logging
import re
from time import perf_counter

from langgraph.graph import StateGraph
from core.exceptions import AppException
from core.exceptions.error_codes import INTERNAL_SERVER_ERROR

from . import observability, prompt_builder, registry, router
from .state import AgentState, snapshot_state

logger = logging.getLogger(__name__)


def _observable(state: AgentState):
    db, run = state.get("db"), state.get("agent_run")
    return (db, run) if db is not None and run is not None else (None, None)


def _error_code(exc: BaseException) -> str:
    return exc.code if isinstance(exc, AppException) else INTERNAL_SERVER_ERROR


def _record_failure(state: AgentState, callback, /, *args, **kwargs) -> None:
    """Preserve the original assistant exception if failure recording also fails."""
    try:
        callback(*args, **kwargs)
    except Exception:  # pragma: no cover - only a broken observability transaction
        logger.exception("assistant observability failure while preserving original exception", extra=_log_context(state))


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
    db, run = _observable(state)
    started = perf_counter()
    messages = prompt_builder.build_module_router_messages(
        question=state.get("question", ""), modules=modules,
        history=state.get("history"), has_attachments=bool(state.get("attachments")),
        image_blocks=state.get("image_blocks") or [],
    )
    if run is not None:
        observability.start_step(
            db, run, stage="module_router", event_type="module_router.started",
            state=snapshot_state(state), payload={"allowed_candidates": [item.module for item in modules]},
        )
        observability.record_model_call(
            db, run, stage="module_router", status="started", provider="openai_compatible",
            model=state.get("model_name") or "configured", prompt_version="module-router-v1",
            prompt_digest=observability.prompt_hash(messages), response_format="json_object",
        )
    logger.info("assistant.module_router.started", extra=_log_context(state))
    try:
        result = await router.classify_module(
            question=state.get("question", ""),
            modules=modules,
            has_attachments=bool(state.get("attachments")),
            image_blocks=state.get("image_blocks") or [],
            history=state.get("history") or [],
            client=state.get("model_client"),
            model=state.get("model_name"),
        )
    except Exception as exc:
        if run is not None:
            elapsed = observability.duration_ms(started)
            _record_failure(
                state, observability.record_model_call, db, run, stage="module_router", status="failed",
                provider="openai_compatible", model=state.get("model_name") or "configured",
                elapsed_ms=elapsed, prompt_version="module-router-v1",
                prompt_digest=observability.prompt_hash(messages), response_format="json_object",
                error_code=_error_code(exc),
            )
            _record_failure(
                state, observability.fail_step, db, run, stage="module_router",
                event_type="module_router.failed", error_code=_error_code(exc), elapsed_ms=elapsed,
                state=snapshot_state(state),
            )
        raise
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
    if run is not None:
        elapsed = observability.duration_ms(started)
        metadata = result.get("_model_call") or {}
        observability.record_model_call(
            db, run, stage="module_router", status="completed",
            provider=metadata.get("provider") or "openai_compatible",
            model=metadata.get("model") or state.get("model_name") or "configured",
            elapsed_ms=elapsed, input_tokens=metadata.get("input_tokens"),
            output_tokens=metadata.get("output_tokens"), total_tokens=metadata.get("total_tokens"),
            prompt_version="module-router-v1", prompt_digest=observability.prompt_hash(messages),
            response_format="json_object",
        )
        observability.record_route(
            db, run, event_type="module_router.selected", stage="module_router",
            route_from="chat", route_to=selected_module, selected_module=selected_module,
            confidence=output["module_confidence"],
            allowed_candidates=[item.module for item in modules] + ["general", "clarify"],
            decision_summary=f"Selected module {selected_module} from the permitted module catalog.",
            elapsed_ms=elapsed,
        )
        run.state = snapshot_state(output)
        db.commit()
    return output


async def task_finder_node(state: AgentState) -> AgentState:
    user = state["user"]
    selected_module = state.get("selected_module") or "clarify"
    db, run = _observable(state)
    started = perf_counter()
    if run is not None:
        observability.start_step(
            db, run, stage="task_finder", event_type="task_finder.started",
            state=snapshot_state(state), payload={"selected_module": selected_module},
        )
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
            messages = prompt_builder.build_task_finder_messages(
                question=state.get("question", ""), module=module_descriptor, tasks=tasks,
                history=state.get("history"), has_attachments=bool(state.get("attachments")),
                image_blocks=state.get("image_blocks") or [],
            )
            if run is not None:
                observability.record_model_call(
                    db, run, stage="task_finder", status="started", provider="openai_compatible",
                    model=state.get("model_name") or "configured", prompt_version="task-finder-v1",
                    prompt_digest=observability.prompt_hash(messages), response_format="json_object",
                )
            try:
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
            except Exception as exc:
                if run is not None:
                    elapsed = observability.duration_ms(started)
                    _record_failure(
                        state, observability.record_model_call, db, run, stage="task_finder",
                        status="failed", provider="openai_compatible",
                        model=state.get("model_name") or "configured", elapsed_ms=elapsed,
                        prompt_version="task-finder-v1", prompt_digest=observability.prompt_hash(messages),
                        response_format="json_object", error_code=_error_code(exc),
                    )
                    _record_failure(
                        state, observability.fail_step, db, run, stage="task_finder",
                        event_type="task_finder.failed", error_code=_error_code(exc), elapsed_ms=elapsed,
                        state=snapshot_state(state),
                    )
                raise
            if run is not None:
                metadata = result.get("_model_call") or {}
                observability.record_model_call(
                    db, run, stage="task_finder", status="completed",
                    provider=metadata.get("provider") or "openai_compatible",
                    model=metadata.get("model") or state.get("model_name") or "configured",
                    elapsed_ms=observability.duration_ms(started), input_tokens=metadata.get("input_tokens"),
                    output_tokens=metadata.get("output_tokens"), total_tokens=metadata.get("total_tokens"),
                    prompt_version="task-finder-v1", prompt_digest=observability.prompt_hash(messages),
                    response_format="json_object",
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
    if run is not None:
        elapsed = observability.duration_ms(started)
        observability.record_route(
            db, run, event_type="task_finder.selected", stage="task_finder",
            route_from=selected_module, route_to=selected_task,
            selected_module=selected_module, selected_task=selected_task,
            confidence=output["task_confidence"],
            allowed_candidates=[item.intent for item in tasks] + ["clarify"],
            decision_summary=f"Selected task {selected_task} within module {selected_module}.",
            elapsed_ms=elapsed,
        )
        run.state = snapshot_state(output)
        db.commit()
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



_READ_FOLLOWUP_EN_RE = re.compile(
    r"\b(last|previous|that|those|same|first|second|third|above|result|results|output|outputs|it|them)\b",
    flags=re.IGNORECASE,
)

_READ_REFRESH_EN_RE = re.compile(
    r"\b(search again|find again|new search|search new|refresh|run the search again|latest data)\b",
    flags=re.IGNORECASE,
)

_READ_FOLLOWUP_FA = (
    "قبلی",
    "آخرین نتیجه",
    "نتیجه قبلی",
    "خروجی قبلی",
    "خروجی آخر",
    "همان",
    "همون",
    "اون",
    "آن مورد",
    "این مورد",
    "مورد بالا",
    "اولی",
    "دومی",
    "سومی",
    "نتایج بالا",
)

_READ_REFRESH_FA = (
    "دوباره جستجو",
    "دوباره جست‌وجو",
    "جستجوی مجدد",
    "جست‌وجوی مجدد",
    "جستجوی جدید",
    "جست‌وجوی جدید",
    "دوباره سرچ",
    "بروزرسانی جستجو",
    "به‌روزرسانی جستجو",
)


def _is_previous_result_followup(question: str) -> bool:
    text = re.sub(r"\s+", " ", str(question or "").strip())
    lowered = text.lower()

    if not text:
        return False

    if _READ_REFRESH_EN_RE.search(lowered):
        return False

    if any(marker in text for marker in _READ_REFRESH_FA):
        return False

    if _READ_FOLLOWUP_EN_RE.search(lowered):
        return True

    return any(marker in text for marker in _READ_FOLLOWUP_FA)


def _matching_read_context(state: AgentState, spec) -> dict | None:
    context = state.get("active_read_context")

    if not isinstance(context, dict):
        return None

    if context.get("selected_module") != spec.module:
        return None

    retrieved_items = context.get("retrieved_items")

    if not isinstance(retrieved_items, list) or not retrieved_items:
        return None

    if not _is_previous_result_followup(state.get("question", "")):
        return None

    return context


async def read_node(state: AgentState) -> AgentState:
    user, db = state["user"], state["db"]
    intent = state.get("selected_task") or state["intent"]
    spec = registry.find_intent(user, intent)

    if spec is None or spec.module != state.get("selected_module"):
        return await clarify_node(
            {
                **state,
                "clarify_question": "Could you clarify what you want to do?",
            }
        )

    cached_context = _matching_read_context(state, spec)

    if cached_context is not None:
        return {
            **state,
            "current_step": intent,
            "retrieved_items": cached_context.get("retrieved_items") or [],
            "summary": cached_context.get("summary"),
            "answer": "",
            "citations": cached_context.get("citations") or [],
            "tool_calls": [
                *(state.get("tool_calls") or []),
                {
                    "module": spec.module,
                    "intent": intent,
                    "kind": "read_context_reuse",
                },
            ],
        }

    toolset = registry.get_toolset(spec.module)
    result = await toolset.handle_read(
        intent=intent,
        db=db,
        user=user,
        slots=state.get("slots") or {},
    )

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



_MISSING_LABELS_FA = {
    "accepted_quantity": "مقدار پذیرفته‌شده",
    "access method": "روش دسترسی",
    "amount": "مبلغ",
    "base currency": "ارز پایه",
    "base_currency_id": "ارز پایه",
    "card number": "شماره کارت",
    "category": "دسته‌بندی",
    "category_id": "دسته‌بندی",
    "counterparty": "طرف حساب",
    "credit card": "کارت بانکی",
    "currency": "ارز",
    "currency_id": "ارز",
    "deadline_date": "تاریخ مهلت",
    "description": "توضیحات",
    "direction": "نوع دریافت یا پرداخت",
    "item": "کالا",
    "items": "اقلام",
    "mr_id or items": "درخواست MR یا اقلام",
    "name": "نام",
    "needed_by_date": "تاریخ موردنیاز",
    "phone number": "شماره تلفن",
    "purchase phase item": "قلم مرحله خرید",
    "reason": "دلیل درخواست",
    "receipt date": "تاریخ رسید",
    "received_quantity": "مقدار دریافت‌شده",
    "rejected_quantity": "مقدار ردشده",
    "RFQ": "درخواست RFQ",
    "rfq_id": "درخواست RFQ",
    "storage location": "محل نگهداری",
    "storage_location_id": "محل نگهداری",
    "supplier": "تأمین‌کننده",
    "supplier_id": "تأمین‌کننده",
    "supplier_ids": "تأمین‌کنندگان",
    "title": "عنوان",
    "unit": "واحد",
    "unit_id": "واحد",
    "warehouse": "انبار",
    "warehouse_id": "انبار",
}


def _persian_field_label(value: object) -> str:
    name = str(value or "").strip()
    short_name = name.split(".")[-1]

    if name in _MISSING_LABELS_FA:
        return _MISSING_LABELS_FA[name]
    if short_name in _MISSING_LABELS_FA:
        return _MISSING_LABELS_FA[short_name]

    if short_name.endswith("_ids"):
        short_name = short_name[:-4]
    elif short_name.endswith("_id"):
        short_name = short_name[:-3]

    return short_name.replace("_", " ") or "اطلاعات لازم"


def _matching_partial_draft(state: AgentState, spec) -> dict | None:
    candidates = state.get("active_partial_drafts")

    if not isinstance(candidates, list):
        candidates = []

    legacy_partial = state.get("active_partial_draft")
    if isinstance(legacy_partial, dict):
        candidates = [*candidates, legacy_partial]

    for partial in candidates:
        if not isinstance(partial, dict):
            continue
        if partial.get("target_module") != spec.module:
            continue
        if partial.get("target_action") != spec.target_action:
            continue
        if not isinstance(partial.get("payload"), dict):
            continue
        return partial

    return None


def _localized_clarify_question(*, language: str, draft_data) -> str:
    current_language = str(language or "en").lower()

    if not current_language.startswith("fa"):
        return (
            draft_data.clarify_question
            or "Could you provide the missing details?"
        )

    validation = (
        draft_data.validation
        if isinstance(draft_data.validation, dict)
        else {}
    )

    references = validation.get("references")
    pending_fields = set(validation.get("references_pending") or [])

    if isinstance(references, list):
        for reference in references:
            if not isinstance(reference, dict):
                continue

            field = str(reference.get("field") or "")
            status = reference.get("status")

            if field not in pending_fields and status not in {
                "ambiguous",
                "missing",
            }:
                continue

            label = _persian_field_label(field)

            if status == "ambiguous":
                return (
                    f"چند گزینه برای {label} پیدا کردم. "
                    "لطفاً گزینه درست را انتخاب کنید."
                )

            create_suggestion = reference.get("create_suggestion")
            if isinstance(create_suggestion, dict):
                model_candidates = create_suggestion.get("model_candidates")
                if isinstance(model_candidates, list) and model_candidates:
                    return (
                        "چند مدل دقیق یا مشابه پیدا کردم. "
                        "لطفاً مدل درست را انتخاب کنید؛ اگر هیچ‌کدام درست نیست، "
                        "یک مدل جدید ایجاد کنید."
                    )
                if create_suggestion.get("requires_model_selection"):
                    return (
                        "مدل دقیق یا مشابهی پیدا نشد. "
                        "برای ادامه یک مدل جدید ایجاد کنید."
                    )
                return (
                    f"{label} موردنظر پیدا نشد. "
                    "آیا می‌خواهید آن را ایجاد کنید یا با عبارت دیگری جست‌وجو کنم؟"
                )

            return (
                f"{label} موردنظر پیدا نشد. "
                "لطفاً شناسه یا نام دقیق‌تری وارد کنید."
            )

    missing = validation.get("missing")

    if isinstance(missing, list) and missing:
        labels = [_persian_field_label(item) for item in missing]
        return (
            "برای ادامه هنوز این اطلاعات را نیاز دارم: "
            + "، ".join(labels)
            + "."
        )

    return "لطفاً اطلاعات تکمیلی موردنیاز را وارد کنید."


async def write_node(state: AgentState) -> AgentState:
    user, db = state["user"], state["db"]
    intent = state.get("selected_task") or state["intent"]
    spec = registry.find_intent(user, intent)
    if spec is None or spec.module != state.get("selected_module"):
        return await clarify_node({**state, "clarify_question": "Could you clarify what you want to change?"})
    toolset = registry.get_toolset(spec.module)
    slots = dict(state.get("slots") or {})
    active_partial = _matching_partial_draft(state, spec) or {}
    if active_partial:
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
        clarify_question = _localized_clarify_question(
            language=state.get("language") or "en",
            draft_data=draft_data,
        )
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
    db, run = _observable(state)
    started = perf_counter()
    kind = _resolve_kind(state)
    selected_module = state.get("selected_module") or "general"
    selected_task = state.get("selected_task") or state.get("intent") or kind
    tool_identifier = f"{selected_module}.{selected_task}"
    if run is not None:
        observability.start_step(
            db, run, stage="executor", event_type="executor.started",
            state=snapshot_state(state), payload={"task_kind": kind},
        )
        observability.record_tool_call(
            db, run, stage="executor", status="started", tool_identifier=tool_identifier,
            owning_module=selected_module, operation=selected_task,
            input_summary={
                "slot_keys": sorted((state.get("slots") or {}).keys()),
                "attachment_count": len(state.get("attachments") or []),
            },
        )
    logger.info("assistant.executor.started", extra=_log_context(state))
    handler = {
        "read": read_node,
        "write": write_node,
        "help": help_node,
        "general": general_node,
        "clarify": clarify_node,
    }[kind]
    try:
        if run is not None:
            with observability.execution_context(
                db=db, run=run, selected_module=selected_module, selected_task=selected_task,
            ) as execution:
                output = await handler(state)
                searched_modules = sorted(execution["searched_modules"])
        else:
            output = await handler(state)
            searched_modules = []
    except Exception as exc:
        if run is not None:
            elapsed = observability.duration_ms(started)
            _record_failure(
                state, observability.record_tool_call, db, run, stage="executor", status="failed",
                tool_identifier=tool_identifier, owning_module=selected_module, operation=selected_task,
                elapsed_ms=elapsed, error_code=_error_code(exc),
            )
            _record_failure(
                state, observability.fail_step, db, run, stage="executor", event_type="executor.failed",
                error_code=_error_code(exc), elapsed_ms=elapsed, state=snapshot_state(state),
            )
        raise
    logger.info("assistant.executor.completed", extra=_log_context(output, task_kind=kind))
    if run is not None:
        elapsed = observability.duration_ms(started)
        pending, partial = output.get("pending_draft"), output.get("partial_draft")
        observability.record_tool_call(
            db, run, stage="executor", status="completed", tool_identifier=tool_identifier,
            owning_module=selected_module, operation=selected_task, elapsed_ms=elapsed,
            output_summary={
                "retrieved_count": len(output.get("retrieved_items") or []),
                "has_summary": bool(output.get("summary")),
                "validation_outcome": (output.get("validation_result") or {}).get("outcome"),
            },
            produced_draft=bool(pending or partial),
            searched_another_module=bool(searched_modules),
        )
        observability.complete_step(
            db, run, stage="executor", event_type="executor.completed",
            state=snapshot_state(output), payload={"task_kind": kind}, elapsed_ms=elapsed,
        )
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
    db, run = _observable(state)
    started = perf_counter()
    if run is not None:
        observability.start_step(
            db, run, stage="validator", event_type="validator.started", state=snapshot_state(state),
        )
    errors: list[str] = []
    output: AgentState = state
    selected_task = state.get("selected_task")
    spec = registry.find_intent(state["user"], selected_task) if selected_task else None
    kind = spec.kind if spec is not None else ("general" if selected_task in {"general", "assistant_help"} else "clarify")

    try:
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
    except Exception as exc:
        if run is not None:
            _record_failure(
                state, observability.fail_step, db, run, stage="validator", event_type="validator.failed",
                error_code=_error_code(exc), elapsed_ms=observability.duration_ms(started),
                state=snapshot_state(state),
            )
        raise

    if output.get("intent") == "clarify":
        logger.info("assistant.clarification.required", extra=_log_context(output))
    logger.info(
        "assistant.validator.completed",
        extra=_log_context(output, validation_outcome=output.get("validation_result", {}).get("outcome")),
    )
    if run is not None:
        outcome = output.get("validation_result", {}).get("outcome")
        if outcome == "pending_draft":
            observability.record_event(
                db, run, event_type="draft.created", stage="validator", status="completed",
                selected_module=output.get("selected_module"), selected_task=output.get("selected_task"),
                payload={
                    "target_module": (output.get("pending_draft") or {}).get("target_module"),
                    "target_action": (output.get("pending_draft") or {}).get("target_action"),
                    "validation": (output.get("pending_draft") or {}).get("validation") or {},
                },
            )
        elif outcome == "partial_draft":
            observability.record_event(
                db, run, event_type="partial_draft.created", stage="validator", status="completed",
                selected_module=output.get("selected_module"), selected_task=output.get("selected_task"),
                payload={
                    "target_module": (output.get("partial_draft") or {}).get("target_module"),
                    "target_action": (output.get("partial_draft") or {}).get("target_action"),
                    "missing": (output.get("partial_draft") or {}).get("missing") or [],
                },
            )
        observability.complete_step(
            db, run, stage="validator", event_type="validator.completed", state=snapshot_state(output),
            payload={"outcome": outcome, "valid": output.get("validation_result", {}).get("valid")},
            elapsed_ms=observability.duration_ms(started),
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
