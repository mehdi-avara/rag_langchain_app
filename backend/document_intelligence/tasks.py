"""
Celery tasks for Document Intelligence.

The Celery app is imported from the project's existing worker entry point.
If no Celery app exists yet, we create a minimal one here using the Redis URL
from settings.  The project's docker-compose already has a `celery` service,
so this worker will pick up the task automatically.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime

from celery import Celery
from sqlalchemy.orm import Session

from db.session import SessionLocal
from document_intelligence.models import (
    DIJobStatus,
    DIMethod,
    DocumentIntelligenceJob,
    DocumentMethodRun,
    DocumentPageArtifact,
)
from document_intelligence.services.pdf_artifacts import process_page_artifacts
from document_intelligence.services.llm_vlm_method import run_llm_vlm_pipeline
from Models import Document
from settings import get_settings

logger = logging.getLogger(__name__)
settings = get_settings()

# ---------------------------------------------------------------------------
# Celery application
# Try to import the shared app first; fall back to creating one.
# ---------------------------------------------------------------------------

try:
    from celery_app import celery_app  # type: ignore[import]
except ImportError:
    celery_app = Celery(
        "document_intelligence",
        broker=settings.redis_url,
        backend=settings.redis_url,
    )
    celery_app.conf.update(
        task_serializer="json",
        result_serializer="json",
        accept_content=["json"],
        task_acks_late=True,
        worker_prefetch_multiplier=1,
    )


# ---------------------------------------------------------------------------
# Helper: run async coroutine in a Celery (sync) worker thread
# ---------------------------------------------------------------------------

def _run_async(coro):
    """Run an async coroutine from a sync context (Celery task)."""
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


# ---------------------------------------------------------------------------
# Main Celery task
# ---------------------------------------------------------------------------

@celery_app.task(
    bind=True,
    name="document_intelligence.process_document",
    max_retries=2,
    default_retry_delay=60,
)
def process_document_task(self, job_id: int) -> dict:
    """
    Run the Document Intelligence pipeline for a given job.

    Steps
    -----
    1. Load the job and document from the database.
    2. Build / reuse page artifacts.
    3. For each requested method, create a DocumentMethodRun and execute.
    4. Mark the job completed (or failed).

    Returns a summary dict.
    """
    db: Session = SessionLocal()

    try:
        # --- Load job ---
        job: DocumentIntelligenceJob = (
            db.query(DocumentIntelligenceJob)
            .filter(DocumentIntelligenceJob.id == job_id)
            .first()
        )
        if not job:
            logger.error("Job %d not found.", job_id)
            return {"error": "job_not_found", "job_id": job_id}

        if job.status not in (DIJobStatus.QUEUED, DIJobStatus.RUNNING):
            logger.warning("Job %d already in status %s – skipping.", job_id, job.status)
            return {"status": job.status, "job_id": job_id}

        # Mark running
        job.status = DIJobStatus.RUNNING
        job.started_at = datetime.utcnow()
        db.commit()

        # --- Load document ---
        document: Document = (
            db.query(Document).filter(Document.id == job.document_id).first()
        )
        if not document:
            _fail_job(db, job, "Document not found.")
            return {"error": "document_not_found", "job_id": job_id}

        # --- Page artifacts ---
        logger.info("[Task] Building page artifacts for doc %d …", document.id)
        artifacts = process_page_artifacts(db, document, force=False)
        db.commit()

        # Reload ordered artifacts
        artifacts = (
            db.query(DocumentPageArtifact)
            .filter(DocumentPageArtifact.document_id == document.id)
            .order_by(DocumentPageArtifact.page_num)
            .all()
        )

        # --- Run requested methods ---
        methods = job.methods_requested or [DIMethod.LLM_VLM]
        results_summary = {}

        for method_name in methods:
            logger.info("[Task] Running method '%s' for job %d …", method_name, job_id)

            # Create or reuse method run row
            method_run = (
                db.query(DocumentMethodRun)
                .filter(
                    DocumentMethodRun.job_id == job_id,
                    DocumentMethodRun.method == method_name,
                )
                .first()
            )
            if not method_run:
                method_run = DocumentMethodRun(
                    job_id=job_id,
                    method=method_name,
                    status="running",
                )
                db.add(method_run)
                db.flush()

            try:
                if method_name == DIMethod.LLM_VLM:
                    _run_async(
                        run_llm_vlm_pipeline(
                            db=db,
                            job_id=job_id,
                            document=document,
                            artifacts=artifacts,
                            method_run=method_run,
                        )
                    )
                else:
                    logger.warning(
                        "Method '%s' not yet implemented – skipping.", method_name
                    )
                    method_run.status = "skipped"
                    method_run.completed_at = datetime.utcnow()

                db.commit()
                results_summary[method_name] = "completed"

            except Exception as exc:
                logger.exception(
                    "Method '%s' failed for job %d: %s", method_name, job_id, exc
                )
                method_run.status = "failed"
                method_run.error_message = str(exc)
                method_run.completed_at = datetime.utcnow()
                db.commit()
                results_summary[method_name] = f"failed: {exc}"

        # --- Mark job complete ---
        job.status = DIJobStatus.COMPLETED
        job.completed_at = datetime.utcnow()
        db.commit()

        logger.info("[Task] Job %d completed: %s", job_id, results_summary)
        return {"job_id": job_id, "status": "completed", "methods": results_summary}

    except Exception as exc:
        logger.exception("Unexpected error in job %d: %s", job_id, exc)
        try:
            _fail_job(db, db.query(DocumentIntelligenceJob).get(job_id), str(exc))
        except Exception:
            pass
        raise self.retry(exc=exc)

    finally:
        db.close()


def _fail_job(db: Session, job: DocumentIntelligenceJob | None, message: str) -> None:
    if job is None:
        return
    job.status = DIJobStatus.FAILED
    job.error_message = message
    job.completed_at = datetime.utcnow()
    db.commit()
