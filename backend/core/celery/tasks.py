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


@celery_app.task(name="mineru.process_pdf")
def mineru_process_pdf(
    doc_id: int,
    pdf_path: str | None = None,
    asset_id: int | None = None,
    owner_id: int | None = None,
    document_version_id: int | None = None,
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
        )
        _activate_document_version(doc_id, document_version_id)

    except Exception:
        _set_document_version_status(doc_id, document_version_id, DocumentStatusType.FAIELED)
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
