"""RBAC-filtered intent / tool registry (PROMPT §3).

One source of truth: the tool registry filtered by the caller's RBAC. The router
only ever sees the intents *this* user is allowed to do — intents whose required
permission the user lacks are dropped before the prompt is built, so the LLM is
never told about tasks the user can't access (no information leak) and
``PERMISSION_DENIED`` becomes a rare edge case rather than the normal path.

The same filtered registry backs the ``//`` slash-command menu (master plan
§12.16). ``general`` and ``clarify`` are always available.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Optional

from Models import User

from .rbac import has_permission


@dataclass
class DraftData:
    """What a ``build_*_draft`` builder returns (PROMPT §4).

    The toolset never writes — it only assembles the payload and resolves the
    ``commit_target`` (method + endpoint + permission). ``valid`` / ``validation``
    let the runner prefer ``clarify`` over offering an un-committable draft.
    """

    target_module: str
    target_action: str
    payload: dict
    commit_target: dict
    attachments: list = field(default_factory=list)
    validation: dict = field(default_factory=dict)
    valid: bool = True
    clarify_question: Optional[str] = None
    references: list = field(default_factory=list)   # list of ReferenceResolution.as_dict()


@dataclass(frozen=True)
class IntentSpec:
    name: str
    description: str
    kind: str                      # read | write | file | general | clarify
    permission: Optional[str] = None
    module: Optional[str] = None
    target_action: Optional[str] = None  # for write intents -> Draft.target_action


@dataclass(frozen=True)
class ModuleAssistantDescriptor:
    """Prompt-safe description of one module exposed to the module router."""

    module: str
    display_title: str
    description: str


@dataclass(frozen=True)
class TaskAssistantDescriptor:
    """Prompt-safe description of one RBAC-filtered module task."""

    module: str
    intent: str
    kind: str  # read | write | file | general | clarify
    required_permission: Optional[str]
    description: str
    slot_rules: tuple[str, ...] = ()
    examples: tuple[str, ...] = ()
    specialist_notes: tuple[str, ...] = ()
    target_action: Optional[str] = None


# Always-available, module-independent intents.
GENERAL_INTENT = IntentSpec(
    name="general",
    description=(
        "A general-knowledge question that is NOT about the company's own financial "
        "data (receipts, cards, customers). Answer from the model's own knowledge and "
        "cite nothing."
    ),
    kind="general",
    permission="assistant:chat",
)

HELP_INTENT = IntentSpec(
    name="assistant_help",
    description=(
        "A question about this assistant's capabilities, available actions, or how to use it - "
        "for example 'what can you do?' or 'how can you help me?'."
    ),
    kind="help",
    permission="assistant:chat",
)

CLARIFY_INTENT = IntentSpec(
    name="clarify",
    description=(
        "The message is ambiguous, under-specified, or missing fields required to act. "
        "Ask the user exactly one focused clarifying question in their own language."
    ),
    kind="clarify",
    permission=None,
)


class ModuleToolSet:
    """A module's contribution to the assistant (PROMPT §11 deliverable).

    A module registers one ``ModuleToolSet``. It declares its intents and supplies
    the read handlers and the ``build_*_draft`` builders. It never commits a write.
    """

    module: str = "base"

    def module_descriptor(self) -> ModuleAssistantDescriptor:
        """Return module routing metadata.

        The default keeps existing toolsets compatible while modules migrate to
        richer, module-owned prompt metadata.
        """
        descriptions = [spec.description for spec in self.intents() if spec.description]
        return ModuleAssistantDescriptor(
            module=self.module,
            display_title=self.module.replace("_", " ").title(),
            description=descriptions[0] if descriptions else f"Operations in {self.module}.",
        )

    def task_descriptors(self) -> List[TaskAssistantDescriptor]:
        """Return task routing metadata; legacy ``intents`` are adapted safely."""
        return [
            TaskAssistantDescriptor(
                module=spec.module or self.module,
                intent=spec.name,
                kind=spec.kind if spec.kind in {"read", "write", "file", "general", "clarify"} else "general",
                required_permission=spec.permission,
                description=spec.description,
                target_action=spec.target_action,
            )
            for spec in self.intents()
        ]

    def specialist_instructions(self, intent: str) -> tuple[str, ...]:
        """Return optional module-owned notes for the selected task only."""
        for descriptor in self.task_descriptors():
            if descriptor.intent == intent:
                return descriptor.specialist_notes
        return ()

    def intents(self) -> List[IntentSpec]:  # pragma: no cover - interface
        raise NotImplementedError

    # Read handlers return a dict shaped for the runner:
    #   {answer, retrieved_items, summary, citations}
    async def handle_read(self, *, intent: str, db, user: User, slots: dict) -> dict:  # pragma: no cover
        raise NotImplementedError

    # Build (but never commit) a draft for a write intent. Returns DraftData.
    def build_draft(self, *, intent: str, db, user: User, slots: dict, attachments: list):  # pragma: no cover
        raise NotImplementedError


_REGISTRY: Dict[str, ModuleToolSet] = {}


def register_toolset(toolset: ModuleToolSet) -> None:
    _REGISTRY[toolset.module] = toolset


def get_toolset(module: str) -> Optional[ModuleToolSet]:
    return _REGISTRY.get(module)


def all_toolsets() -> List[ModuleToolSet]:
    return list(_REGISTRY.values())


def _all_module_intents() -> List[IntentSpec]:
    intents: List[IntentSpec] = []
    for toolset in _REGISTRY.values():
        intents.extend(toolset.intents())
    return intents


def assemble_intents(user: User) -> List[IntentSpec]:
    """Build the per-request intent set, dropping intents the user can't access.

    The restricted tasks are never named back to the user: if everything is
    filtered out, only ``general`` / ``clarify`` remain.
    """
    permitted: List[IntentSpec] = []

    for spec in _all_module_intents():
        if spec.permission is None or has_permission(user, spec.permission):
            permitted.append(spec)

    # general requires assistant:chat; clarify is always available.
    if has_permission(user, GENERAL_INTENT.permission):
        permitted.append(HELP_INTENT)
        permitted.append(GENERAL_INTENT)
    permitted.append(CLARIFY_INTENT)

    return permitted


def assemble_module_descriptors(user: User) -> List[ModuleAssistantDescriptor]:
    """Return only modules with at least one task accessible to ``user``."""
    if not has_permission(user, GENERAL_INTENT.permission):
        return []
    descriptors: List[ModuleAssistantDescriptor] = []
    for toolset in _REGISTRY.values():
        if assemble_task_descriptors(user, toolset.module):
            descriptors.append(toolset.module_descriptor())
    return descriptors


def assemble_task_descriptors(user: User, module: str) -> List[TaskAssistantDescriptor]:
    """Return only permitted tasks owned by the selected module."""
    if not has_permission(user, GENERAL_INTENT.permission):
        return []
    toolset = get_toolset(module)
    if toolset is None:
        return []
    permitted: List[TaskAssistantDescriptor] = []
    for descriptor in toolset.task_descriptors():
        if descriptor.module != module:
            continue
        permission = descriptor.required_permission
        if permission is None or has_permission(user, permission):
            permitted.append(descriptor)
    return permitted


def find_intent(user: User, name: str) -> Optional[IntentSpec]:
    for spec in assemble_intents(user):
        if spec.name == name:
            return spec
    return None
