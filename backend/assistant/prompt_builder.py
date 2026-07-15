"""Compose global orchestration prompts with RBAC-filtered module metadata."""

from __future__ import annotations

import json
from typing import Iterable, Optional

from .prompts import answer_rules, draft_rules, file_rules, global_rules, module_router_rules, task_router_rules
from .registry import ModuleAssistantDescriptor, TaskAssistantDescriptor


def _normalise_history(history: Optional[list[dict]]) -> list[dict]:
    output: list[dict] = []
    for item in history or []:
        role, content = item.get("role"), item.get("content")
        if role in {"user", "assistant"} and isinstance(content, str) and content.strip():
            output.append({"role": role, "content": content.strip()})
    return output


def _user_message(question: str, image_blocks: Optional[list[dict]]) -> dict:
    if image_blocks:
        return {"role": "user", "content": [*image_blocks, {"type": "text", "text": question}]}
    return {"role": "user", "content": question}


def build_module_router_prompt(
    *,
    modules: Iterable[ModuleAssistantDescriptor],
    has_attachments: bool = False,
    has_images: bool = False,
) -> str:
    accessible = tuple(modules)
    catalog = "\n".join(
        f"- {item.module} ({item.display_title}): {item.description}" for item in accessible
    ) or "(no domain modules are accessible)"
    return "\n\n".join((
        global_rules(),
        module_router_rules(allowed_modules=tuple(item.module for item in accessible)),
        file_rules(has_attachments=has_attachments, has_images=has_images),
        "Accessible module descriptors:\n" + catalog,
    ))


def build_module_router_messages(
    *, question: str, modules: Iterable[ModuleAssistantDescriptor], history: Optional[list[dict]] = None,
    has_attachments: bool = False, image_blocks: Optional[list[dict]] = None,
) -> list[dict]:
    module_list = tuple(modules)
    return [
        {"role": "system", "content": build_module_router_prompt(
            modules=module_list, has_attachments=has_attachments, has_images=bool(image_blocks),
        )},
        *_normalise_history(history),
        _user_message(question, image_blocks),
    ]


def build_specialist_prompt(
    *,
    module: ModuleAssistantDescriptor,
    task: TaskAssistantDescriptor,
    specialist_instructions: Iterable[str] = (),
) -> str:
    """Load metadata for exactly one selected module/task."""
    lines = [
        f"Selected module: {module.module} ({module.display_title})",
        f"Module purpose: {module.description}",
        f"Selected task: {task.intent} ({task.kind})",
        f"Task: {task.description}",
    ]
    if task.slot_rules:
        lines.append("Slot extraction rules:\n- " + "\n- ".join(task.slot_rules))
    if task.examples:
        lines.append("Examples:\n- " + "\n- ".join(task.examples))
    notes = tuple(specialist_instructions) or task.specialist_notes
    if notes:
        lines.append("Specialist notes:\n- " + "\n- ".join(notes))
    return "\n\n".join(lines)


def build_task_finder_prompt(
    *,
    module: ModuleAssistantDescriptor,
    tasks: Iterable[TaskAssistantDescriptor],
    has_attachments: bool = False,
    has_images: bool = False,
) -> str:
    selected_tasks = tuple(tasks)
    entries: list[str] = []
    for item in selected_tasks:
        lines = [f"- {item.intent} [{item.kind}]: {item.description}"]
        if item.slot_rules:
            lines.append("  Slot rules: " + " | ".join(item.slot_rules))
        if item.examples:
            lines.append("  Examples: " + " | ".join(item.examples))
        entries.append("\n".join(lines))
    catalog = "\n".join(entries) or "(no tasks are accessible)"
    return "\n\n".join((
        global_rules(),
        task_router_rules(allowed_intents=tuple(item.intent for item in selected_tasks)),
        file_rules(has_attachments=has_attachments, has_images=has_images),
        f"Selected module: {module.module} ({module.display_title})\n{module.description}",
        "Accessible tasks for this selected module only:\n" + catalog,
    ))


def build_task_finder_messages(
    *, question: str, module: ModuleAssistantDescriptor, tasks: Iterable[TaskAssistantDescriptor],
    history: Optional[list[dict]] = None, has_attachments: bool = False,
    image_blocks: Optional[list[dict]] = None,
) -> list[dict]:
    task_list = tuple(tasks)
    return [
        {"role": "system", "content": build_task_finder_prompt(
            module=module, tasks=task_list, has_attachments=has_attachments, has_images=bool(image_blocks),
        )},
        *_normalise_history(history),
        _user_message(question, image_blocks),
    ]


def _answer_context(
    *, pending_draft: Optional[dict], retrieved_items: list[dict], summary: Optional[dict],
    citations: list, extracted_text: Optional[str],
) -> str:
    parts: list[str] = []
    if summary:
        parts.append("Summary/KPIs (trusted system data):\n" + json.dumps(summary, default=str))
    if retrieved_items:
        parts.append("Retrieved records (trusted system data):\n" + json.dumps(retrieved_items[:20], default=str))
    if citations:
        parts.append("Allowed citation keys:\n" + json.dumps(citations, default=str))
    if pending_draft:
        parts.append("Pending draft (not committed):\n" + json.dumps(pending_draft, default=str))
    if extracted_text:
        parts.append("<uploaded_data>\n" + extracted_text[:4000] + "\n</uploaded_data>")
    return "\n\n".join(parts) or "(no system data)"


def build_answer_prompt(
    *, selected_module: str, selected_task: str, language: str, pending_draft: Optional[dict] = None,
    retrieved_items: Optional[list[dict]] = None, summary: Optional[dict] = None,
    citations: Optional[list] = None, extracted_text: Optional[str] = None,
    image_blocks: Optional[list[dict]] = None,
    specialist_instructions: Iterable[str] = (),
) -> str:
    module_label = selected_module or "general"
    task_label = selected_task or "general"
    specialist = tuple(specialist_instructions)
    parts = [
        global_rules(language=language),
        answer_rules(),
        file_rules(
            has_attachments=bool(extracted_text) or bool(image_blocks),
            has_images=bool(image_blocks),
        ),
        f"Current module: {module_label}. Current task: {task_label}.",
    ]
    if pending_draft:
        parts.append(draft_rules())
    if specialist:
        parts.append("Selected module/task specialist notes:\n- " + "\n- ".join(specialist))
    return "\n\n".join(parts)


def build_answer_messages(
    *, question: str, selected_module: str, selected_task: str, language: str,
    pending_draft: Optional[dict] = None, retrieved_items: Optional[list[dict]] = None,
    summary: Optional[dict] = None, citations: Optional[list] = None,
    extracted_text: Optional[str] = None, image_blocks: Optional[list[dict]] = None,
    history: Optional[list[dict]] = None, specialist_instructions: Iterable[str] = (),
) -> list[dict]:
    items = retrieved_items or []
    citation_values = citations or []
    system = build_answer_prompt(
        selected_module=selected_module, selected_task=selected_task, language=language,
        pending_draft=pending_draft, retrieved_items=items, summary=summary,
        citations=citation_values, extracted_text=extracted_text,
        image_blocks=image_blocks,
        specialist_instructions=specialist_instructions,
    )
    context = _answer_context(
        pending_draft=pending_draft, retrieved_items=items, summary=summary,
        citations=citation_values, extracted_text=extracted_text,
    )
    if selected_module == "general" and selected_task == "general" and context == "(no system data)":
        text = question
    else:
        text = "User request:\n" + question + "\n\nContext:\n" + context
    return [
        {"role": "system", "content": system},
        *_normalise_history(history),
        _user_message(text, image_blocks),
    ]
