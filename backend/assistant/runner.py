"""Turn orchestration + SSE streaming + history persistence (PROMPT §8.1, §8.2).

Responsibilities:
- enforce the rate guard (§9) and run as exactly the caller (§5);
- reuse the existing chat transcript store (``Chat`` + ``ChatMessage``) so
  ``GET /chat/{chat_id}/history`` keeps working (§8.1);
- keep the resumable run state in its own ``AgentRun`` store (§8.1);
- run the LangGraph flow, persist any built draft (never commit it, §4), and
  stream the reply over SSE (§8.2) — structured payloads (draft / references /
  summary) are emitted as whole objects, never reconstructed from tokens.
"""

from __future__ import annotations

import json
import logging
from typing import AsyncGenerator, Optional

from sqlalchemy import desc
from sqlalchemy.orm import Session

from components.llm import llm_client
from core.exceptions import AppException
from core.exceptions.error_codes import INTERNAL_SERVER_ERROR
from Models import AgentRun, ChatMessage, User
from Models.chat import ChatRole
from settings import get_settings

from . import intake as intake_mod
from . import prompt_builder, registry
from . import service as draft_service
from . import tracing
from .graph import build_assistant_graph
from .models import AgentRunStatus, DraftStatus
from .rate_limit import check_and_consume
from .schemas import AssistantChatRequest, DraftOut
from .state import AgentState, snapshot_state

logger = logging.getLogger(__name__)
settings = get_settings()
HISTORY_MESSAGE_LIMIT = 12
HISTORY_CONTENT_LIMIT = 4000


def sse_event(event: str, data: dict) -> str:
    return f"event: {event}\ndata: {json.dumps(data, default=str)}\n\n"


def _chunk_text(text: str, size: int = 24):
    for i in range(0, len(text), size):
        yield text[i : i + size]


def _load_recent_history(db: Session, *, chat_id: int, limit: int = HISTORY_MESSAGE_LIMIT) -> list[dict]:
    messages = (
        db.query(ChatMessage)
        .filter(ChatMessage.chat_id == chat_id)
        .order_by(desc(ChatMessage.id))
        .limit(limit)
        .all()
    )
    history: list[dict] = []
    for message in reversed(messages):
        role = getattr(message.role, "value", str(message.role))
        if role not in {"user", "assistant"}:
            continue
        content = (message.content or "").strip()
        if not content:
            continue
        history.append({"role": role, "content": content[:HISTORY_CONTENT_LIMIT]})
    return history


def _load_latest_partial_draft(db: Session, *, chat_id: int, user: User) -> Optional[dict]:
    runs = (
        db.query(AgentRun)
        .filter(
            AgentRun.chat_id == chat_id,
            AgentRun.company_id == user.company_id,
            AgentRun.created_by_user_id == user.id,
        )
        .order_by(desc(AgentRun.id))
        .limit(8)
        .all()
    )
    for run in runs:
        state = run.state if isinstance(run.state, dict) else {}
        partial = state.get("partial_draft") if isinstance(state, dict) else None
        if isinstance(partial, dict) and partial.get("target_action") and isinstance(partial.get("payload"), dict):
            return partial
        if state.get("pending_draft"):
            return None
    return None


def _history_messages(state: AgentState) -> list[dict]:
    messages: list[dict] = []
    for item in state.get("history") or []:
        role = item.get("role")
        content = item.get("content")
        if role not in {"user", "assistant"}:
            continue
        if not isinstance(content, str) or not content.strip():
            continue
        messages.append({"role": role, "content": content.strip()[:HISTORY_CONTENT_LIMIT]})
    return messages


def _answer_messages(state: AgentState) -> list[dict]:
    selected_task = state.get("selected_task") or state.get("intent") or "general"
    selected_module = state.get("selected_module") or "general"
    if selected_module == "general" and selected_task not in {"general", "assistant_help", "clarify"}:
        spec = registry.find_intent(state["user"], selected_task) if state.get("user") else None
        selected_module = spec.module if spec and spec.module else "general"
    return prompt_builder.build_answer_messages(
        question=state.get("question", ""),
        selected_module=selected_module,
        selected_task=selected_task,
        language=state.get("language") or "en",
        pending_draft=state.get("pending_draft"),
        retrieved_items=state.get("retrieved_items") or [],
        summary=state.get("summary"),
        citations=state.get("citations") or [],
        extracted_text=state.get("extracted_text"),
        image_blocks=state.get("image_blocks") or [],
        history=_history_messages(state),
        specialist_instructions=state.get("specialist_instructions") or [],
    )


async def _stream_model_answer(state: AgentState):
    """Yield answer text deltas from the model (OpenAI-compatible, stream=True).

    Uses the client + model resolved from the active ``ChatAIModels`` row
    (carried on the state), falling back to the shared settings-based client.
    """
    client = state.get("model_client") or llm_client.async_openai_client
    model = state.get("model_name") or settings.openai_model
    stream = await client.chat.completions.create(
        model=model,
        temperature=settings.llm_temperature,
        messages=_answer_messages(state),
        stream=True,
        timeout=intake_mod.LLM_TIMEOUT,
    )
    async for chunk in stream:
        choices = getattr(chunk, "choices", None) or []
        if not choices:
            continue
        delta = getattr(choices[0], "delta", None)
        if delta is None:
            continue
        content = getattr(delta, "content", None)
        if isinstance(content, str) and content:
            yield content


async def run_turn_stream(
    db: Session,
    *,
    user: User,
    request: AssistantChatRequest,
) -> AsyncGenerator[str, None]:
    """Run one assistant turn and stream SSE events.

    Imports the chat-transcript helpers lazily to avoid import cycles at module
    load (PROMPT §8.1 mandates reusing the existing ``ChatMessage`` store).
    """
    from routs.chat import add_message, get_or_create_chat

    # --- guard rails ---
    check_and_consume(user)

    chat_obj, is_new_chat = get_or_create_chat(db, chat_id=request.chat_id, user=user)
    history = _load_recent_history(db, chat_id=chat_obj.id)
    active_partial_draft = _load_latest_partial_draft(db, chat_id=chat_obj.id, user=user)
    add_message(db, chat_id=chat_obj.id, role=ChatRole.user, content=request.query)

    if is_new_chat:
        try:  # title generation is best-effort
            from core.celery.tasks import chat_generate_title

            chat_generate_title.delay(chat_obj.id, request.query)
        except Exception:  # pragma: no cover
            logger.debug("chat title generation unavailable", exc_info=True)

    run = draft_service.create_agent_run(db, chat_id=chat_obj.id, user=user)

    async def event_generator() -> AsyncGenerator[str, None]:
        full_answer_parts: list[str] = []
        draft_out: Optional[dict] = None
        draft_id: Optional[int] = None
        result: Optional[AgentState] = None
        retrieved_items: list = []
        summary = None
        citations: list = []
        intent = None
        partial_draft = None

        with tracing.trace_run("assistant_chat", chat_id=chat_obj.id, user_id=user.id):
            try:
                yield sse_event("status", {"step": "routing", "message": "Understanding your request…"})

                # --- resolve the active model (api key + endpoint + name + vision)
                #     from the ChatAIModels row (PROMPT §7) ---
                model_cfg = intake_mod.resolve_chat_model(db)
                model_is_vlm = model_cfg.supports_vision

                # --- file intake + VLM/text branch (§6/§7) ---
                intake = intake_mod.gather_intake(
                    db, user=user, asset_ids=list(request.attachments or []), model_is_vlm=model_is_vlm
                )
                draft_service.update_run(db, run, intake_mode=intake.intake_mode)

                state: AgentState = {
                    "chat_id": chat_obj.id,
                    "agent_run_id": run.id,
                    "user": user,
                    "user_id": user.id,
                    "company_id": user.company_id,
                    "db": db,
                    "question": request.query,
                    "history": history,
                    "attachments": list(request.attachments or []),
                    "model_is_vlm": model_is_vlm,
                    "model_client": model_cfg.client,
                    "model_name": model_cfg.model,
                    "image_blocks": intake.image_blocks,
                    "extracted_text": intake.extracted_text,
                    "intake_mode": intake.intake_mode,
                    "slots": {},
                    "selected_module": "",
                    "selected_task": "",
                    "module_confidence": 0.0,
                    "task_confidence": 0.0,
                    "loaded_prompt_parts": [],
                    "specialist_instructions": [],
                    "tool_calls": [],
                    "validation_result": {},
                    "active_partial_draft": active_partial_draft,
                    "plan": [],
                    "step_count": 0,
                    "retrieved_items": [],
                    "citations": [],
                    "answer": "",
                }

                graph = build_assistant_graph()
                result: AgentState = await graph.ainvoke(state)

                intent = result.get("intent")
                language = result.get("language") or "en"
                retrieved_items = result.get("retrieved_items") or []
                summary = result.get("summary")
                pending_draft = result.get("pending_draft")
                partial_draft = result.get("partial_draft")
                citations = result.get("citations") or []
                draft_service.update_run(db, run, intent=intent, language=language)

                # --- structured payloads first, as whole objects (§8.2) ---
                if retrieved_items or summary:
                    yield sse_event(
                        "references",
                        {"retrieved": retrieved_items, "summary": summary},
                    )

                # Incomplete write: return the object-so-far + missing field nouns
                # (no draft is persisted — it isn't committable yet).
                if partial_draft:
                    yield sse_event("partial_draft", {"partial_draft": partial_draft})

                if pending_draft:
                    yield sse_event("status", {"step": "draft", "message": "Preparing a draft for your review…"})
                    draft = draft_service.persist_draft(
                        db,
                        chat_id=chat_obj.id,
                        agent_run_id=run.id,
                        user=user,
                        pending_draft=pending_draft,
                        language=language,
                    )
                    draft_id = draft.id
                    draft_out = DraftOut.model_validate(draft).model_dump(mode="json")
                    yield sse_event("draft", {"draft": draft_out})

                # --- answer deltas ---
                precomputed = (result.get("answer") or "").strip()
                if precomputed:
                    # ask_finance / clarify already produced grounded/clarifying text.
                    for piece in _chunk_text(precomputed):
                        full_answer_parts.append(piece)
                        yield sse_event("delta", {"text": piece})
                else:
                    async for piece in _stream_model_answer(result):
                        full_answer_parts.append(piece)
                        yield sse_event("delta", {"text": piece})

            except AppException as exc:
                # Catalogued error: stream-safe, leave the run resumable + draft intact (§8.2).
                draft_service.update_run(
                    db, run, status=AgentRunStatus.SUSPENDED.value, error_code=exc.code,
                    state=snapshot_state(result) if result is not None else None,
                )
                yield sse_event("error", {"code": exc.code, "message": exc.message})
                return
            except Exception as exc:  # noqa: BLE001
                logger.exception("assistant run failed")
                draft_service.update_run(
                    db, run, status=AgentRunStatus.SUSPENDED.value, error_code=INTERNAL_SERVER_ERROR
                )
                yield sse_event("error", {"code": INTERNAL_SERVER_ERROR, "message": "Internal server error"})
                return

            # --- persist after streaming (§8.2): transcript = visible history ---
            full_answer = "".join(full_answer_parts).strip()
            add_message(
                db,
                chat_id=chat_obj.id,
                role=ChatRole.assistant,
                content=full_answer,
                citations=citations,
                retrieved_chunks=retrieved_items,
                draft_id=draft_id,
            )
            draft_service.update_run(
                db, run, status=AgentRunStatus.COMPLETED.value, state=snapshot_state(result)
            )

            yield sse_event(
                "done",
                {
                    "answer": full_answer,
                    "citations": citations,
                    "retrieved_chunks": retrieved_items,
                    "summary": summary,
                    "intent": intent,
                    "chat_id": chat_obj.id,
                    "draft_id": draft_id,
                    "draft": draft_out,
                    "partial_draft": partial_draft,
                },
            )

    return event_generator()
