"""
LLM/VLM teacher pipeline.

Runs five sequential tasks against the configured OpenAI-compatible endpoint:
  1. Page inventory      – per-page type, entities, language.
  2. Boundary detection  – adjacent-pair same/new decision.
  3. Segment construction – boundaries → page ranges.
  4. Segment classification + metadata.
  5. Validation pass.

All LLM calls use JSON-mode (response_format={"type":"json_object"}) because
structured-output schema enforcement may not be available on every local model.
The code validates output with Pydantic before storing it.

Image inputs: pages are encoded as base-64 data URLs when the model supports
vision (settings.openai_model assumed vision-capable by default; set
DI_LLM_VISION_ENABLED=0 in env to disable).
"""

from __future__ import annotations

import base64
import json
import logging
import os
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

from openai import AsyncOpenAI
from pydantic import BaseModel, Field, ValidationError
from sqlalchemy.orm import Session

from Models import Document
from document_intelligence.models import (
    DIMethod,
    DocumentMethodRun,
    DocumentPageArtifact,
    DocumentSegment,
    DocumentSegmentSuggestion,
    DIModelCreationSuggestion,
    DISegmentStatus,
    DISuggestionStatus,
    DISuggestionType,
)
from document_intelligence.schemas import (
    CanonicalMethodOutput,
    CanonicalSegmentPayload,
    CanonicalSuggestionPayload,
    EvidenceItem,
)
from settings import get_settings

logger = logging.getLogger(__name__)
settings = get_settings()

_VISION_ENABLED = os.getenv("DI_LLM_VISION_ENABLED", "1") not in ("0", "false", "False")
_MAX_PAGES_PER_CALL = int(os.getenv("DI_LLM_MAX_PAGES_PER_CALL", "20"))
_MODEL = os.getenv("DI_LLM_MODEL", settings.openai_model)

# ---------------------------------------------------------------------------
# OpenAI client (re-uses project settings)
# ---------------------------------------------------------------------------

def _get_client() -> AsyncOpenAI:
    return AsyncOpenAI(
        api_key=settings.openai_api_key,
        base_url=settings.openai_base_url,
    )


# ---------------------------------------------------------------------------
# Image encoding helpers
# ---------------------------------------------------------------------------

def _encode_image_b64(image_path: str) -> Optional[str]:
    try:
        with open(image_path, "rb") as fh:
            return base64.b64encode(fh.read()).decode("utf-8")
    except Exception as exc:
        logger.warning("Cannot encode image %s: %s", image_path, exc)
        return None


def _image_content_block(image_path: str) -> Optional[Dict]:
    b64 = _encode_image_b64(image_path)
    if not b64:
        return None
    return {
        "type": "image_url",
        "image_url": {"url": f"data:image/png;base64,{b64}", "detail": "low"},
    }


# ---------------------------------------------------------------------------
# Low-level JSON chat call
# ---------------------------------------------------------------------------

async def _chat_json(
    client: AsyncOpenAI,
    system: str,
    user_content: List[Dict],
    max_tokens: int = 4096,
) -> tuple[str, int]:
    """
    Send a chat completion request and return (raw_text, total_tokens).
    Uses JSON mode for more reliable structured output.
    """
    response = await client.chat.completions.create(
        model=_MODEL,
        messages=[
            {"role": "system", "content": system},
            {"role": "user", "content": user_content},
        ],
        response_format={"type": "json_object"},
        max_tokens=max_tokens,
        temperature=0.0,
    )
    content = response.choices[0].message.content or ""
    tokens = response.usage.total_tokens if response.usage else 0
    return content, tokens


# ---------------------------------------------------------------------------
# Pydantic helpers for LLM responses
# ---------------------------------------------------------------------------

class _PageInventoryItem(BaseModel):
    page: int
    page_type: str = "unknown"
    visible_title: Optional[str] = None
    main_entities: List[str] = []
    manufacturer_candidates: List[str] = []
    model_candidates: List[str] = []
    language: str = "en"
    visual_notes: Optional[str] = None
    confidence: float = 0.5


class _PageInventoryResponse(BaseModel):
    pages: List[_PageInventoryItem]


class _BoundaryItem(BaseModel):
    page_i: int
    page_j: int
    relationship: str = "continues"   # continues | new_document | uncertain
    confidence: float = 0.5
    evidence: List[str] = []


class _BoundaryResponse(BaseModel):
    boundaries: List[_BoundaryItem]


class _LLMSuggestion(BaseModel):
    type: str
    proposed_name: Optional[str] = None
    manufacturer: Optional[str] = None
    model: Optional[str] = None
    target_id: Optional[int] = None
    confidence: float = 0.5
    evidence: str = ""


class _LLMSegment(BaseModel):
    start_page: int
    end_page: int
    title: Optional[str] = None
    document_type: str = "unknown"
    summary: Optional[str] = None
    detected_language: str = "en"
    confidence: float = 0.5
    evidence: List[Dict[str, Any]] = []
    suggestions: List[_LLMSuggestion] = []
    unknown_model_candidate: bool = False


class _SegmentClassificationResponse(BaseModel):
    segments: List[_LLMSegment]


# ---------------------------------------------------------------------------
# System prompt
# ---------------------------------------------------------------------------

_SYSTEM_PROMPT = """You are a document intelligence engine.
Your job is to detect and classify logical documents embedded in a single PDF file.
A single PDF may contain multiple concatenated documents (manuals, certificates, datasheets, etc.).

Rules you must follow:
- Return ONLY valid JSON matching the requested schema.  No prose outside JSON.
- Every classification must include page-level evidence.
- Use "unknown" when unsure of document_type or entity names.
- Confidence values must represent probability of being correct (0.0 – 1.0).
- Never create real database objects; only create suggestions.
- Page ranges must be non-overlapping and must cover all pages.
- Supported document types: manual, datasheet, certificate, calibration, invoice, report, unknown.
- Supported suggestion types: tag, managed_model, process_link, category.
"""

# ---------------------------------------------------------------------------
# Task 1: Page inventory
# ---------------------------------------------------------------------------

async def _task_page_inventory(
    client: AsyncOpenAI,
    artifacts: List[DocumentPageArtifact],
) -> tuple[List[_PageInventoryItem], int]:
    """Ask the LLM to describe each page."""

    all_items: List[_PageInventoryItem] = []
    total_tokens = 0

    # Process in batches to avoid context-length limits
    for batch_start in range(0, len(artifacts), _MAX_PAGES_PER_CALL):
        batch = artifacts[batch_start : batch_start + _MAX_PAGES_PER_CALL]

        user_content: List[Dict] = []

        # Build text descriptions for the batch
        pages_text_block = []
        for art in batch:
            txt = (art.text or art.ocr_text or "").strip()[:2000]  # cap per page
            pages_text_block.append(f"--- Page {art.page_num} ---\n{txt}")

        user_content.append(
            {
                "type": "text",
                "text": (
                    "Analyze the following pages from a PDF and classify each page.\n\n"
                    + "\n\n".join(pages_text_block)
                    + "\n\nRespond with JSON matching:\n"
                    "{\n"
                    '  "pages": [\n'
                    "    {\n"
                    '      "page": <int>,\n'
                    '      "page_type": "cover_page|table_of_contents|text_page|certificate|image_page|appendix|unknown",\n'
                    '      "visible_title": "<string or null>",\n'
                    '      "main_entities": ["<string>"],\n'
                    '      "manufacturer_candidates": ["<string>"],\n'
                    '      "model_candidates": ["<string>"],\n'
                    '      "language": "<ISO 639-1>",\n'
                    '      "visual_notes": "<string or null>",\n'
                    '      "confidence": <float 0-1>\n'
                    "    }\n"
                    "  ]\n"
                    "}"
                ),
            }
        )

        # Optionally attach page images
        if _VISION_ENABLED:
            for art in batch:
                if art.thumbnail_path:
                    block = _image_content_block(art.thumbnail_path)
                    if block:
                        user_content.insert(0, block)  # images before text

        raw, tokens = await _chat_json(client, _SYSTEM_PROMPT, user_content, max_tokens=4096)
        total_tokens += tokens

        try:
            parsed = _PageInventoryResponse.model_validate_json(raw)
            all_items.extend(parsed.pages)
        except (ValidationError, json.JSONDecodeError) as exc:
            logger.warning("Page inventory parse error (batch %d): %s", batch_start, exc)

    return all_items, total_tokens


# ---------------------------------------------------------------------------
# Task 2: Boundary detection
# ---------------------------------------------------------------------------

async def _task_boundary_detection(
    client: AsyncOpenAI,
    artifacts: List[DocumentPageArtifact],
    inventory: List[_PageInventoryItem],
) -> tuple[List[_BoundaryItem], int]:
    """Classify each adjacent pair as continues / new_document / uncertain."""

    inv_by_page = {item.page: item for item in inventory}
    all_boundaries: List[_BoundaryItem] = []
    total_tokens = 0

    # Build pairs
    pairs = [
        (artifacts[i], artifacts[i + 1])
        for i in range(len(artifacts) - 1)
    ]

    # Process pairs in batches
    for batch_start in range(0, len(pairs), _MAX_PAGES_PER_CALL):
        batch_pairs = pairs[batch_start : batch_start + _MAX_PAGES_PER_CALL]

        pair_descriptions = []
        for art_i, art_j in batch_pairs:
            inv_i = inv_by_page.get(art_i.page_num)
            inv_j = inv_by_page.get(art_j.page_num)

            desc = (
                f"Pages {art_i.page_num} → {art_j.page_num}:\n"
                f"  Page {art_i.page_num} type={getattr(inv_i,'page_type','?')} "
                f"title={getattr(inv_i,'visible_title','?')} "
                f"lang={getattr(inv_i,'language','?')}\n"
                f"  Page {art_j.page_num} type={getattr(inv_j,'page_type','?')} "
                f"title={getattr(inv_j,'visible_title','?')} "
                f"lang={getattr(inv_j,'language','?')}\n"
                f"  Text snippet page {art_i.page_num}: {(art_i.text or '')[:400]}\n"
                f"  Text snippet page {art_j.page_num}: {(art_j.text or '')[:400]}"
            )
            pair_descriptions.append(desc)

        user_content = [
            {
                "type": "text",
                "text": (
                    "For each adjacent page pair, decide whether page_j continues the same document "
                    "as page_i, or starts a new logical document.\n\n"
                    + "\n\n".join(pair_descriptions)
                    + "\n\nRespond with JSON:\n"
                    "{\n"
                    '  "boundaries": [\n'
                    "    {\n"
                    '      "page_i": <int>,\n'
                    '      "page_j": <int>,\n'
                    '      "relationship": "continues|new_document|uncertain",\n'
                    '      "confidence": <float 0-1>,\n'
                    '      "evidence": ["<reason string>"]\n'
                    "    }\n"
                    "  ]\n"
                    "}"
                ),
            }
        ]

        raw, tokens = await _chat_json(client, _SYSTEM_PROMPT, user_content, max_tokens=2048)
        total_tokens += tokens

        try:
            parsed = _BoundaryResponse.model_validate_json(raw)
            all_boundaries.extend(parsed.boundaries)
        except (ValidationError, json.JSONDecodeError) as exc:
            logger.warning("Boundary parse error (batch %d): %s", batch_start, exc)

    return all_boundaries, total_tokens


# ---------------------------------------------------------------------------
# Task 3: Segment construction from boundary decisions
# ---------------------------------------------------------------------------

def _build_segments_from_boundaries(
    n_pages: int,
    boundaries: List[_BoundaryItem],
) -> List[tuple[int, int]]:
    """Convert boundary decisions to (start_page, end_page) tuples (1-based)."""

    # new_document or uncertain with low confidence → treat as boundary
    boundary_after: set[int] = set()
    for b in boundaries:
        if b.relationship == "new_document":
            boundary_after.add(b.page_i)
        elif b.relationship == "uncertain" and b.confidence < 0.6:
            boundary_after.add(b.page_i)

    segments: List[tuple[int, int]] = []
    start = 1
    for page in range(1, n_pages + 1):
        if page in boundary_after:
            segments.append((start, page))
            start = page + 1
    segments.append((start, n_pages))

    return [(s, e) for s, e in segments if s <= e]


# ---------------------------------------------------------------------------
# Task 4: Segment classification and metadata
# ---------------------------------------------------------------------------

async def _task_segment_classification(
    client: AsyncOpenAI,
    artifacts: List[DocumentPageArtifact],
    page_ranges: List[tuple[int, int]],
) -> tuple[List[_LLMSegment], int]:
    """Classify each segment and extract metadata + suggestions."""

    art_by_page = {art.page_num: art for art in artifacts}
    all_segments: List[_LLMSegment] = []
    total_tokens = 0

    for start_page, end_page in page_ranges:
        # Aggregate text for the segment (capped)
        seg_text_parts = []
        for pn in range(start_page, end_page + 1):
            art = art_by_page.get(pn)
            if art:
                seg_text_parts.append(f"[Page {pn}]\n{(art.text or art.ocr_text or '').strip()[:800]}")
        seg_text = "\n\n".join(seg_text_parts)[:6000]

        user_content = [
            {
                "type": "text",
                "text": (
                    f"Classify the following document segment (pages {start_page}–{end_page}).\n\n"
                    f"{seg_text}\n\n"
                    "Respond with JSON:\n"
                    "{\n"
                    '  "segments": [\n'
                    "    {\n"
                    f'      "start_page": {start_page},\n'
                    f'      "end_page": {end_page},\n'
                    '      "title": "<string or null>",\n'
                    '      "document_type": "manual|datasheet|certificate|calibration|invoice|report|unknown",\n'
                    '      "summary": "<1-3 sentence summary>",\n'
                    '      "detected_language": "<ISO 639-1>",\n'
                    '      "confidence": <float 0-1>,\n'
                    '      "evidence": [\n'
                    '        {"page": <int>, "kind": "text|visual|layout", "value": "<evidence string>"}\n'
                    "      ],\n"
                    '      "unknown_model_candidate": <bool>,\n'
                    '      "suggestions": [\n'
                    "        {\n"
                    '          "type": "tag|managed_model|process_link|category",\n'
                    '          "proposed_name": "<string or null>",\n'
                    '          "manufacturer": "<string or null>",\n'
                    '          "model": "<string or null>",\n'
                    '          "target_id": null,\n'
                    '          "confidence": <float 0-1>,\n'
                    '          "evidence": "<reason>"\n'
                    "        }\n"
                    "      ]\n"
                    "    }\n"
                    "  ]\n"
                    "}"
                ),
            }
        ]

        # Add first-page image if available
        if _VISION_ENABLED:
            first_art = art_by_page.get(start_page)
            if first_art and first_art.thumbnail_path:
                block = _image_content_block(first_art.thumbnail_path)
                if block:
                    user_content.insert(0, block)

        raw, tokens = await _chat_json(client, _SYSTEM_PROMPT, user_content, max_tokens=2048)
        total_tokens += tokens

        try:
            parsed = _SegmentClassificationResponse.model_validate_json(raw)
            all_segments.extend(parsed.segments)
        except (ValidationError, json.JSONDecodeError) as exc:
            logger.warning(
                "Segment classification parse error for pages %d-%d: %s",
                start_page, end_page, exc,
            )
            # Fallback: store minimal segment
            all_segments.append(
                _LLMSegment(
                    start_page=start_page,
                    end_page=end_page,
                    confidence=0.0,
                )
            )

    return all_segments, total_tokens


# ---------------------------------------------------------------------------
# Task 5: Validation
# ---------------------------------------------------------------------------

def _validate_segments(
    segments: List[_LLMSegment],
    n_pages: int,
) -> List[str]:
    """Return a list of validation warnings (empty = all clear)."""
    warnings: List[str] = []

    if not segments:
        warnings.append("No segments produced.")
        return warnings

    # Sort by start page
    sorted_segs = sorted(segments, key=lambda s: s.start_page)

    prev_end = 0
    for seg in sorted_segs:
        if seg.start_page < 1:
            warnings.append(f"Segment starts at page {seg.start_page} < 1.")
        if seg.end_page > n_pages:
            warnings.append(
                f"Segment ends at page {seg.end_page} > n_pages {n_pages}."
            )
        if seg.start_page > seg.end_page:
            warnings.append(
                f"Segment start {seg.start_page} > end {seg.end_page}."
            )
        if seg.start_page <= prev_end:
            warnings.append(
                f"Overlapping segment: starts at {seg.start_page}, "
                f"previous ended at {prev_end}."
            )
        prev_end = seg.end_page

    # Check coverage
    first_start = sorted_segs[0].start_page if sorted_segs else 0
    last_end = sorted_segs[-1].end_page if sorted_segs else 0
    if first_start > 1:
        warnings.append(f"Pages 1..{first_start-1} not covered.")
    if last_end < n_pages:
        warnings.append(f"Pages {last_end+1}..{n_pages} not covered.")

    return warnings


# ---------------------------------------------------------------------------
# Convert LLM output to canonical schema + store in DB
# ---------------------------------------------------------------------------

def _to_canonical(
    document_id: int,
    segments: List[_LLMSegment],
) -> CanonicalMethodOutput:
    canonical_segs = []
    for seg in segments:
        evidence_items = []
        for ev in seg.evidence:
            try:
                evidence_items.append(
                    EvidenceItem(
                        page=ev.get("page", 0),
                        kind=ev.get("kind", "text"),
                        value=str(ev.get("value", "")),
                    )
                )
            except Exception:
                pass

        suggestions = []
        for sug in seg.suggestions:
            suggestions.append(
                CanonicalSuggestionPayload(
                    type=sug.type,
                    proposed_name=sug.proposed_name,
                    manufacturer=sug.manufacturer,
                    model=sug.model,
                    target_id=sug.target_id,
                    confidence=sug.confidence,
                    evidence=sug.evidence,
                )
            )

        canonical_segs.append(
            CanonicalSegmentPayload(
                start_page=seg.start_page,
                end_page=seg.end_page,
                title=seg.title,
                document_type=seg.document_type,
                summary=seg.summary,
                detected_language=seg.detected_language,
                confidence=seg.confidence,
                evidence=evidence_items,
                suggestions=suggestions,
            )
        )

    return CanonicalMethodOutput(
        document_id=document_id,
        method=DIMethod.LLM_VLM,
        segments=canonical_segs,
    )


def store_llm_predictions(
    db: Session,
    job_id: int,
    document_id: int,
    canonical: CanonicalMethodOutput,
    method_run: DocumentMethodRun,
) -> List[DocumentSegment]:
    """Persist canonical output as DocumentSegment + suggestion rows."""

    created_segments: List[DocumentSegment] = []

    for seg_payload in canonical.segments:
        seg = DocumentSegment(
            job_id=job_id,
            document_id=document_id,
            method=DIMethod.LLM_VLM,
            start_page=seg_payload.start_page,
            end_page=seg_payload.end_page,
            title=seg_payload.title,
            document_type=seg_payload.document_type,
            summary=seg_payload.summary,
            detected_language=seg_payload.detected_language,
            confidence=seg_payload.confidence,
            evidence=[ev.model_dump() for ev in seg_payload.evidence],
            status=DISegmentStatus.PREDICTED,
        )
        db.add(seg)
        db.flush()  # get seg.id

        for sug_payload in seg_payload.suggestions:
            sug = DocumentSegmentSuggestion(
                segment_id=seg.id,
                suggestion_type=sug_payload.type,
                proposed_name=sug_payload.proposed_name,
                manufacturer=sug_payload.manufacturer,
                model_name=sug_payload.model,
                target_id=sug_payload.target_id,
                confidence=sug_payload.confidence,
                evidence=sug_payload.evidence,
                status=DISuggestionStatus.PENDING,
            )
            db.add(sug)

        created_segments.append(seg)

    return created_segments


# ---------------------------------------------------------------------------
# Main pipeline entry point
# ---------------------------------------------------------------------------

async def run_llm_vlm_pipeline(
    db: Session,
    job_id: int,
    document: Document,
    artifacts: List[DocumentPageArtifact],
    method_run: DocumentMethodRun,
) -> CanonicalMethodOutput:
    """
    Full LLM/VLM teacher pipeline for one document.

    Parameters
    ----------
    db          : SQLAlchemy session (caller commits).
    job_id      : The parent DIJob id.
    document    : The Document ORM object.
    artifacts   : Pre-built page artifacts (ordered by page_num).
    method_run  : The DocumentMethodRun row to update.

    Returns
    -------
    CanonicalMethodOutput  – also stored in method_run.output and as segment rows.
    """
    t0 = time.monotonic()
    total_tokens = 0
    client = _get_client()
    n_pages = document.n_pages or len(artifacts)

    logger.info("[LLM/VLM] Starting pipeline for doc %d (%d pages)", document.id, n_pages)

    # --- Task 1: page inventory ---
    inventory, tok = await _task_page_inventory(client, artifacts)
    total_tokens += tok
    logger.info("[LLM/VLM] Page inventory done: %d items, %d tokens", len(inventory), tok)

    # --- Task 2: boundary detection ---
    boundaries, tok = await _task_boundary_detection(client, artifacts, inventory)
    total_tokens += tok
    logger.info("[LLM/VLM] Boundary detection done: %d pairs evaluated, %d tokens", len(boundaries), tok)

    # --- Task 3: segment construction ---
    page_ranges = _build_segments_from_boundaries(n_pages, boundaries)
    logger.info("[LLM/VLM] Segment construction: %d segments", len(page_ranges))

    # --- Task 4: classification ---
    classified_segments, tok = await _task_segment_classification(client, artifacts, page_ranges)
    total_tokens += tok
    logger.info("[LLM/VLM] Classification done: %d segments, %d tokens", len(classified_segments), tok)

    # --- Task 5: validation ---
    warnings = _validate_segments(classified_segments, n_pages)
    if warnings:
        logger.warning("[LLM/VLM] Validation warnings for doc %d: %s", document.id, warnings)

    # --- Convert to canonical output ---
    canonical = _to_canonical(document.id, classified_segments)

    # --- Update method_run ---
    method_run.output = canonical.model_dump()
    method_run.llm_tokens_used = total_tokens
    method_run.latency_seconds = time.monotonic() - t0
    method_run.status = "completed"
    from datetime import datetime
    method_run.completed_at = datetime.utcnow()

    # --- Persist segments & suggestions ---
    store_llm_predictions(db, job_id, document.id, canonical, method_run)

    logger.info(
        "[LLM/VLM] Pipeline complete for doc %d: %d segments, %d total tokens, %.1fs",
        document.id,
        len(canonical.segments),
        total_tokens,
        method_run.latency_seconds,
    )

    return canonical
