"""Reference (foreign-key) resolution (FK-resolution task).

Real users say *"Ali's Mellat card"*, not ``credit_card_id=12``. The LLM passes
the **text**; the server resolves it deterministically against the module's
search and returns the matched record's **id** (for the frontend to submit) plus
a human-readable **label** (for the user to confirm).

- :func:`resolve_reference` is **pure** — ranking only, no DB, no model. ILIKE
  gives no scores, so it ranks by exact-name match then provider order. A future
  scored / trigram matcher can replace its body without changing callers.
- :func:`resolve_field` orchestrates: explicit-id short-circuit → RBAC check →
  provider search → rank → build a create-suggestion for a ``missing`` reference.

The LLM never touches the DB: all data access happens here, in deterministic
server-side Python that calls the module's registered :class:`SearchProvider`.
"""

from __future__ import annotations

from dataclasses import dataclass, field
import re
from time import perf_counter
from typing import Any, Dict, List, Optional

from Models import User

from .module_interface import Candidate, get_resource
from .rbac import has_permission

RESOLVED = "resolved"
AMBIGUOUS = "ambiguous"
MISSING = "missing"
_TOKEN_RE = re.compile(r"[\w\u0600-\u06ff]+", flags=re.UNICODE)
_STOPWORDS = {
    "a", "an", "and", "for", "from", "in", "model", "of", "the", "to",
    "از", "برای", "در", "مدل", "و",
}


@dataclass
class ReferenceResolution:
    field: str                                  # payload field this fills, e.g. "credit_card_id"
    raw: str                                    # the user's text (or the explicit id as string)
    status: str                                 # resolved | ambiguous | missing
    chosen: Optional[Dict[str, Any]] = None     # {"id": int, "label": str | None}
    alternatives: List[Dict[str, Any]] = field(default_factory=list)  # [{"id","label"}]
    create_suggestion: Optional[Dict[str, Any]] = None
    note: Optional[str] = None                  # e.g. "no_access", "explicit_id"

    def as_dict(self) -> dict:
        return {
            "field": self.field, "raw": self.raw, "status": self.status,
            "chosen": self.chosen, "alternatives": self.alternatives,
            "create_suggestion": self.create_suggestion, "note": self.note,
        }


def _slim(c: Candidate) -> Dict[str, Any]:
    return {"id": c.id, "label": c.label}


def _tokens(text: str) -> set[str]:
    return {
        token
        for token in _TOKEN_RE.findall((text or "").lower())
        if len(token) >= 2 and token not in _STOPWORDS
    }


def _candidate_text(candidate: Candidate) -> str:
    data_text = " ".join(str(value) for value in (candidate.data or {}).values() if value is not None)
    return " ".join(part for part in (candidate.match_text, candidate.label, data_text) if part)


def _plausible_candidates(raw: str, candidates: List[Candidate]) -> List[Candidate]:
    raw_tokens = _tokens(raw)
    if not raw_tokens:
        return candidates

    plausible: List[Candidate] = []
    for candidate in candidates:
        text = _candidate_text(candidate).lower()
        candidate_tokens = _tokens(text)
        if raw.strip().lower() in text:
            plausible.append(candidate)
            continue
        if raw_tokens & candidate_tokens:
            plausible.append(candidate)
            continue
        if any(token in text for token in raw_tokens):
            plausible.append(candidate)
    return plausible


def resolve_reference(field: str, raw_text: str, candidates: List[Candidate]) -> ReferenceResolution:
    """Pure ranking. ILIKE gives no scores, so rank by exact-name match then provider order.
    (A future scored matcher can replace this body without changing callers.)"""
    raw = (raw_text or "").strip()
    if not candidates:
        return ReferenceResolution(field=field, raw=raw, status=MISSING)

    norm = raw.lower()
    exact = [c for c in candidates if (c.match_text or "").strip().lower() == norm]

    if len(exact) == 1:
        chosen = exact[0]
        others = [c for c in candidates if c.id != chosen.id][:5]
        return ReferenceResolution(field, raw, RESOLVED, chosen=_slim(chosen),
                                   alternatives=[_slim(c) for c in others])

    plausible = _plausible_candidates(raw, candidates)
    if not plausible:
        return ReferenceResolution(field, raw, MISSING)

    if len(plausible) == 1:
        chosen = plausible[0]
        return ReferenceResolution(field, raw, RESOLVED, chosen=_slim(chosen))

    # ambiguous: default to first, return up to 5 alternatives
    chosen = plausible[0]
    alts = [c for c in plausible if c.id != chosen.id][:5]
    return ReferenceResolution(field, raw, AMBIGUOUS, chosen=_slim(chosen),
                               alternatives=[_slim(c) for c in alts])


def resolve_field(db, user: User, *, field: str, resource_key: str, raw_text: str,
                  slots: dict, explicit_id=None) -> ReferenceResolution:
    spec = get_resource(resource_key)
    if spec is None:
        return ReferenceResolution(field, raw_text or "", MISSING, note="unknown_resource")

    # Explicit numeric id always wins; skip search.
    if explicit_id is not None and str(explicit_id).strip().isdigit():
        return ReferenceResolution(field, str(explicit_id), RESOLVED,
                                   chosen={"id": int(explicit_id), "label": None}, note="explicit_id")

    if not has_permission(user, spec.read_permission):
        return ReferenceResolution(field, raw_text or "", MISSING, note="no_access")

    # When a selected module resolves a reference through another module's
    # provider, record the fan-out without persisting the raw query or results.
    from . import observability

    context = observability.current_execution_context()
    search_fn = getattr(spec.provider, "_search_fn", None)
    provider_module = getattr(search_fn, "__module__", "").split(".", 1)[0] or None
    is_cross_module = bool(
        context and provider_module and provider_module != context["selected_module"]
    )
    started = perf_counter()
    if is_cross_module:
        context["searched_modules"].add(provider_module)
        observability.record_event(
            db, context["run"], event_type="cross_module_search.started", stage="executor",
            status="started", selected_module=context["selected_module"],
            selected_task=context["selected_task"],
            payload={"target_module": provider_module, "resource_identifier": resource_key},
        )
    try:
        candidates = spec.provider.search(db=db, user=user, query=raw_text or "", limit=5)
    except Exception as exc:
        if is_cross_module:
            observability.record_event(
                db, context["run"], event_type="cross_module_search.failed", stage="executor",
                status="failed", severity="error", selected_module=context["selected_module"],
                selected_task=context["selected_task"], duration_ms=observability.duration_ms(started),
                error_code=getattr(exc, "code", "INTERNAL_SERVER_ERROR"),
                payload={"target_module": provider_module, "resource_identifier": resource_key},
            )
        raise
    if is_cross_module:
        observability.record_event(
            db, context["run"], event_type="cross_module_search.completed", stage="executor",
            status="completed", selected_module=context["selected_module"],
            selected_task=context["selected_task"], duration_ms=observability.duration_ms(started),
            payload={
                "target_module": provider_module, "resource_identifier": resource_key,
                "result_count": len(candidates),
            },
        )
    res = resolve_reference(field, raw_text or "", candidates)

    if res.status == MISSING and spec.create_endpoint and \
            (spec.create_permission is None or has_permission(user, spec.create_permission)):
        res.create_suggestion = {
            "resource": spec.key,
            "method": spec.create_method,
            "endpoint": spec.create_endpoint,
            "permission": spec.create_permission,
            "payload": (spec.suggestion_from(raw_text or "", slots) if spec.suggestion_from else {}),
        }
    return res
