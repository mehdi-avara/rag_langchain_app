"""Financial-management ``ModuleToolSet`` for the AI assistant (PROMPT §3, §4, §11).

Wraps the module's **existing service functions** — never re-implements them and
never issues loopback HTTP. Read intents call services directly (RBAC re-checked
first); write intents return a ``DraftData`` carrying the module's own create/
update endpoint as the ``commit_target`` — the frontend commits there, the
assistant never writes.

This is the only place that may import ``financial_management`` services/models;
the generic assistant core stays module-agnostic.
"""

from __future__ import annotations

from decimal import Decimal, InvalidOperation
from typing import List, Optional

from sqlalchemy.orm import Session

from Models import User

from assistant.registry import DraftData, IntentSpec, ModuleToolSet, register_toolset
from assistant.rbac import ensure_permission

from .models import FinancialAccessMethod, FinancialCurrency, FinancialDirection
from .schemas import FinancialReceiptSemanticHit
from .services import (
    answer_receipts_question,
    summarize_receipts,
)
from .search.service import search_receipt_hits

MODULE = "financial_management"
_API_PREFIX = "/financial_management"

# Permission strings (PROMPT §3 table).
P_SEARCH = "financial_management:receipts:search"
P_READ = "financial_management:receipts:read"
P_ASK = "financial_management:receipts:ask"
P_RECEIPT_CREATE = "financial_management:receipts:create"
P_RECEIPT_UPDATE = "financial_management:receipts:update"
P_CARD_CREATE = "financial_management:cards:create"
P_CARD_UPDATE = "financial_management:cards:update"
P_CUSTOMER_CREATE = "financial_management:customers:create"
P_CUSTOMER_UPDATE = "financial_management:customers:update"
P_COMMENT_CREATE = "financial_management:receipt_comments:create"
P_FILE_CREATE = "financial_management:receipt_files:create"


def _hit_to_item(hit: FinancialReceiptSemanticHit) -> dict:
    data = hit.model_dump(mode="json")
    return {
        "resource_type": "receipt",
        "source_type": "financial_receipt",
        "citation_key": f"receipt:{hit.receipt_id}",
        "title": f"Receipt #{hit.receipt_id}",
        "data": data,
    }


def _str(slots: dict, *keys: str) -> Optional[str]:
    for key in keys:
        value = slots.get(key)
        if value is not None and str(value).strip():
            return str(value).strip()
    return None


def _decimal(value) -> Optional[Decimal]:
    if value is None or str(value).strip() == "":
        return None
    try:
        return Decimal(str(value))
    except (InvalidOperation, ValueError):
        return None


def _enum_value(enum_cls, value) -> Optional[str]:
    if value is None:
        return None
    raw = str(value).strip()
    for member in enum_cls:
        if raw.lower() in {member.value.lower(), member.name.lower()}:
            return member.value
    return None


class FinancialAssistantToolSet(ModuleToolSet):
    module = MODULE

    def intents(self) -> List[IntentSpec]:
        return [
            IntentSpec(
                name="search_receipts",
                description=(
                    "Find receipts / payments by description, counterparty, card, tracking "
                    "number, amount, or date — e.g. 'find the receipt for pump X', "
                    "'show payments to ACME'. A lookup, not a totals question."
                ),
                kind="read",
                permission=P_SEARCH,
                module=MODULE,
            ),
            IntentSpec(
                name="summarize_finance",
                description=(
                    "Totals / KPIs over receipts — 'how much did we spend this month', "
                    "net in/out, sums by currency. A roll-up, not a single-receipt lookup."
                ),
                kind="read",
                permission=P_READ,
                module=MODULE,
            ),
            IntentSpec(
                name="ask_finance",
                description=(
                    "A grounded natural-language question answered from receipt content — "
                    "e.g. 'what was the last invoice from ACME about'. Returns a cited answer."
                ),
                kind="read",
                permission=P_ASK,
                module=MODULE,
            ),
            IntentSpec(
                name="add_receipt",
                description=(
                    "Create a new receipt — e.g. 'add a receipt: 1.2M IRR to ACME on …', "
                    "often with a photo/PDF of the receipt."
                ),
                kind="write",
                permission=P_RECEIPT_CREATE,
                module=MODULE,
                target_action="create_receipt",
            ),
            IntentSpec(
                name="update_receipt",
                description="Change fields of an existing receipt — e.g. 'change the amount of receipt 42 to …'.",
                kind="write",
                permission=P_RECEIPT_UPDATE,
                module=MODULE,
                target_action="update_receipt",
            ),
            IntentSpec(
                name="add_card",
                description="Add a new credit/bank card to the financial module.",
                kind="write",
                permission=P_CARD_CREATE,
                module=MODULE,
                target_action="create_card",
            ),
            IntentSpec(
                name="update_card",
                description="Update an existing credit/bank card.",
                kind="write",
                permission=P_CARD_UPDATE,
                module=MODULE,
                target_action="update_card",
            ),
            IntentSpec(
                name="add_customer",
                description="Add a new customer / counterparty.",
                kind="write",
                permission=P_CUSTOMER_CREATE,
                module=MODULE,
                target_action="create_customer",
            ),
            IntentSpec(
                name="update_customer",
                description="Update an existing customer / counterparty.",
                kind="write",
                permission=P_CUSTOMER_UPDATE,
                module=MODULE,
                target_action="update_customer",
            ),
            IntentSpec(
                name="add_receipt_comment",
                description="Attach a note / comment to a receipt.",
                kind="write",
                permission=P_COMMENT_CREATE,
                module=MODULE,
                target_action="add_receipt_comment",
            ),
            IntentSpec(
                name="attach_receipt_file",
                description="Attach / upload a file to a receipt.",
                kind="file",
                permission=P_FILE_CREATE,
                module=MODULE,
                target_action="attach_receipt_file",
            ),
        ]

    # ------------------------------------------------------------------
    # Read handlers (RBAC re-checked before each service call — PROMPT §5)
    # ------------------------------------------------------------------
    async def handle_read(self, *, intent: str, db: Session, user: User, slots: dict) -> dict:
        if intent == "search_receipts":
            return self._search(db, user, slots)
        if intent == "summarize_finance":
            return self._summarize(db, user, slots)
        if intent == "ask_finance":
            return await self._ask(db, user, slots)
        raise ValueError(f"Unsupported read intent: {intent}")

    def _search(self, db: Session, user: User, slots: dict) -> dict:
        ensure_permission(user, P_SEARCH)
        query = _str(slots, "query", "text") or ""
        mode = _str(slots, "mode") or "hybrid"
        ids = slots.get("ids") or slots.get("receipt_ids") or []
        try:
            limit = int(slots.get("limit") or 10)
        except (TypeError, ValueError):
            limit = 10

        hits = search_receipt_hits(
            db=db,
            current_user=user,
            query_text=query,
            mode=mode if mode in {"keyword", "semantic", "vector", "hybrid"} else "hybrid",
            receipt_ids=list(ids) if ids else None,
            limit=max(1, min(limit, 50)),
        )
        items = [_hit_to_item(hit) for hit in hits]
        return {
            "retrieved_items": items,
            "citations": [item["citation_key"] for item in items],
            "answer": "",
            "summary": None,
        }

    def _summarize(self, db: Session, user: User, slots: dict) -> dict:
        ensure_permission(user, P_READ)
        summary = summarize_receipts(
            db,
            user,
            direction=_str(slots, "direction"),
            credit_card_id=slots.get("credit_card_id"),
            date_from=slots.get("date_from"),
            date_to=slots.get("date_to"),
        )
        return {
            "retrieved_items": [],
            "citations": [],
            "answer": "",
            "summary": summary.model_dump(mode="json"),
        }

    async def _ask(self, db: Session, user: User, slots: dict) -> dict:
        ensure_permission(user, P_ASK)
        question = _str(slots, "question", "query", "text") or ""
        mode = _str(slots, "mode") or "hybrid"
        ids = slots.get("receipt_ids") or slots.get("ids") or []
        response = await answer_receipts_question(
            db,
            user,
            question=question,
            mode=mode if mode in {"keyword", "semantic", "vector", "hybrid"} else "hybrid",
            receipt_ids=list(ids) if ids else None,
        )
        items = [_hit_to_item(hit) for hit in response.references]
        return {
            "retrieved_items": items,
            "citations": [f"receipt:{rid}" for rid in response.used_receipt_ids],
            "answer": response.answer,
            "summary": None,
        }

    # ------------------------------------------------------------------
    # Draft builders — assemble payload + commit_target, NEVER write (PROMPT §4)
    # ------------------------------------------------------------------
    def build_draft(self, *, intent: str, db: Session, user: User, slots: dict, attachments: list) -> DraftData:
        builder = {
            "add_receipt": self._build_create_receipt,
            "update_receipt": self._build_update_receipt,
            "add_card": self._build_create_card,
            "update_card": self._build_update_card,
            "add_customer": self._build_create_customer,
            "update_customer": self._build_update_customer,
            "add_receipt_comment": self._build_add_receipt_comment,
            "attach_receipt_file": self._build_attach_receipt_file,
        }.get(intent)
        if builder is None:
            raise ValueError(f"Unsupported write intent: {intent}")
        return builder(db, user, slots, attachments or [])

    @staticmethod
    def _invalid(
        target_action: str,
        missing: list,
        errors: dict,
        question: str,
        partial_payload: dict | None = None,
    ) -> DraftData:
        # Returns the object completed SO FAR (``partial_payload``) plus the
        # still-missing fields named as nouns in ``validation.missing`` — so the
        # frontend can show the half-filled form and highlight what to add.
        return DraftData(
            target_module=MODULE,
            target_action=target_action,
            payload=partial_payload or {},
            commit_target={},
            validation={"valid": False, "missing": missing, "errors": errors},
            valid=False,
            clarify_question=question,
        )

    def _build_create_receipt(self, db, user, slots, attachments) -> DraftData:
        ensure_permission(user, P_RECEIPT_CREATE)  # early check — no un-committable draft

        description = _str(slots, "description")
        amount = _decimal(slots.get("amount"))
        direction = _enum_value(FinancialDirection, slots.get("direction"))
        credit_card_id = slots.get("credit_card_id")
        receipt_date = _str(slots, "receipt_date", "date")
        counterparty_name = _str(slots, "counterparty_name", "counterparty")
        customer_id = slots.get("customer_id")
        currency = _enum_value(FinancialCurrency, slots.get("currency")) or FinancialCurrency.TOMAN.value

        # Assemble whatever is known so far (the partial object).
        payload: dict = {"currency": currency}
        if description:
            payload["description"] = description
        if amount is not None and amount > 0:
            payload["amount"] = str(amount)
        if direction:
            payload["direction"] = direction
        if credit_card_id:
            payload["credit_card_id"] = credit_card_id
        if receipt_date:
            payload["receipt_date"] = receipt_date
        if counterparty_name:
            payload["counterparty_name"] = counterparty_name
        if customer_id:
            payload["customer_id"] = customer_id
        if _str(slots, "tracking_number"):
            payload["tracking_number"] = _str(slots, "tracking_number")
        rate = _decimal(slots.get("exchange_rate_to_base"))
        if rate is not None:
            payload["exchange_rate_to_base"] = str(rate)

        # Missing required fields, named as nouns (PROMPT: localize labels later).
        missing: list = []
        if not description:
            missing.append("description")
        if amount is None or amount <= 0:
            missing.append("amount")
        if not direction:
            missing.append("direction")
        if not credit_card_id:
            missing.append("credit card")
        if not receipt_date:
            missing.append("receipt date")
        if not counterparty_name and not customer_id:
            missing.append("counterparty")

        if missing:
            return self._invalid(
                "create_receipt",
                missing,
                {},
                "I still need: " + ", ".join(missing) + ".",
                partial_payload=payload,
            )

        return DraftData(
            target_module=MODULE,
            target_action="create_receipt",
            payload=payload,
            commit_target={
                "method": "POST",
                "endpoint": f"{_API_PREFIX}/receipts",
                "permission": P_RECEIPT_CREATE,
            },
            attachments=list(attachments),
            validation={"valid": True},
        )

    def _build_update_receipt(self, db, user, slots, attachments) -> DraftData:
        ensure_permission(user, P_RECEIPT_UPDATE)
        receipt_id = slots.get("receipt_id") or slots.get("id")
        if not receipt_id:
            return self._invalid(
                "update_receipt", ["receipt_id"], {}, "Which receipt should I update? Please give its id."
            )

        payload: dict = {}
        if _str(slots, "description"):
            payload["description"] = _str(slots, "description")
        amount = _decimal(slots.get("amount"))
        if amount is not None:
            payload["amount"] = str(amount)
        currency = _enum_value(FinancialCurrency, slots.get("currency"))
        if currency:
            payload["currency"] = currency
        direction = _enum_value(FinancialDirection, slots.get("direction"))
        if direction:
            payload["direction"] = direction
        for key in ("tracking_number", "counterparty_name", "receipt_date"):
            value = _str(slots, key)
            if value:
                payload[key] = value
        if slots.get("credit_card_id"):
            payload["credit_card_id"] = slots["credit_card_id"]
        if "customer_id" in slots:
            payload["customer_id"] = slots["customer_id"]
        rate = _decimal(slots.get("exchange_rate_to_base"))
        if rate is not None:
            payload["exchange_rate_to_base"] = str(rate)

        if not payload:
            return self._invalid(
                "update_receipt", [], {"fields": "no updatable fields provided"},
                "What should I change on this receipt?",
            )

        return DraftData(
            target_module=MODULE,
            target_action="update_receipt",
            payload=payload,
            commit_target={
                "method": "PATCH",
                "endpoint": f"{_API_PREFIX}/receipts/{receipt_id}",
                "permission": P_RECEIPT_UPDATE,
                "entity_id": receipt_id,
            },
            attachments=list(attachments),
            validation={"valid": True},
        )

    def _build_create_card(self, db, user, slots, attachments) -> DraftData:
        ensure_permission(user, P_CARD_CREATE)
        title = _str(slots, "title")
        card_number = _str(slots, "card_number")
        payload: dict = {}
        if title:
            payload["title"] = title
        if card_number:
            payload["card_number"] = card_number
        for key in ("bank_name", "account_owner_name", "description"):
            value = _str(slots, key)
            if value:
                payload[key] = value
        missing = []
        if not title:
            missing.append("title")
        if not card_number:
            missing.append("card number")
        if missing:
            return self._invalid(
                "create_card", missing, {}, "I still need: " + ", ".join(missing) + ".",
                partial_payload=payload,
            )
        return DraftData(
            target_module=MODULE,
            target_action="create_card",
            payload=payload,
            commit_target={"method": "POST", "endpoint": f"{_API_PREFIX}/cards", "permission": P_CARD_CREATE},
            validation={"valid": True},
        )

    def _build_update_card(self, db, user, slots, attachments) -> DraftData:
        ensure_permission(user, P_CARD_UPDATE)
        card_id = slots.get("card_id") or slots.get("id")
        if not card_id:
            return self._invalid("update_card", ["card_id"], {}, "Which card should I update? Please give its id.")
        payload: dict = {}
        for key in ("title", "card_number", "bank_name", "account_owner_name", "description"):
            value = _str(slots, key)
            if value:
                payload[key] = value
        if "is_active" in slots and slots["is_active"] is not None:
            payload["is_active"] = bool(slots["is_active"])
        if not payload:
            return self._invalid("update_card", [], {"fields": "no updatable fields"}, "What should I change on this card?")
        return DraftData(
            target_module=MODULE,
            target_action="update_card",
            payload=payload,
            commit_target={
                "method": "PATCH",
                "endpoint": f"{_API_PREFIX}/cards/{card_id}",
                "permission": P_CARD_UPDATE,
                "entity_id": card_id,
            },
            validation={"valid": True},
        )

    def _build_create_customer(self, db, user, slots, attachments) -> DraftData:
        ensure_permission(user, P_CUSTOMER_CREATE)
        name = _str(slots, "name")
        phone = _str(slots, "phone_number1", "phone")
        access_method = _enum_value(FinancialAccessMethod, slots.get("access_method"))
        payload: dict = {}
        if name:
            payload["name"] = name
        if phone:
            payload["phone_number1"] = phone
        if access_method:
            payload["access_method"] = access_method
        for key in ("phone_number2", "email", "description"):
            value = _str(slots, key)
            if value:
                payload[key] = value
        missing = []
        if not name:
            missing.append("name")
        if not phone:
            missing.append("phone number")
        if not access_method:
            missing.append("access method")
        if missing:
            return self._invalid(
                "create_customer", missing, {},
                "I still need: " + ", ".join(missing) + ".",
                partial_payload=payload,
            )
        return DraftData(
            target_module=MODULE,
            target_action="create_customer",
            payload=payload,
            commit_target={"method": "POST", "endpoint": f"{_API_PREFIX}/customers", "permission": P_CUSTOMER_CREATE},
            validation={"valid": True},
        )

    def _build_update_customer(self, db, user, slots, attachments) -> DraftData:
        ensure_permission(user, P_CUSTOMER_UPDATE)
        customer_id = slots.get("customer_id") or slots.get("id")
        if not customer_id:
            return self._invalid("update_customer", ["customer_id"], {}, "Which customer should I update? Please give its id.")
        payload: dict = {}
        for key in ("name", "phone_number1", "phone_number2", "email", "description"):
            value = _str(slots, key)
            if value:
                payload[key] = value
        access_method = _enum_value(FinancialAccessMethod, slots.get("access_method"))
        if access_method:
            payload["access_method"] = access_method
        if not payload:
            return self._invalid("update_customer", [], {"fields": "no updatable fields"}, "What should I change on this customer?")
        return DraftData(
            target_module=MODULE,
            target_action="update_customer",
            payload=payload,
            commit_target={
                "method": "PATCH",
                "endpoint": f"{_API_PREFIX}/customers/{customer_id}",
                "permission": P_CUSTOMER_UPDATE,
                "entity_id": customer_id,
            },
            validation={"valid": True},
        )

    def _build_add_receipt_comment(self, db, user, slots, attachments) -> DraftData:
        ensure_permission(user, P_COMMENT_CREATE)
        receipt_id = slots.get("receipt_id")
        comment_id = slots.get("comment_id")
        if not receipt_id:
            return self._invalid("add_receipt_comment", ["receipt_id"], {}, "Which receipt should the note be attached to?")
        if not comment_id:
            return self._invalid(
                "add_receipt_comment", ["comment_id"], {},
                "Which existing comment should I link? (creating a new comment first is a separate step)",
            )
        payload = {"comment_id": comment_id}
        note = _str(slots, "note")
        if note:
            payload["note"] = note
        return DraftData(
            target_module=MODULE,
            target_action="add_receipt_comment",
            payload=payload,
            commit_target={
                "method": "POST",
                "endpoint": f"{_API_PREFIX}/receipts/{receipt_id}/comments",
                "permission": P_COMMENT_CREATE,
                "entity_id": receipt_id,
            },
            validation={"valid": True},
        )

    def _build_attach_receipt_file(self, db, user, slots, attachments) -> DraftData:
        ensure_permission(user, P_FILE_CREATE)
        receipt_id = slots.get("receipt_id")
        asset_ids = list(attachments) or list(slots.get("asset_ids") or [])
        missing = []
        if not receipt_id:
            missing.append("receipt_id")
        if not asset_ids:
            missing.append("file")
        if missing:
            return self._invalid(
                "attach_receipt_file", missing, {},
                "To attach a file I need a receipt id and an uploaded file.",
            )
        asset_id = asset_ids[0]
        return DraftData(
            target_module=MODULE,
            target_action="attach_receipt_file",
            payload={"checksum": _str(slots, "checksum")} if _str(slots, "checksum") else {},
            commit_target={
                "method": "POST",
                "endpoint": f"{_API_PREFIX}/receipts/{receipt_id}/files/complete-upload/{asset_id}",
                "permission": P_FILE_CREATE,
                "entity_id": receipt_id,
            },
            attachments=asset_ids,
            validation={"valid": True},
        )


def register() -> FinancialAssistantToolSet:
    toolset = FinancialAssistantToolSet()
    register_toolset(toolset)
    return toolset


# Register on import so the assistant registry is populated wherever this module
# (or the app) is loaded. ``register_toolset`` is idempotent (keyed by module).
register()
