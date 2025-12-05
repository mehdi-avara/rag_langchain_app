import re
from pathlib import Path

from settings import get_settings
from db.session import db_session
from Models import Chunk
from components import generate_embeddings_for_chunks


def deleting_image_path_from_embedding():
    """
    1) Find chunks whose content contains local image markdown:
         ![](images/xxxx.jpg)
    2) Regenerate embeddings using the same prompt format as ingestion,
       but with those image tags removed from the text.
    3) Rewrite the markdown image URLs in the chunk content to absolute URLs:
         https://<BASE>/<doc_id>/images/<filename>
       where <BASE> is read from settings.
    """

    settings = get_settings()

    # Adjust this attribute name to whatever you actually use
    # e.g. settings.public_files_base_url, settings.api_base_url, etc.
    base_url = settings.base_url

    # Regex for markdown images that start with "images/"
    # Example matched: ![](images/aabbcc.jpg)
    # groups:
    #   1 -> alt text (may be empty)
    #   2 -> "images/filename.ext"
    #   3 -> "filename.ext"
    md_image_pattern = re.compile(
        r'!\[([^\]]*)\]\((images/([^)\s]+))\)'
    )

    with db_session() as db:
        # Only chunks that have local images paths
        chunks = (
            db.query(Chunk)
              .filter(Chunk.content.ilike("%](images/%"))
            #   .limit(3)
              .all()
        )


        if not chunks:
            print("No chunks with local image paths found.")
            return

        clean_prompts = []
        chunks_to_embed = []

        for ch in chunks:
            print(f"id {ch.id}")
            print(f"id {ch.content}")
            
            if not ch.content:
                continue

            # 1) Text for embedding: remove the entire image tag
            #    (so the URL does not pollute the embedding)
            text_without_images = md_image_pattern.sub("", ch.content)

            # If absolutely nothing remains, you can decide to:
            #   - set embedding to None, or
            #   - keep the old embedding and skip this chunk.
            if not text_without_images.strip():
                # Here we'll still update embedding with an empty string
                # (you could also choose to skip)
                prompt = "search_document: "
            else:
                prompt = f"search_document: {text_without_images}"

            clean_prompts.append(prompt)
            chunks_to_embed.append(ch)

        # 2) Regenerate embeddings in bulk
        if clean_prompts:
            new_embeddings = generate_embeddings_for_chunks(clean_prompts)
        else:
            new_embeddings = []

        # 3) Assign new embeddings and rewrite image URLs in markdown
        for ch, emb in zip(chunks_to_embed, new_embeddings):
            ch.embedding = emb

            def _rewrite_match(m: re.Match) -> str:
                alt_text = m.group(1) or ""
                filename = m.group(3)  # "a0223b5f99d7....jpg"
                # Build the public URL:
                #   https://porsaapi.../{doc_id}/images/<filename>
                public_url = f"{base_url}/{ch.doc_id}/images/{filename}"
                return f"![{alt_text}]({public_url})"

            ch.content = md_image_pattern.sub(_rewrite_match, ch.content)

        for i in chunks_to_embed:
            print(i.content)
        db.commit()
        print(f"Updated {len(chunks_to_embed)} chunks (embeddings + image URLs).")
