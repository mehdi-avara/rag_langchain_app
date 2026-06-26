import asyncio
import os
from pathlib import Path

from core.celery.celery_app import celery_app
from core.chat_title import generate_chat_title_from_question
from core.simple_ingestion import run_mineru_on_file
from db.session import db_session
from Models import Chat, Document, DocumentVersion, DocumentStatusType, User
from settings import get_settings
from storage.manager import StorageManager

settings = get_settings()


def _set_document_status(doc_id: int, status: DocumentStatusType):
    with db_session() as db:
        db.query(Document).filter(Document.id == doc_id).update({
            Document.status: status.value
        })
        db.commit()


def _set_document_version_status(doc_id: int, document_version_id: int | None, status: DocumentStatusType):
    with db_session() as db:
        if document_version_id is not None:
            db.query(DocumentVersion).filter(DocumentVersion.id == document_version_id).update({
                DocumentVersion.status: status.value
            })

        doc = db.query(Document).filter(Document.id == doc_id).first()
        if doc and (document_version_id is None or doc.current_version_id == document_version_id):
            doc.status = status.value

        db.commit()


def _activate_document_version(doc_id: int, document_version_id: int | None):
    if document_version_id is None:
        _set_document_status(doc_id, DocumentStatusType.DONE)
        return

    with db_session() as db:
        version = db.query(DocumentVersion).filter(
            DocumentVersion.id == document_version_id,
            DocumentVersion.document_id == doc_id,
        ).first()

        if not version:
            raise ValueError("Document version not found")

        doc = db.query(Document).filter(Document.id == doc_id).first()
        if not doc:
            raise ValueError("Document not found")

        db.query(DocumentVersion).filter(
            DocumentVersion.document_id == doc_id,
            DocumentVersion.id != document_version_id,
        ).update({DocumentVersion.is_current: False}, synchronize_session=False)

        version.is_current = True
        version.status = DocumentStatusType.DONE.value

        doc.current_version_id = version.id
        doc.original_asset_id = version.asset_id
        doc.filename = version.filename
        doc.file_path = version.file_path
        doc.n_pages = version.n_pages
        doc.n_chunks = version.n_chunks
        doc.status = DocumentStatusType.DONE.value

        db.commit()


def _enqueue_document_intelligence(doc_id: int, owner_id: int | None) -> None:
    """Create a Document Intelligence job for a freshly-processed document and
    enqueue it on the shared (Redis) Celery app.  Imported lazily to avoid a
    circular import at module load.  Best-effort: a DI failure must never fail
    the MinerU task."""
    try:
        from document_intelligence.models import DIJobStatus, DocumentIntelligenceJob
        from document_intelligence.tasks import process_document_task

        with db_session() as db:
            job = DocumentIntelligenceJob(
                document_id=doc_id,
                triggered_by_user_id=owner_id,
                status=DIJobStatus.QUEUED,
                methods_requested=["llm_vlm"],
            )
            db.add(job)
            db.commit()
            db.refresh(job)
            job_id = job.id

        process_document_task.delay(job_id)
        print(f"[mineru] Chained Document Intelligence job {job_id} for doc {doc_id}", flush=True)
    except Exception as exc:  # pragma: no cover - defensive
        print(f"[mineru] Failed to enqueue Document Intelligence for doc {doc_id}: {exc!r}", flush=True)


@celery_app.task(name="mineru.process_pdf")
def mineru_process_pdf(
    doc_id: int,
    pdf_path: str | None = None,
    asset_id: int | None = None,
    owner_id: int | None = None,
    document_version_id: int | None = None,
    run_document_intelligence: bool = False,
):
    _set_document_version_status(doc_id, document_version_id, DocumentStatusType.INPROGGRESS)

    try:
        storage_path = str(doc_id)

        if document_version_id is not None:
            with db_session() as db:
                version = db.query(DocumentVersion).filter(
                    DocumentVersion.id == document_version_id,
                    DocumentVersion.document_id == doc_id,
                ).first()
                if not version:
                    raise ValueError("Document version not found")

                storage_path = version.file_path or f"{doc_id}/versions/{version.version_number}"
                version.file_path = storage_path
                db.commit()

        if asset_id is not None:
            with db_session() as db:
                doc = db.query(Document).filter(Document.id == doc_id).first()
                if not doc:
                    raise ValueError("Document not found")

                user_id = owner_id or doc.owner_id
                user = db.query(User).filter(User.id == user_id).first()
                if not user:
                    raise ValueError("Document owner not found")

                doc_dir = Path(settings.files_dir) / storage_path
                original_pdf = doc_dir / "original.pdf"

                manager = StorageManager(db)
                manager.download_asset_to_path(
                    asset_id=asset_id,
                    user=user,
                    target_path=original_pdf,
                )

                with original_pdf.open("rb") as f:
                    header = f.read(4)

                if header != b"%PDF":
                    raise ValueError("Uploaded file is not a valid PDF")

                pdf_path = os.path.join(storage_path, "original.pdf")

        if not pdf_path:
            raise ValueError("Either pdf_path or asset_id is required")

        run_mineru_on_file(
            pdf_path=pdf_path,
            doc_id=doc_id,
            document_version_id=document_version_id,
            storage_path=storage_path,
            asset_id=asset_id,
        )
        _activate_document_version(doc_id, document_version_id)

        # Opt-in hand-off: MinerU output (text + _middle.json) is now persisted,
        # so Document Intelligence can reuse it instead of re-processing the PDF.
        if run_document_intelligence:
            _enqueue_document_intelligence(doc_id, owner_id)

    except Exception:
        _set_document_version_status(doc_id, document_version_id, DocumentStatusType.FAIELED)
        raise


def _backfill_one_document(doc_id: int, rerun_missing: bool) -> str:
    """Backfill S3 artifacts + chunk↔image links for a single document.

    If the document's local MinerU `_middle.json` still exists, re-run the
    (MinerU-free) middle-json ingestion: this rewrites image refs, uploads the
    derived bundle to S3 and recreates `image_chunks` rows — idempotent on
    re-run. If no local artifacts exist and ``rerun_missing`` is set, re-run
    MinerU from the S3 original. Otherwise the document is skipped.
    """
    from components.folders import find_processed_bundle
    from core.simple_ingestion import ingest_processed_middle_json, run_mineru_on_file

    with db_session() as db:
        doc = db.query(Document).filter(Document.id == doc_id).first()
        if not doc:
            return "missing"
        storage_path = doc.file_path or str(doc_id)
        asset_id = doc.original_asset_id
        version_id = doc.current_version_id
        owner_id = doc.owner_id

    doc_dir = Path(settings.files_dir) / storage_path
    bundle = find_processed_bundle(doc_dir)

    if bundle.middle_json is not None and bundle.middle_json.exists():
        with db_session() as db:
            ingest_processed_middle_json(
                middle_json_path=str(bundle.middle_json),
                doc_id=doc_id,
                db=db,
                document_version_id=version_id,
                storage_path=storage_path,
                asset_id=asset_id,
            )
            db.commit()
        return "migrated"

    if rerun_missing and asset_id is not None:
        with db_session() as db:
            user = db.query(User).filter(User.id == owner_id).first()
            if not user:
                return "skipped-no-owner"
            original_pdf = doc_dir / "original.pdf"
            manager = StorageManager(db)
            manager.download_asset_to_path(
                asset_id=asset_id,
                user=user,
                target_path=original_pdf,
            )
        run_mineru_on_file(
            pdf_path=os.path.join(storage_path, "original.pdf"),
            doc_id=doc_id,
            document_version_id=version_id,
            storage_path=storage_path,
            asset_id=asset_id,
        )
        return "reprocessed"

    return "skipped-no-local"


@celery_app.task(name="mineru.backfill_s3")
def backfill_mineru_to_s3(doc_id="all", rerun_missing: bool = False):
    """Backfill MinerU S3 artifacts and chunk↔image links for existing docs.

    ``doc_id`` may be a specific document id or the string ``"all"``. Returns a
    map of ``{doc_id: result}``. Idempotent: safe to re-run.
    """
    with db_session() as db:
        if doc_id == "all" or doc_id is None:
            ids = [row[0] for row in db.query(Document.id).order_by(Document.id.asc()).all()]
        else:
            ids = [int(doc_id)]

    results: dict[int, str] = {}
    for did in ids:
        try:
            results[did] = _backfill_one_document(did, rerun_missing)
        except Exception as exc:  # never abort the whole batch on one doc
            results[did] = f"error: {exc!r}"
            print(f"[mineru-backfill] doc {did} failed: {exc!r}", flush=True)

    print(f"[mineru-backfill] done: {results}", flush=True)
    return results


@celery_app.task(name="stt.transcribe_audio", bind=True, max_retries=2)
def transcribe_audio_task(self, asset_id: int, user_id: int, language: str | None = None):
    """Download the audio asset and call the STT service synchronously.

    Updates TaskResult row (keyed by celery_task_id == self.request.id)
    with success payload or failure message.
    """
    import httpx
    import tempfile
    from pathlib import Path

    celery_task_id = self.request.id

    def _get_task(db):
        from Models.task_result import TaskResult
        return (
            db.query(TaskResult)
            .filter(TaskResult.celery_task_id == celery_task_id)
            .first()
        )

    # Mark in_progress
    with db_session() as db:
        task = _get_task(db)
        if task:
            task.status = "in_progress"
            db.commit()

    try:
        with db_session() as db:
            user = db.query(User).filter(User.id == user_id).first()
            if not user:
                raise ValueError(f"User {user_id} not found")

            manager = StorageManager(db)

            from Models.file_asset import FileAsset
            asset = db.query(FileAsset).filter(FileAsset.id == asset_id).first()
            if not asset:
                raise ValueError(f"Asset {asset_id} not found")

            suffix = Path(asset.original_filename or "").suffix.lower() or ".audio"

            with tempfile.TemporaryDirectory() as tmpdir:
                target_path = Path(tmpdir) / f"asset_{asset_id}{suffix}"
                manager.download_asset_to_path(
                    asset_id=asset_id,
                    user=user,
                    target_path=target_path,
                )
                content = target_path.read_bytes()

            filename = asset.original_filename or f"asset_{asset_id}{suffix}"
            content_type = asset.content_type or "application/octet-stream"

        # Call STT service (synchronous HTTP)
        params = {}
        if language:
            params["language"] = language

        with httpx.Client(timeout=300) as client:
            response = client.post(
                f"{settings.STT_URL}/transcribe",
                files={"file": (filename, content, content_type)},
                params=params,
            )
            response.raise_for_status()
            result = response.json()

        # Persist success
        with db_session() as db:
            task = _get_task(db)
            if task:
                task.status = "success"
                task.result_json = result
                db.commit()

    except Exception as exc:
        with db_session() as db:
            task = _get_task(db)
            if task:
                task.status = "failure"
                task.error_message = str(exc)
                db.commit()
        raise


@celery_app.task(name="chat.generate_title")
def chat_generate_title(chat_id: int, first_user_question: str):
    try:
        title = asyncio.run(generate_chat_title_from_question(first_user_question))
    except RuntimeError:
        loop = asyncio.new_event_loop()
        try:
            title = loop.run_until_complete(generate_chat_title_from_question(first_user_question))
        finally:
            loop.close()

    if not (title or "").strip():
        return

    with db_session() as db:
        chat = db.query(Chat).filter(Chat.id == chat_id).first()
        if not chat:
            return

        if chat.name != "New Chat":
            return

        chat.name = title.strip()
        db.commit()
