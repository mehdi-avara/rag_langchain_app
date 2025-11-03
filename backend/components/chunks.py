from pathlib import Path

from settings import get_settings
from db.session import db_session
from db.models import Chunk
from components.folders import get_full_processed_file_path


def find_chunk_pos_in_text(chunk_text: str, md_text: str):
    start = md_text.find(chunk_text)
    if start == -1:
        return None, None
    end = start + len(chunk_text)
    return start, end


if __name__ == "__main__":
    settings = get_settings()

    for doc_id in range(88, 195):
        with db_session() as db:
            chunks = (db.query(Chunk)
                        .filter(Chunk.doc_id == doc_id)
                        .order_by(Chunk.id)
                        .all())

            if not chunks:
                continue

            doc_dir = Path(settings.files_dir) / str(doc_id)
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
                    print(f"[OK] doc {doc_id} chunk {ch.id} -> {start}..{end}")

            db.commit()