from enum import Enum
from typing import List, Dict
import re
from langchain.text_splitter import RecursiveCharacterTextSplitter
import tiktoken
from components.stand_alone_functions.page_find_logic.mineru_main_file_creator import (
    build_dual_mode_chunks_from_pdf_info,
)



class ChunkingMode(str, Enum):
    sentence_3 = "sentence-3"
    paragraph = "paragraph"
    token_fixed = "token-fixed"

def chunk_by_sentences(text: str, group_size: int = 3) -> List[str]:
    sentences = re.split(r'(?<=[.!?])\s+', text.strip())
    chunks = [' '.join(sentences[i:i + group_size]) for i in range(0, len(sentences), group_size)]
    return chunks

# def chunk_by_sentences(text: str, group_size: int = 3) -> List[str]:
#     """Split text into groups of sentences."""
#     try:
#         nltk.data.find('tokenizers/punkt')
#     except LookupError:
#         nltk.download('punkt')
    
#     sentences = nltk.sent_tokenize(text)
#     chunks = []
#     for i in range(0, len(sentences), group_size):
#         chunk = ' '.join(sentences[i:i + group_size])
#         chunks.append(chunk)
#     return chunks

def chunk_by_paragraph(text: str) -> List[str]:
    """Split text into paragraphs."""
    paragraphs = [p.strip() for p in text.split('\n\n') if p.strip()]
    return paragraphs

def token_len(s: str) -> int:
    model = "gpt-4o-mini"
    enc = tiktoken.encoding_for_model(model)
    return len(enc.encode(s))


def chunk_by_tokens(text: str, max_tokens: int = 800, overlap: int = 100, ) -> List[str]:
    """Split text into chunks of ~max_tokens using actual token counts."""
    splitter = RecursiveCharacterTextSplitter(
        chunk_size=max_tokens,
        chunk_overlap=overlap,
        length_function=token_len,
    )
    return splitter.split_text(text)

def chunk_text(
    pdf_info: list,
    doc_id: int,
    base_url: str,
    max_tokens: int = 800,
    overlap_tokens: int = 150,
    min_chunk_tokens: int = 20,
    mode: ChunkingMode = ChunkingMode.token_fixed
) -> List[Dict]:
    """
    Build chunks from MinerU middle json (`pdf_info`) and return dicts with:
      chunk_text, chunk_embedding_text, start_page, end_page, token_count
    """
    # We keep this API mode-aware for compatibility, but use one robust strategy.
    if mode not in {ChunkingMode.sentence_3, ChunkingMode.paragraph, ChunkingMode.token_fixed}:
        raise ValueError(f"Unknown chunking mode: {mode}")

    chunks, _ = build_dual_mode_chunks_from_pdf_info(
        pdf_info_dict=pdf_info,
        doc_id=doc_id,
        base_url=base_url,
        max_tokens=max_tokens,
        overlap_tokens=overlap_tokens,
        min_chunk_tokens=min_chunk_tokens,
    )
    return chunks
