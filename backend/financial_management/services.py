from __future__ import annotations

import re
from datetime import date
from decimal import Decimal
from typing import List, Optional, Sequence

from fastapi import HTTPException
from sqlalchemy.orm import Session

from components import generate_embeddings_for_chunks
from components.llm import llm_client
from settings import get_settings
from Models import User

from .models import FinancialCard, FinancialCustomer, FinancialReceipt, FinancialReceiptFile
from .schemas import (
    FinancialCardOut,
    FinancialCardSummaryOut,
    FinancialCustomerOut,
    FinancialCustomerSummaryOut,
    FinancialReceiptFileOut,
    FinancialReceiptOut,
)


settings = get_settings()
_RECEIPT_CITATION_RE = re.compile(r"\[receipt:(\d+)\]")


def is_admin(user: User) -> bool:
    return getattr(user, "role", None) == "admin"


def tenant_filter_id(current_user: User) -> int:
    return current_user.company_id


def owner_filter_id(current_user: User) -> int:
    return current_user.id


def get_card_or_404(db: Session, card_id: int, current_user: User) -> FinancialCard:
    card = (
        db.query(FinancialCard)
        .filter(
            FinancialCard.id == card_id,
            FinancialCard.company_id == tenant_filter_id(current_user),
        )
        .first()
    )

    if not card:
        raise HTTPException(status_code=404, detail="Financial card not found")

    return card


def get_receipt_or_404(db: Session, receipt_id: int, current_user: User) -> FinancialReceipt:
    receipt = (
        db.query(FinancialReceipt)
        .filter(
            FinancialReceipt.id == receipt_id,
            FinancialReceipt.company_id == tenant_filter_id(current_user),
        )
        .first()
    )

    if not receipt:
        raise HTTPException(status_code=404, detail="Financial receipt not found")

    return receipt


def get_customer_or_404(db: Session, customer_id: int, current_user: User) -> FinancialCustomer:
    customer = (
        db.query(FinancialCustomer)
        .filter(
            FinancialCustomer.id == customer_id,
            FinancialCustomer.company_id == tenant_filter_id(current_user),
        )
        .first()
    )

    if not customer:
        raise HTTPException(status_code=404, detail="Financial customer not found")

    return customer


def normalize_card_number(card_number: str) -> str:
    return re.sub(r"\s+", "", card_number or "").strip()


def mask_card_number(card_number: str) -> str:
    return normalize_card_number(card_number)


def _div(a: int, b: int) -> int:
    return a // b


def solar_to_gregorian(value: str) -> date:
    try:
        jy, jm, jd = [int(part) for part in value.split("-", 2)]
    except ValueError as exc:
        raise HTTPException(status_code=422, detail="Invalid solar date format") from exc

    if not 1 <= jm <= 12:
        raise HTTPException(status_code=422, detail="Invalid solar month")

    max_day = 31 if jm <= 6 else 30
    if not 1 <= jd <= max_day:
        raise HTTPException(status_code=422, detail="Invalid solar day")

    jy += 1595
    days = -355668 + (365 * jy) + (_div(jy, 33) * 8) + _div((jy % 33) + 3, 4) + jd

    if jm < 7:
        days += (jm - 1) * 31
    else:
        days += ((jm - 7) * 30) + 186

    gy = 400 * _div(days, 146097)
    days %= 146097

    if days > 36524:
        gy += 100 * _div(days - 1, 36524)
        days = (days - 1) % 36524
        if days >= 365:
            days += 1

    if days > 365:
        gy += 4 * _div(days, 1461)
        days %= 1461

    if days > 365:
        gy += _div(days - 1, 365)
        days = (days - 1) % 365

    gd = days + 1
    leap = gy % 4 == 0 and (gy % 100 != 0 or gy % 400 == 0)
    month_lengths = [0, 31, 29 if leap else 28, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31]

    gm = 1
    while gm <= 12 and gd > month_lengths[gm]:
        gd -= month_lengths[gm]
        gm += 1

    return date(gy, gm, gd)


def gregorian_to_solar(value: date) -> str:
    gy = value.year
    gm = value.month
    gd = value.day
    g_d_m = [0, 31, 59, 90, 120, 151, 181, 212, 243, 273, 304, 334]

    gy2 = gy + 1 if gm > 2 else gy
    days = (
        355666
        + (365 * gy)
        + _div(gy2 + 3, 4)
        - _div(gy2 + 99, 100)
        + _div(gy2 + 399, 400)
        + gd
        + g_d_m[gm - 1]
    )

    jy = -1595 + (33 * _div(days, 12053))
    days %= 12053
    jy += 4 * _div(days, 1461)
    days %= 1461

    if days > 365:
        jy += _div(days - 1, 365)
        days = (days - 1) % 365

    if days < 186:
        jm = 1 + _div(days, 31)
        jd = 1 + (days % 31)
    else:
        jm = 7 + _div(days - 186, 30)
        jd = 1 + ((days - 186) % 30)

    return f"{jy:04d}-{jm:02d}-{jd:02d}"


def safe_embed_text(text: str) -> Optional[list[float]]:
    try:
        embeddings = generate_embeddings_for_chunks([text])
    except Exception:
        return None

    return embeddings[0] if embeddings else None


def ensure_receipt_embeddings(
    db: Session,
    current_user: User,
    receipt_ids: Optional[Sequence[int]] = None,
) -> None:
    query = db.query(FinancialReceipt).filter(
        FinancialReceipt.company_id == tenant_filter_id(current_user),
        FinancialReceipt.description_embedding.is_(None),
    )

    if receipt_ids is not None:
        if not receipt_ids:
            return
        query = query.filter(FinancialReceipt.id.in_(receipt_ids))

    changed = False

    for receipt in query.all():
        embedding = safe_embed_text(receipt.description)
        if embedding is None:
            continue
        receipt.description_embedding = embedding
        changed = True

    if changed:
        db.commit()


def card_to_summary(card: FinancialCard) -> FinancialCardSummaryOut:
    return FinancialCardSummaryOut(
        id=card.id,
        title=card.title,
        card_number=card.card_number,
        bank_name=card.bank_name,
        account_owner_name=card.account_owner_name,
        description=card.description,
        is_active=card.is_active,
    )


def card_to_out(card: FinancialCard) -> FinancialCardOut:
    return FinancialCardOut(
        **card_to_summary(card).model_dump(),
        company_id=card.company_id,
        owner_id=card.owner_id,
        created_at=card.created_at,
        updated_at=card.updated_at,
    )


def customer_to_summary(customer: FinancialCustomer) -> FinancialCustomerSummaryOut:
    return FinancialCustomerSummaryOut(
        id=customer.id,
        name=customer.name,
        phone_number1=customer.phone_number1,
        phone_number2=customer.phone_number2,
        access_method=customer.access_method,
        email=customer.email,
        description=customer.description,
    )


def customer_to_out(customer: FinancialCustomer) -> FinancialCustomerOut:
    return FinancialCustomerOut(
        **customer_to_summary(customer).model_dump(),
        company_id=customer.company_id,
        owner_id=customer.owner_id,
        created_at=customer.created_at,
        updated_at=customer.updated_at,
    )


def receipt_file_to_out(file_rec: FinancialReceiptFile) -> FinancialReceiptFileOut:
    return FinancialReceiptFileOut(
        id=file_rec.id,
        file_name=file_rec.file_name,
        media_address=file_rec.media_address,
        content_type=file_rec.content_type,
        asset_id=file_rec.asset_id,
        created_at=file_rec.created_at,
    )


def receipt_to_out(receipt: FinancialReceipt) -> FinancialReceiptOut:
    files = [receipt_file_to_out(file_rec) for file_rec in list(receipt.files or [])]

    return FinancialReceiptOut(
        id=receipt.id,
        company_id=receipt.company_id,
        owner_id=receipt.owner_id,
        description=receipt.description,
        tracking_number=receipt.tracking_number,
        amount=Decimal(str(receipt.amount)),
        direction=receipt.direction,
        counterparty_name=receipt.counterparty_name,
        receipt_date=receipt.receipt_date,
        credit_card=card_to_summary(receipt.credit_card),
        customer_id=receipt.customer_id,
        customer=customer_to_summary(receipt.customer) if receipt.customer is not None else None,
        embedding_status="available" if receipt.description_embedding is not None else "pending",
        created_at=receipt.created_at,
        updated_at=receipt.updated_at,
        files=files,
    )


def build_receipt_context(references: Sequence) -> str:
    if not references:
        return "(no references)"

    lines = ["Receipt references:"]

    for hit in references:
        tracking_number = hit.tracking_number or "-"
        lines.append(
            f"[receipt:{hit.receipt_id}] "
            f"date={hit.receipt_date} "
            f"direction={hit.direction} "
            f"amount={hit.amount} "
            f"counterparty={hit.counterparty_name} "
            f"tracking={tracking_number} "
            f"card={hit.card_title}({hit.card_number}) "
            f"description={hit.description}"
        )

    return "\n".join(lines)


async def generate_receipt_answer(question: str, references: Sequence) -> str:
    response = await llm_client.async_openai_client.chat.completions.create(
        model=settings.openai_model,
        temperature=settings.llm_temperature,
        messages=[
            {
                "role": "system",
                "content": (
                    "Answer using ONLY the provided financial receipt references.\n"
                    "If the references are insufficient, say so.\n"
                    "Cite sources strictly as [receipt:<receipt_id>]."
                ),
            },
            {
                "role": "user",
                "content": f"Question:\n{question}\n\nReferences:\n{build_receipt_context(references)}",
            },
        ],
    )

    return (response.choices[0].message.content or "").strip()


def parse_receipt_citations(answer: str) -> List[int]:
    seen: set[int] = set()
    citations: List[int] = []

    for match in _RECEIPT_CITATION_RE.findall(answer or ""):
        receipt_id = int(match)
        if receipt_id in seen:
            continue
        seen.add(receipt_id)
        citations.append(receipt_id)

    return citations

