from pathlib import Path
# from mineru.utils.enum_class import MakeMode
import json

from settings import get_settings
from db.session import db_session
from Models import Chunk, Document
from components.folders import get_full_processed_file_path
from components.stand_alone_functions.page_find_logic import union_make


def find_chunk_pos_in_text(chunk_text: str, md_text: str):
    start = md_text.find(chunk_text)
    if start == -1:
        return None, None
    end = start + len(chunk_text)
    return start, end



def find_page_for_pos(pos: int, pages_list: list):
    """
    Given a character position and a list of page boundaries, return the page index.
    Each item in pages_list: {"page_idx": int, "start": int, "end": int}
    """
    for p in pages_list:
        if p["start"] <= pos < p["end"]:
            return p["page_idx"]
    return None



def numbering_pages():
    settings = get_settings()
    # 1) get only the IDs
    with db_session() as db:
        doc_ids = [d.id for d in db.query(Document).order_by(Document.id).all()]

    # 2) now loop over ids freely
    for doc_id in doc_ids:
        
        print(f"Processing doc: {doc_id}")

        doc_dir = Path(settings.files_dir) / str(doc_id)
        # Load JSON
        file_path = Path(get_full_processed_file_path(doc_dir, "_middle.json"))
        with file_path.open("r", encoding="utf-8") as f:
            data = json.load(f)

        # Accept either {"pdf_info": [...]} or a raw list
        pdf_info = data.get("pdf_info", data)
        if not isinstance(pdf_info, list):
            raise SystemExit("Input JSON must contain a list under key 'pdf_info' (or be a list itself).")

        # Convert to Markdown using your function
        # md_text,pages_list = union_make(pdf_info_dict=pdf_info, make_mode=MakeMode.MM_MD,img_buket_path="images")
        md_text,pages_list = union_make(pdf_info_dict=pdf_info, make_mode="wrong",img_buket_path="images")
        with db_session() as db:
            chunks = (db.query(Chunk)
                        .filter(Chunk.doc_id == doc_id)
                        .order_by(Chunk.id)
                        .all())

            if not chunks:
                continue

            md_file_path = get_full_processed_file_path(doc_dir, ".md")
            md_text = Path(md_file_path).read_text(encoding="utf-8")

            for ch in chunks:
                chunk_text = ch.content  # make sure this is the exact text
                start, end = find_chunk_pos_in_text(chunk_text, md_text)

                if start is None:
                    print(f"[WARN] chunk {ch.id} of doc {doc_id} not found in md")
                    # continue  # don’t block the script
                else:
                    ch.start_pos = start
                    ch.end_pos = end
                    db.flush()  # force SQLAlchemy to issue UPDATE
                                # find page number based on start position
                page_idx = find_page_for_pos(start, pages_list)
                if page_idx is not None:
                    ch.page_num = page_idx
                    db.flush()  # force SQLAlchemy to issue UPDATE
                else:
                    print(f"[WARN] Chunk {ch.id} position {start} not inside any page range.")

            db.commit()