from pathlib import Path

from settings import get_settings
from db.session import db_session
from db.models import Document, Chunk

from components.folders import get_full_processed_file_path
settings = get_settings()





def get_chunk_page_using_json(chunk: Chunk) -> int:
    """Get the file path of the chunk page based on the document directory."""
    with db_session() as db:
        doc = db.query(Document).filter(Document.id == chunk.doc_id).all()
        if not doc:
            return None
    settings = get_settings()
    doc_dir = Path(settings.files_dir) / str(doc[0].id)
    json_path = get_full_processed_file_path(doc_dir, "_content_list.json")
    if json_path:
        import json
        with open(json_path, 'r', encoding='utf-8') as f:
            content_list = json.load(f)
    chunk_content = chunk.content
        
    
    
    return 0
        