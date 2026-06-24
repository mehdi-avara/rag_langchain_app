"""
PDF artifact extraction service.

Produces one DocumentPageArtifact row per page for a given Document.
Results are cached: re-running is a no-op unless force=True.

Text is REUSED from the existing MinerU pipeline output (`_middle.json`, or the
`chunks` table) — this service never re-extracts PDF text.  The only PDF op it
performs is rendering full-page images, which MinerU does not produce and the
VLM teacher needs.  OCR is used solely as a last resort for blank pages.

Dependencies already in the project's requirements:
  pdf2image, Pillow, pytesseract (optional / graceful fallback)
"""

from __future__ import annotations

import hashlib
import logging
from pathlib import Path
from typing import Dict, List, Optional

from PIL import Image
from sqlalchemy.orm import Session

from Models import Document
from document_intelligence.models import DocumentPageArtifact
from document_intelligence.services.mineru_source import load_reused_page_text
from settings import get_settings

logger = logging.getLogger(__name__)
settings = get_settings()

# ---------------------------------------------------------------------------
# Path helpers
# ---------------------------------------------------------------------------

def _doc_dir(document: Document) -> Path:
    """Return the directory that holds the original PDF and MinerU outputs."""
    files_dir = Path(settings.files_dir)
    return files_dir / document.file_path


def _original_pdf_path(document: Document) -> Path:
    return _doc_dir(document) / "original.pdf"


def _artifacts_dir(document: Document) -> Path:
    path = _doc_dir(document) / "di_artifacts"
    path.mkdir(parents=True, exist_ok=True)
    return path


# ---------------------------------------------------------------------------
# Text extraction helpers
# ---------------------------------------------------------------------------

def _try_ocr_page(img: Image.Image) -> tuple[Optional[str], Optional[float]]:
    """Run pytesseract on a PIL image. Returns (text, quality_score)."""
    try:
        import pytesseract
        data = pytesseract.image_to_data(img, output_type=pytesseract.Output.DICT, lang="eng+fas")
        texts = [w for w in data["text"] if w.strip()]
        confs = [c for c in data["conf"] if c >= 0]
        quality = (sum(confs) / len(confs)) / 100.0 if confs else 0.0
        return " ".join(texts), quality
    except Exception as exc:
        logger.debug("OCR skipped: %s", exc)
        return None, None


# ---------------------------------------------------------------------------
# Image rendering helpers
# ---------------------------------------------------------------------------

def _render_pages(pdf_path: Path, dpi: int = 150) -> List[Image.Image]:
    """Render all PDF pages to PIL Images using pdf2image."""
    try:
        from pdf2image import convert_from_path
        return convert_from_path(str(pdf_path), dpi=dpi)
    except Exception as exc:
        logger.error("pdf2image failed: %s", exc)
        return []


def _phash_hex(img: Image.Image, hash_size: int = 16) -> str:
    """Compute a perceptual hash (average-hash) of a PIL image."""
    small = img.convert("L").resize((hash_size, hash_size), Image.LANCZOS)
    pixels = list(small.getdata())
    avg = sum(pixels) / len(pixels)
    bits = "".join("1" if p >= avg else "0" for p in pixels)
    hex_val = hex(int(bits, 2))[2:].zfill(hash_size * hash_size // 4)
    return hex_val


def _text_hash(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8", errors="replace")).hexdigest()[:64]


def _text_density(text: str, width: int, height: int) -> Optional[float]:
    area = width * height
    if area == 0:
        return None
    return len(text) / area


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------

def process_page_artifacts(
    db: Session,
    document: Document,
    force: bool = False,
    dpi: int = 150,
) -> List[DocumentPageArtifact]:
    """
    Build DocumentPageArtifact rows for every page of *document*.

    Parameters
    ----------
    db       : SQLAlchemy session (caller is responsible for commit/rollback).
    document : The parent Document ORM object.
    force    : If True, delete and re-create existing artifacts.
    dpi      : Render resolution for page images.

    Returns
    -------
    List of DocumentPageArtifact objects (not yet committed).
    """
    if force:
        db.query(DocumentPageArtifact).filter(
            DocumentPageArtifact.document_id == document.id
        ).delete(synchronize_session=False)
        db.flush()
    else:
        existing = (
            db.query(DocumentPageArtifact)
            .filter(DocumentPageArtifact.document_id == document.id)
            .count()
        )
        if existing > 0:
            logger.info(
                "Artifacts already exist for doc %d (%d pages) – skipping.",
                document.id,
                existing,
            )
            return (
                db.query(DocumentPageArtifact)
                .filter(DocumentPageArtifact.document_id == document.id)
                .order_by(DocumentPageArtifact.page_num)
                .all()
            )

    pdf_path = _original_pdf_path(document)
    if not pdf_path.exists():
        raise FileNotFoundError(f"Original PDF not found: {pdf_path}")

    art_dir = _artifacts_dir(document)

    # Reuse text already produced by the MinerU pipeline — never re-extract.
    logger.info("Loading reused MinerU/chunk text for doc %d …", document.id)
    reused_text: Dict[int, str] = load_reused_page_text(db, document)

    logger.info("Rendering page images for doc %d (dpi=%d) …", document.id, dpi)
    page_images = _render_pages(pdf_path, dpi=dpi)

    max_reused_page = max(reused_text.keys(), default=0)
    n_pages = max(max_reused_page, len(page_images), document.n_pages, 1)

    artifacts: List[DocumentPageArtifact] = []

    for page_idx in range(n_pages):
        page_num = page_idx + 1   # 1-based

        # -- text (reused from MinerU / chunks; never re-extracted) --
        text: Optional[str] = reused_text.get(page_num) or None

        # -- image --
        img: Optional[Image.Image] = None
        image_path: Optional[str] = None
        thumbnail_path: Optional[str] = None
        img_hash: Optional[str] = None
        width: Optional[int] = None
        height: Optional[int] = None
        img_density: Optional[float] = None

        if page_idx < len(page_images):
            img = page_images[page_idx]
            width, height = img.size

            # Save full-res PNG
            img_fname = f"page_{page_num:04d}.png"
            img_full_path = art_dir / img_fname
            img.save(str(img_full_path), format="PNG", optimize=True)
            image_path = str(img_full_path)

            # Save thumbnail
            thumb = img.copy()
            thumb.thumbnail((400, 400))
            thumb_fname = f"page_{page_num:04d}_thumb.png"
            thumb_full_path = art_dir / thumb_fname
            thumb.save(str(thumb_full_path), format="PNG", optimize=True)
            thumbnail_path = str(thumb_full_path)

            img_hash = _phash_hex(img)

            # Simple image density: non-white pixel ratio as proxy
            grey = img.convert("L")
            px = list(grey.getdata())
            non_white = sum(1 for p in px if p < 250)
            img_density = non_white / len(px) if px else None

        # -- OCR fallback when text is absent --
        ocr_text: Optional[str] = None
        ocr_quality: Optional[float] = None
        if not text and img is not None:
            ocr_text, ocr_quality = _try_ocr_page(img)

        # -- text density --
        effective_text = text or ocr_text or ""
        td = _text_density(effective_text, width or 1, height or 1)

        # -- layout features (simple JSON dict, expandable) --
        layout_features: dict = {
            "has_text": bool(text),
            "has_ocr_fallback": bool(ocr_text and not text),
            "image_count": 0,  # placeholder; can be filled by layout parsers
        }

        artifact = DocumentPageArtifact(
            document_id=document.id,
            page_num=page_num,
            text=text,
            ocr_text=ocr_text,
            text_hash=_text_hash(effective_text) if effective_text else None,
            image_path=image_path,
            thumbnail_path=thumbnail_path,
            image_hash=img_hash,
            width=width,
            height=height,
            ocr_quality=ocr_quality,
            text_density=td,
            image_density=img_density,
            layout_features=layout_features,
        )
        db.add(artifact)
        artifacts.append(artifact)

    logger.info(
        "Created %d page artifacts for doc %d.", len(artifacts), document.id
    )
    return artifacts
