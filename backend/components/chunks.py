from pathlib import Path

from settings import get_settings
from db.session import db_session
from db.models import Chunk
from components.folders import get_full_processed_file_path

def get_chunk_pos(chunk: Chunk, md_file_path: Path):
    """
    Return (start_pos, end_pos) of this chunk inside the markdown file.
    Assumes the chunk text appears in the file *exactly once*.
    """
    # read the whole markdown file
    md_text = Path(md_file_path).read_text(encoding="utf-8")

    # try to figure out which attribute of the chunk actually stores the text
    chunk_text = chunk.content

    start = md_text.find(chunk_text)
    if start == -1:
        # not found — you can log this if you want
        return None, None

    end = start + len(chunk_text)
    return start, end


if __name__ == "__main__":
    for doc_id in range(93, 195):
        with db_session() as db:
            # process only chunks missing page_num; drop .limit(400) or paginate
            chunks = (db.query(Chunk)
                        .filter(Chunk.doc_id == doc_id)
                        # .filter((Chunk.page_num == None) | (Chunk.page_num == -1))
                        .order_by(Chunk.id)
                        .all())

            for ch in chunks:
                settings = get_settings()
                doc_dir = Path(settings.files_dir) / str(ch.doc_id)
                md_file_path = get_full_processed_file_path(doc_dir, ".md")
                """
                the md file path: md_file_path
                chunks: chunks
                """
                start,end = get_chunk_pos(ch,md_file_path)
                if start == None or end == None:
                    input("problem")
                else:
                    ch.start_pos = start
                    ch.end_pos = end
                    print(f"pos updated {doc_id} chunk {ch.id} start pos {start} end pos {end}")
            
            db.commit()
