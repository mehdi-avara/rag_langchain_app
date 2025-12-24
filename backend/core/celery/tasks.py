# core/celery/tasks.py
from core.celery.celery_app import celery_app
from core.simple_ingestion import run_mineru_on_file
from db.session import db_session
from Models import Document,DocumentStatusType


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
        
