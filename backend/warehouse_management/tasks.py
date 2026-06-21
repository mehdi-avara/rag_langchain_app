from __future__ import annotations

import logging

from fastapi import HTTPException

from core.celery.celery_app import celery_app
from db.session import db_session

from .services import (
    backfill_posted_goods_receipts,
    get_low_stock_items,
    process_grn_receipt,
)


logger = logging.getLogger(__name__)


@celery_app.task(
    name="warehouse_management.tasks.on_grn_posted",
    bind=True,
    max_retries=3,
    default_retry_delay=60,
    acks_late=True,
    reject_on_worker_lost=True,
)
def on_grn_posted(self, goods_receipt_id: int):
    try:
        with db_session() as db:
            result = process_grn_receipt(
                db=db,
                goods_receipt_id=goods_receipt_id,
            )
            db.commit()
            return result
    except HTTPException as exc:
        if exc.status_code == 404:
            logger.warning(
                "Skipping warehouse receipt for unavailable GRN %s",
                goods_receipt_id,
            )
            return {
                "goods_receipt_id": goods_receipt_id,
                "created_movements": 0,
                "skipped_movements": 0,
                "status": "skipped",
            }
        raise
    except Exception as exc:
        raise self.retry(exc=exc)


@celery_app.task(
    name="warehouse_management.tasks.backfill_posted_grns",
    bind=True,
    max_retries=3,
    default_retry_delay=60,
    acks_late=True,
    reject_on_worker_lost=True,
)
def backfill_posted_grns(self, company_id: int | None = None):
    try:
        with db_session() as db:
            result = backfill_posted_goods_receipts(
                db=db,
                company_id=company_id,
            )
            db.commit()
            return result
    except Exception as exc:
        raise self.retry(exc=exc)


@celery_app.task(
    name="warehouse_management.tasks.check_low_stock",
    bind=True,
    max_retries=3,
    default_retry_delay=60,
    acks_late=True,
    reject_on_worker_lost=True,
)
def check_low_stock(self, company_id: int):
    try:
        from types import SimpleNamespace

        with db_session() as db:
            user = SimpleNamespace(company_id=company_id)
            low_stock = get_low_stock_items(
                db=db,
                current_user=user,
            )
            result = {
                "company_id": company_id,
                "low_stock_item_ids": [
                    stock_item.id
                    for stock_item in low_stock
                ],
            }
            logger.warning("Warehouse low-stock result: %s", result)
            return result
    except Exception as exc:
        raise self.retry(exc=exc)
