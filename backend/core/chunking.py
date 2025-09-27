from enum import Enum
from typing import List
import re
from langchain.text_splitter import RecursiveCharacterTextSplitter
from typing import List
from langchain.text_splitter import RecursiveCharacterTextSplitter
import tiktoken



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

def chunk_by_tokens(text: str, max_tokens: int = 800, overlap: int = 100, model: str = "gpt-4o-mini") -> List[str]:
    """Split text into chunks of ~max_tokens using actual token counts."""

    enc = tiktoken.encoding_for_model(model)

    def token_len(s: str) -> int:
        return len(enc.encode(s))

    splitter = RecursiveCharacterTextSplitter(
        chunk_size=max_tokens,
        chunk_overlap=overlap,
        length_function=token_len,
    )
    return splitter.split_text(text)

def chunk_text(text: str, mode: ChunkingMode) -> List[str]:
    """Main chunking function that routes to appropriate strategy."""
    if mode == ChunkingMode.sentence_3:
        return chunk_by_sentences(text, group_size=4)
    elif mode == ChunkingMode.paragraph:
        return chunk_by_paragraph(text)
    elif mode == ChunkingMode.token_fixed:
        return chunk_by_tokens(text, max_tokens=800)
    else:
        raise ValueError(f"Unknown chunking mode: {mode}") 