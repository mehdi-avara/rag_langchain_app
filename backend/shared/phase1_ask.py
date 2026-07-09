from __future__ import annotations

import re
from typing import Iterable

from components.llm import llm_client, raise_llm_exception
from settings import get_settings

settings = get_settings()


def parse_citations(answer: str, prefix: str) -> list[int]:
    result: list[int] = []
    seen: set[int] = set()
    pattern = re.compile(rf"\[{re.escape(prefix)}:(\d+)\]")

    for raw_value in pattern.findall(answer or ""):
        value = int(raw_value)
        if value not in seen:
            seen.add(value)
            result.append(value)

    return result


async def answer_from_references(
    *,
    question: str,
    references: Iterable[object],
    context: str,
    citation_prefix: str,
    component_name: str,
    language: str | None = None,
) -> str:
    language_instruction = (
        f" Answer in the user's language (BCP-47: {language})."
        if language
        else ""
    )
    try:
        response = await llm_client.async_openai_client.chat.completions.create(
            model=settings.openai_model,
            temperature=settings.llm_temperature,
            messages=[
                {
                    "role": "system",
                    "content": (
                        "Answer only from the provided references. "
                        "If the references are insufficient, say so. "
                        f"Cite every factual statement as "
                        f"[{citation_prefix}:<id>]."
                        f"{language_instruction}"
                    ),
                },
                {
                    "role": "user",
                    "content": (
                        f"Question:\n{question}\n\n"
                        f"References:\n{context}"
                    ),
                },
            ],
        )
    except Exception as exc:
        raise_llm_exception(exc, component_name)

    return (response.choices[0].message.content or "").strip()
