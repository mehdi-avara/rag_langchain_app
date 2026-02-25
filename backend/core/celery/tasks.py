# core/celery/tasks.py
import asyncio

from core.celery.celery_app import celery_app
from core.chat_title import generate_chat_title_from_question
from core.simple_ingestion import run_mineru_on_file
from db.session import db_session
from Models import Chat, Document,DocumentStatusType


@celery_app.task(name="mineru.process_pdf")
def mineru_process_pdf(pdf_path: str, doc_id: int):
    
    with db_session() as db:
        # Update document record
        db.query(Document).filter(Document.id == doc_id).update({
            Document.status: DocumentStatusType.INPROGGRESS.value
        })
        db.commit()
    try:
        run_mineru_on_file(pdf_path, doc_id)
        with db_session() as db:
            db.query(Document).filter(Document.id == doc_id).update({
                Document.status: DocumentStatusType.DONE.value
            })
            db.commit()
    except Exception as e:
        with db_session() as db:
            db.query(Document).filter(Document.id == doc_id).update({
                Document.status: DocumentStatusType.FAIELED.value
            })
            db.commit()
        raise e
        


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

