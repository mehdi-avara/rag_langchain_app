from core.celery.celery_app import celery_app
from core.simple_ingestion import background_task_mineru
from core.chunking import ChunkingMode

@celery_app.task(name="mineru.process_pdf")
def mineru_process_pdf(pdf_bytes: bytes, filename: str, doc_id: int, chunking: str):
    """
    Celery worker task. Runs MinerU ingestion in background.
    """
    mode = ChunkingMode(chunking)

    background_task_mineru(
        pdf_bytes=pdf_bytes,
        filename=filename,
        doc_id=doc_id,
        chunking_mode=mode,
    )

    return True