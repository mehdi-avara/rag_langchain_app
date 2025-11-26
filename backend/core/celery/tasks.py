from core.celery.celery_app import celery_app
from core.simple_ingestion import background_mineru_task_runner


@celery_app.task(name="mineru.process_pdf")
def mineru_process_pdf(pdf_path: str, filename: str, doc_id: int, chunking: str):
    background_mineru_task_runner(pdf_path,filename,doc_id,chunking)