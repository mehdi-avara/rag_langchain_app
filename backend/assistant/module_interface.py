"""Provider abstraction + resource registry for reference resolution (FK-resolution task).

Generic and module-agnostic. A module registers each resolvable / lookup-able
resource (a card, a customer, …) as a :class:`ResourceSpec`, supplying a
:class:`SearchProvider` that knows how to reach the module's search.

**Function-call now, HTTP later.** Today the only provider is
:class:`FunctionSearchProvider`, which calls a module *interface function* in
process (master plan §12.4 — never loopback HTTP, never import another module's
models here). A future ``HttpSearchProvider`` can implement the same
``.search(...)`` signature and be registered instead — **no caller changes**.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional, Protocol


@dataclass
class Candidate:
    """One search hit, normalized for resolution + display."""
    id: int
    match_text: str          # the primary name/title, used for exact-match comparison
    label: str               # human-readable label shown to the user
    data: Dict[str, Any] = field(default_factory=dict)


class SearchProvider(Protocol):
    """How the assistant reaches a module's search. Function-call today, HTTP later."""
    def search(self, *, db, user, query: str, ids: Optional[List[int]] = None,
               limit: int = 10) -> List[Candidate]: ...


class FunctionSearchProvider:
    """Adapter that calls a module INTERFACE FUNCTION directly (in-process).

    ``search_fn(db, current_user, query_text, ids=..., limit=...)`` returns module
    rows; ``to_candidate(row)`` maps each row to a :class:`Candidate`. To switch to
    HTTP later, implement an ``HttpSearchProvider`` with the same ``.search(...)``
    signature and register it instead — no caller changes.
    """
    def __init__(self, search_fn: Callable, to_candidate: Callable[[Any], Candidate]):
        self._search_fn = search_fn
        self._to_candidate = to_candidate

    def search(self, *, db, user, query, ids=None, limit=10) -> List[Candidate]:
        rows = self._search_fn(db, user, query, ids=ids, limit=limit) if ids is not None \
            else self._search_fn(db, user, query, limit=limit)
        return [self._to_candidate(r) for r in rows]


@dataclass(frozen=True)
class ResourceSpec:
    """A resolvable / lookup-able resource (e.g. a financial customer)."""
    key: str                                  # e.g. "financial_customer"
    read_permission: str                      # required to search/read
    provider: SearchProvider
    create_permission: Optional[str] = None   # required to create (for missing -> create)
    create_endpoint: Optional[str] = None     # e.g. "/financial_management/customers"
    create_method: str = "POST"
    suggestion_from: Optional[Callable[[str, dict], dict]] = None  # (raw_text, slots) -> payload
    # Context-aware missing-resource fallback. It can enrich the create payload
    # from another module's service or suppress an unsafe suggestion.
    missing_suggestion_from: Optional[
        Callable[[Any, Any, str, dict], Optional[dict]]
    ] = None


_RESOURCES: Dict[str, ResourceSpec] = {}


def register_resource(spec: ResourceSpec) -> None:
    _RESOURCES[spec.key] = spec


def get_resource(key: str) -> Optional[ResourceSpec]:
    return _RESOURCES.get(key)
