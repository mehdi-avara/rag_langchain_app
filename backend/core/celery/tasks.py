from core.celery.celery_app import celery_app
from core.simple_ingestion import run_mineru_on_file


@celery_app.task(name="mineru.process_pdf")
def mineru_process_pdf(pdf_path: str, filename: str, doc_id: int, chunking: str):
    run_mineru_on_file(pdf_path,filename,doc_id,chunking)