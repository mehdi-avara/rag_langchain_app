# Phase 3 — Teacher Method (VLM/LLM) at Scale
**Depends on: Phase 1 AND Phase 2**
**Status: ~50 % complete. The 5-step pipeline runs locally. Batch dispatcher, raw response storage, and result JSON files are missing.**

---

## Goal
Run the highest-quality VLM/LLM pipeline over the full document backlog using the
Phase-2 GPU infrastructure, save raw + parsed results to object storage for audit/replay,
and emit a clean labeled dataset for Phase-4 distillation.

Ordering: MinerU runs **first** (Phase 1 + Phase 2 MinerU node) to produce text and
full-page images; **then** the VLM node processes those artifacts.  Both stages are
resumable via Phase-2 checkpoints.

---

## What is already implemented

| Item | Location | Notes |
|------|----------|-------|
| 5-step LLM/VLM pipeline | `services/llm_vlm_method.py` | Page inventory → boundary → segment construction → classification → validation |
| JSON-mode LLM calls | `llm_vlm_method.py:99-121` | Uses `response_format={"type":"json_object"}` |
| Vision support | `llm_vlm_method.py:76-93` | Controlled by `DI_LLM_VISION_ENABLED` env var |
| Pydantic validation of LLM output | `llm_vlm_method.py:128-182` | Each step has its own response model |
| DB persistence | `llm_vlm_method.py:580-625` | `DocumentSegment` + `DocumentSegmentSuggestion` rows created |
| Canonical output format | `schemas.py:202-226` | `CanonicalMethodOutput` + `CanonicalSegmentPayload` |
| Celery task integration | `tasks.py:162-171` | Calls `run_llm_vlm_pipeline` for `llm_vlm` method |

---

## Remaining gaps

### Gap 3-A — Wire to Phase-2 batch dispatcher  *(inconsistency I-9)*

The pipeline currently runs one document synchronously inside a Celery task.
For a backlog of hundreds of documents against a rented GPU node, it must go
through the Phase-2 resumable dispatcher.

**New Celery task for fleet-dispatched runs:**

Create `backend/document_intelligence/tasks.py` — add a second task alongside the
existing single-document task:

```python
@celery_app.task(
    bind=True,
    name="document_intelligence.dispatch_fleet_batch",
)
def dispatch_fleet_batch_task(self, run_id: str, doc_ids: list[int], node_id: int) -> dict:
    """
    Run the VLM teacher over a list of documents using a registered fleet node.
    Called by the Fleet Manager after the node is healthy.
    """
    from document_intelligence.services.batch_dispatcher import dispatch_batches
    from document_intelligence.models import DIFleetNode

    db = SessionLocal()
    try:
        node = db.query(DIFleetNode).get(node_id)
        endpoint_url = node.endpoint_url

        dispatch_batches(
            run_id=run_id,
            doc_ids=doc_ids,
            endpoint_url=endpoint_url,
            batch_size=int(os.getenv("DI_LLM_MAX_DOCS_PER_BATCH", "10")),
        )
        # When queue is drained, signal the operator
        from document_intelligence.fleet.manager import FleetManager
        node.status = "safe_to_shutdown"
        db.commit()
        logger.info("Fleet batch complete. Node %s safe to shut down.", node.node_id)
    finally:
        db.close()
```

Inside `dispatch_batches` (Phase 2), each doc calls `run_llm_vlm_pipeline` against
the fleet node's endpoint by temporarily overriding the `base_url`:

```python
# In batch_dispatcher.py
os.environ["OPENAI_BASE_URL"] = endpoint_url   # or pass as kwarg
from document_intelligence.services.llm_vlm_method import run_llm_vlm_pipeline
```

---

### Gap 3-B — Persist raw VLM responses to object storage  *(inconsistency I-10)*

Every LLM call must save its raw JSON response to object storage for audit and replay.
Add this inside `_chat_json` in `llm_vlm_method.py`:

```python
from document_intelligence.services.storage_keys import teacher_raw_key, upload_bytes
import uuid

async def _chat_json(
    client: AsyncOpenAI,
    system: str,
    user_content: list[dict],
    max_tokens: int = 4096,
    doc_id: int | None = None,        # add this parameter
    step_name: str = "unknown",       # add this parameter
) -> tuple[str, int]:
    response = await client.chat.completions.create(...)
    content = response.choices[0].message.content or ""
    tokens = response.usage.total_tokens if response.usage else 0

    # Save raw response
    if doc_id is not None:
        batch_id = f"{step_name}-{uuid.uuid4().hex[:8]}"
        raw_payload = {
            "step": step_name,
            "model": _MODEL,
            "tokens": tokens,
            "response": content,
        }
        upload_bytes(
            teacher_raw_key(doc_id, batch_id),
            json.dumps(raw_payload).encode(),
        )

    return content, tokens
```

Pass `doc_id` and `step_name` from each task function (`_task_page_inventory`, etc.)
through to `_chat_json`.

---

### Gap 3-C — Write result JSON files to object storage  *(inconsistency I-11)*

After `store_llm_predictions` completes, write the three result JSON files.
Add to the end of `run_llm_vlm_pipeline`:

```python
from document_intelligence.services.storage_keys import (
    results_segments_key, results_suggestions_key, results_metadata_key,
    upload_bytes,
)
import json

# segments.json — all segments with page ranges and confidence
segments_out = [
    {
        "segment_id": seg.id,
        "start_page": seg.start_page,
        "end_page": seg.end_page,
        "method": seg.method,
        "confidence": seg.confidence,
        "document_type": seg.document_type,
    }
    for seg in created_segments
]
upload_bytes(
    results_segments_key(document.id),
    json.dumps(segments_out, ensure_ascii=False).encode(),
)

# suggestions.json — all suggestions per segment
suggestions_out = []
for seg in created_segments:
    for sug in seg.suggestions:
        suggestions_out.append({
            "segment_id": seg.id,
            "type": sug.suggestion_type,
            "proposed_name": sug.proposed_name,
            "manufacturer": sug.manufacturer,
            "model_name": sug.model_name,
            "confidence": sug.confidence,
            "evidence": sug.evidence,
        })
upload_bytes(
    results_suggestions_key(document.id),
    json.dumps(suggestions_out, ensure_ascii=False).encode(),
)

# metadata.json — title/summary/language per segment
metadata_out = [
    {
        "segment_id": seg.id,
        "start_page": seg.start_page,
        "end_page": seg.end_page,
        "title": seg.title,
        "summary": seg.summary,
        "detected_language": seg.detected_language,
        "evidence": seg.evidence,
    }
    for seg in created_segments
]
upload_bytes(
    results_metadata_key(document.id),
    json.dumps(metadata_out, ensure_ascii=False).encode(),
)
logger.info("Wrote DI result JSON files to object storage for doc %d", document.id)
```

The identifiers (`segment_id`, `start_page`, `end_page`) match `DocumentPageArtifact.page_num`,
so the result JSON joins 1:1 to the `pages.jsonl` from Phase 1.

---

### Gap 3-D — Teacher label export format

The existing `GET /jobs/{job_id}/export-labels` endpoint produces a human-readable
format.  For Phase-4 distillation, we also need a machine-readable dataset where
each row is a labeled page range.

Add a service function at
`backend/document_intelligence/services/label_export.py`:

```python
import json
from document_intelligence.models import DocumentSegment, DISuggestionStatus, DISegmentStatus

def export_teacher_labels(db, job_id: int) -> list[dict]:
    """
    Export teacher labels in distillation format.
    One dict per accepted segment; each dict has:
      page_range, document_type, tags (list), models (list), evidence.
    """
    segments = (
        db.query(DocumentSegment)
        .filter(
            DocumentSegment.job_id == job_id,
            DocumentSegment.status != DISegmentStatus.REJECTED,
        )
        .order_by(DocumentSegment.start_page)
        .all()
    )
    rows = []
    for seg in segments:
        accepted_tags = [
            s.proposed_name
            for s in seg.suggestions
            if s.suggestion_type == "tag" and s.status == DISuggestionStatus.ACCEPTED
        ]
        accepted_models = [
            {"manufacturer": s.manufacturer, "model": s.model_name}
            for s in seg.suggestions
            if s.suggestion_type == "managed_model" and s.status == DISuggestionStatus.ACCEPTED
        ]
        rows.append({
            "document_id": seg.document_id,
            "job_id": job_id,
            "start_page": seg.start_page,
            "end_page": seg.end_page,
            "document_type": seg.document_type,
            "tags": accepted_tags,
            "models": accepted_models,
            "confidence": seg.confidence,
            "evidence": seg.evidence or [],
            "source": "teacher",
        })
    return rows
```

This format is what Phase 4 consumes for distillation.

---

## Image batching note

The `_task_page_inventory` function currently adds **all** page thumbnail images to
the same API call (one image block per page).  For large documents this exceeds the
model's context length.  When running against the fleet node, cap images per call:

```python
# In _task_page_inventory, replace the image attachment block:
if _VISION_ENABLED:
    # Only attach images up to MAX_IMAGES_PER_CALL to avoid context overflow
    MAX_IMAGES = int(os.getenv("DI_LLM_MAX_IMAGES_PER_CALL", "10"))
    for art in batch[:MAX_IMAGES]:
        if art.thumbnail_path:
            block = _image_content_block(art.thumbnail_path)
            ...
```

---

## Tests (mandatory)

Create `backend/document_intelligence/tests/test_phase3.py`.

Mock the `AsyncOpenAI` client so tests never touch a real LLM.

Required tests:
- `_task_page_inventory` with a mocked client returning valid JSON → list of `_PageInventoryItem`.
- `_task_page_inventory` with malformed JSON from the model → warns + returns empty list (not crash).
- `_task_boundary_detection` with `new_document` relationship → boundary recorded.
- `_build_segments_from_boundaries` with known boundary list → expected `(start, end)` tuples.
- `_validate_segments` with overlapping segments → returns a warning string containing "Overlapping".
- `_validate_segments` with gap in page coverage → returns a warning string containing "not covered".
- `run_llm_vlm_pipeline` end-to-end (fully mocked LLM): 3-page doc → 1 segment → 1 `DocumentSegment` row in DB.
- `results_segments_key` object written to mock S3 after pipeline completes.
- Raw response object written to mock S3 for each LLM step.
- Re-run on the same job (checkpoint exists) → skips already-done doc IDs.

---

## Acceptance checklist

- [ ] `run_llm_vlm_pipeline` with a mocked LLM produces valid `DocumentSegment` rows.
- [ ] Raw VLM responses are written to `di/teacher/raw_responses/` in object storage after each call.
- [ ] `di/results/segments.json`, `suggestions.json`, `metadata.json` are in object storage after the run.
- [ ] Re-running with the Phase-2 dispatcher resumes from the last checkpoint, not from zero.
- [ ] A batch with one malformed document does not prevent the others from completing.
- [ ] Teacher label export produces one row per non-rejected segment with the distillation format.
- [ ] All tests pass with the LLM mocked.
