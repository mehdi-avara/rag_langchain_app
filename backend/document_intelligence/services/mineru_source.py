"""
Reuse existing MinerU output for Document Intelligence.

This module does NOT process PDFs.  It reads the per-page text that the existing
`mineru.process_pdf` pipeline already produced (the `_middle.json` written under
the document directory) so Document Intelligence never re-extracts text.

Fallback order handled by callers:
  1. MinerU `_middle.json`            (this module)
  2. existing `chunks` table rows     (already embedded text in the DB)
  3. OCR for blank pages only         (last resort, in pdf_artifacts)
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Dict, List, Optional

from sqlalchemy.orm import Session

from Models import Chunk, Document
from settings import get_settings

logger = logging.getLogger(__name__)
settings = get_settings()


def _doc_dir(document: Document) -> Path:
    """Directory that holds original.pdf and the MinerU output for a document."""
    return Path(settings.files_dir) / (document.file_path or str(document.id))


def find_middle_json(document: Document) -> Optional[Path]:
    """Locate the MinerU `_middle.json` for a document, if it exists."""
    doc_dir = _doc_dir(document)
    if not doc_dir.exists():
        return None
    for candidate in doc_dir.rglob("*_middle.json"):
        return candidate
    return None


def _collect_block_text(block: dict) -> str:
    """Recursively pull text spans out of one MinerU para/structure block."""
    parts: List[str] = []

    # Nested layout blocks (e.g. tables/lists wrap their content in `blocks`).
    for child in block.get("blocks", []) or []:
        nested = _collect_block_text(child)
        if nested:
            parts.append(nested)

    for line in block.get("lines", []) or []:
        for span in line.get("spans", []) or []:
            content = span.get("content")
            if content:
                parts.append(str(content))

    return " ".join(p for p in parts if p).strip()


def page_text_from_middle_json(middle_json_path: Path) -> Dict[int, str]:
    """
    Return a {page_num(1-based): text} map from a MinerU `_middle.json`.

    MinerU `page_idx` is 0-based; we expose 1-based page numbers to match the
    DocumentPageArtifact convention used throughout Document Intelligence.
    """
    try:
        with open(middle_json_path, "r", encoding="utf-8") as fh:
            data = json.load(fh)
    except Exception as exc:
        logger.warning("Could not read MinerU middle json %s: %s", middle_json_path, exc)
        return {}

    pdf_info = data.get("pdf_info", data)
    if not isinstance(pdf_info, list):
        logger.warning("Unexpected MinerU middle json shape at %s", middle_json_path)
        return {}

    page_text: Dict[int, str] = {}
    for page in pdf_info:
        if not isinstance(page, dict):
            continue
        page_idx = int(page.get("page_idx", -1))
        if page_idx < 0:
            continue

        block_texts: List[str] = []
        for block in page.get("para_blocks", []) or []:
            txt = _collect_block_text(block)
            if txt:
                block_texts.append(txt)

        page_text[page_idx + 1] = "\n".join(block_texts).strip()

    return page_text


def page_text_from_chunks(db: Session, document_id: int) -> Dict[int, str]:
    """
    Fallback source: reconstruct per-page text by concatenating the existing
    `chunks` rows (already produced by the ingestion pipeline) grouped by page.
    """
    rows = (
        db.query(Chunk.page_num, Chunk.content)
        .filter(Chunk.doc_id == document_id, Chunk.chunk_type == "text")
        .order_by(Chunk.page_num, Chunk.id)
        .all()
    )
    page_text: Dict[int, str] = {}
    for page_num, content in rows:
        if not content:
            continue
        page_text.setdefault(int(page_num), [])
        page_text[int(page_num)].append(content)  # type: ignore[union-attr]

    return {pn: "\n".join(parts).strip() for pn, parts in page_text.items()}


def load_reused_page_text(db: Session, document: Document) -> Dict[int, str]:
    """
    Best available per-page text from existing pipeline output, without touching
    the PDF.  Tries MinerU `_middle.json` first, then the `chunks` table.
    Returns {} if neither source has anything (callers may OCR blank pages).
    """
    middle = find_middle_json(document)
    if middle is not None:
        text = page_text_from_middle_json(middle)
        if any(t for t in text.values()):
            logger.info(
                "Reusing MinerU text for doc %d from %s (%d pages).",
                document.id, middle.name, len(text),
            )
            return text

    text = page_text_from_chunks(db, document.id)
    if text:
        logger.info(
            "Reusing existing chunk text for doc %d (%d pages).",
            document.id, len(text),
        )
    return text
