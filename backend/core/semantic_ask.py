from __future__ import annotations

import re
from typing import Any, Dict, List, Tuple

from components.llm import llm_client
from settings import get_settings


settings = get_settings()

_CHUNK_CITATION_RE = re.compile(r"\[chunk:(\d+)\]")
_COMMENT_CITATION_RE = re.compile(r"\[comment:(\d+)\]")


def _unique_in_order(values: List[int]) -> List[int]:
    seen: set[int] = set()
    output: List[int] = []
    for value in values:
        if value not in seen:
            seen.add(value)
            output.append(value)
    return output


def _split_reference_hits(references: Any) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
    if isinstance(references, dict):
        return list(references.get("documents", []) or []), list(references.get("comments", []) or [])

    if isinstance(references, list):
        if not references:
            return [], []
        first = references[0]
        if isinstance(first, dict) and "part_id" in first:
            return references, []
        if isinstance(first, dict) and "comment_id" in first:
            return [], references

    return [], []


def build_context_from_references(references: Any) -> str:
    documents, comments = _split_reference_hits(references)
    lines: List[str] = []

    if documents:
        lines.append("Document references:")
        for hit in documents:
            lines.append(
                f"[chunk:{hit.get('part_id')}] "
                f"document_id={hit.get('document_id')} "
                f"title={hit.get('document_title')} "
                f"text={hit.get('part_text')}"
            )

    if comments:
        lines.append("Comment references:")
        for hit in comments:
            lines.append(
                f"[comment:{hit.get('comment_id')}] "
                f"title={hit.get('comment_title')} "
                f"type={hit.get('type')} "
                f"content={hit.get('comment_content')}"
            )

    return "\n".join(lines).strip()


async def generate_answer_from_references(question: str, references: Any) -> str:
    context = build_context_from_references(references)
    response = await llm_client.async_openai_client.chat.completions.create(
        model=settings.openai_model,
        temperature=settings.llm_temperature,
        messages=[
            {
                "role": "system",
                "content": (
                    "Answer using ONLY the provided references.\n"
                    "If the references are insufficient, say so.\n"
                    "Cite sources strictly as [chunk:<part_id>] for chunks "
                    "and [comment:<comment_id>] for comments."
                ),
            },
            {
                "role": "user",
                "content": (
                    f"Question:\n{question}\n\n"
                    f"References:\n{context if context else '(no references)'}"
                ),
            },
        ],
    )
    return (response.choices[0].message.content or "").strip()


def parse_semantic_citations(answer: str) -> Tuple[List[int], List[int], List[int]]:
    chunk_ids = _unique_in_order([int(match) for match in _CHUNK_CITATION_RE.findall(answer or "")])
    comment_ids = _unique_in_order([int(match) for match in _COMMENT_CITATION_RE.findall(answer or "")])
    citations = _unique_in_order(chunk_ids + comment_ids)
    return chunk_ids, comment_ids, citations
