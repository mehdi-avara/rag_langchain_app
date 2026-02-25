from __future__ import annotations

import re

from components.llm import llm_client
from settings import get_settings


settings = get_settings()

_WHITESPACE_RE = re.compile(r"\s+")


def _sanitize_generated_title(raw_title: str) -> str:
    title = (raw_title or "").strip()
    title = title.strip('"\'')
    title = _WHITESPACE_RE.sub(" ", title)

    if len(title) > 60:
        title = title[:60].rstrip()

    return title or "General Question"


async def generate_chat_title_from_question(question: str) -> str:
    response = await llm_client.async_openai_client.chat.completions.create(
        model=settings.openai_model,
        temperature=0,
        messages=[
            {
                "role": "system",
                "content": (
                    "Generate a concise chat title from the user's first question. "
                    "Return ONLY the title text with no quotes, JSON, or commentary. "
                    "Prefer 3 to 7 words, descriptive, and no emojis. "
                    "If the question is too short or vague, return: General Question."
                ),
            },
            {
                "role": "user",
                "content": f"First question: {question}",
            },
        ],
    )

    content = response.choices[0].message.content or ""
    return _sanitize_generated_title(content)
