"""Intent router (PROMPT §3).

Classifies a user message into exactly one **permitted** intent (the RBAC-filtered
set — the LLM is never shown tasks the user can't access), plus the detected
language and any extracted slots. Prefers ``clarify`` over guessing when a write
intent is missing required fields.

The router calls the OpenAI-compatible client directly (JSON mode), so unit tests
can monkeypatch ``llm_client.async_openai_client``.
"""

from __future__ import annotations

import json
import logging
from typing import List, Optional

from components.llm import llm_client, raise_llm_exception
from core.exceptions import AppException
from settings import get_settings

from .registry import IntentSpec

logger = logging.getLogger(__name__)
settings = get_settings()


def _intent_catalog(intents: List[IntentSpec]) -> str:
    lines = []
    for spec in intents:
        lines.append(f"- {spec.name}: {spec.description}")
    return "\n".join(lines)


def _system_prompt(intents: List[IntentSpec], has_attachments: bool) -> str:
    catalog = _intent_catalog(intents)
    names = ", ".join(spec.name for spec in intents)
    attach_note = (
        "The user attached one or more files; consider receipt-from-file or attach-file intents."
        if has_attachments
        else "No files are attached."
    )
    return (
        "You are the intent router for a financial-management assistant.\n"
        "Choose EXACTLY ONE intent from the list below that best matches the user's message.\n"
        "You must only ever choose from these intents (do not invent others):\n"
        f"{catalog}\n\n"
        f"{attach_note}\n\n"
        "Rules:\n"
        "- Detect the user's language and return it as a BCP-47 code (e.g. 'fa', 'en').\n"
        "- Extract any useful slots: amounts, dates, names, ids, currency, direction, mode, query text.\n"
        "- For a write intent, if required fields are missing, choose 'clarify' instead of guessing.\n"
        "- Respond ONLY with JSON of the form:\n"
        '{"intent": "<one of: ' + names + '>", "language": "<bcp47>", '
        '"slots": { ... }, "clarify_question": "<question in the user\'s language or null>"}'
    )


async def classify(
    *,
    question: str,
    intents: List[IntentSpec],
    has_attachments: bool = False,
) -> dict:
    """Return ``{intent, language, slots, clarify_question}``.

    Always returns a dict; on a malformed model response it degrades to
    ``clarify`` rather than raising, so a turn never crashes on router noise.
    """
    permitted_names = {spec.name for spec in intents}

    try:
        response = await llm_client.async_openai_client.chat.completions.create(
            model=settings.openai_model,
            temperature=0.0,
            response_format={"type": "json_object"},
            messages=[
                {"role": "system", "content": _system_prompt(intents, has_attachments)},
                {"role": "user", "content": question},
            ],
        )
    except AppException:
        raise
    except Exception as exc:  # network/model failure -> catalogued LLM error
        raise_llm_exception(exc, "assistant_router")

    raw = (response.choices[0].message.content or "").strip()

    try:
        parsed = json.loads(raw)
    except (json.JSONDecodeError, TypeError):
        logger.warning("assistant router returned non-JSON: %r", raw)
        parsed = {}

    intent = parsed.get("intent")
    if intent not in permitted_names:
        intent = "clarify"

    language = parsed.get("language") or "en"
    slots = parsed.get("slots") if isinstance(parsed.get("slots"), dict) else {}
    clarify_question: Optional[str] = parsed.get("clarify_question")

    return {
        "intent": intent,
        "language": language,
        "slots": slots,
        "clarify_question": clarify_question,
    }
