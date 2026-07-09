from __future__ import annotations

from assistant.module_interface import Candidate, FunctionSearchProvider, ResourceSpec, register_resource
from shared.currency.services import list_currencies


P_CURRENCY_READ = "currencies:read"
P_CURRENCY_CREATE = "currencies:create"

_CURRENCY_ALIASES = {
    "toman": "IRT",
    "tomans": "IRT",
    "تومان": "IRT",
    "تومن": "IRT",
    "rial": "IRR",
    "rials": "IRR",
    "ریال": "IRR",
    "dollar": "USD",
    "dollars": "USD",
    "دلار": "USD",
    "euro": "EUR",
    "یورو": "EUR",
}


def _search_currencies_for_resolution(db, current_user, query_text, ids=None, limit=10):
    rows = list_currencies(db, active_only=True)
    if ids is not None:
        wanted = set(ids)
        rows = [row for row in rows if row.id in wanted]

    query = (query_text or "").strip().lower()
    if query:
        mapped_code = _CURRENCY_ALIASES.get(query)
        rows = [
            row for row in rows
            if (mapped_code and (row.code or "").upper() == mapped_code)
            or query in (row.code or "").lower()
            or query in (row.name or "").lower()
            or query in (row.symbol or "").lower()
        ]
    return rows[:limit]


def _currency_to_candidate(currency) -> Candidate:
    label = " - ".join(
        part for part in (currency.code, currency.name, currency.symbol) if part
    )
    return Candidate(
        id=currency.id,
        match_text=currency.code or currency.name or "",
        label=label or f"Currency #{currency.id}",
        data={
            "id": currency.id,
            "code": currency.code,
            "name": currency.name,
            "symbol": currency.symbol,
            "decimal_places": currency.decimal_places,
        },
    )


def register_shared_assistant_resources() -> None:
    register_resource(ResourceSpec(
        key="currency",
        read_permission=P_CURRENCY_READ,
        provider=FunctionSearchProvider(_search_currencies_for_resolution, _currency_to_candidate),
        create_permission=P_CURRENCY_CREATE,
        create_endpoint="/currencies",
        suggestion_from=lambda raw, slots: {
            "code": str(raw or "").strip().upper(),
            "name": raw,
        },
    ))
