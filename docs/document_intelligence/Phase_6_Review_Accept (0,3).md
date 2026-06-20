# Phase 6 — Drafting / Review / Accept → Merge into Main Data
**Depends on: Phase 0 AND Phase 3**
**Status: ~30 % complete. Read API works. Write/auto-apply, split, and versioning are not implemented.**

---

## Goal
A reviewer sees extracted segments, metadata, and suggestions; accepts, edits, or
rejects them; and on accept, the data is **automatically applied to the real CMMS
tables** (tag links, model links, new managed models, child PDFs).

---

## What is already implemented

| Item | Location | Notes |
|------|----------|-------|
| `GET /documents/{doc_id}/segments` | `routes.py:186` | Returns segments + embedded suggestions |
| `GET /segments/{id}` | `routes.py:201` | Single segment detail |
| `PATCH /segments/{id}` | `routes.py:213` | Accept / reject / edit segment fields |
| `GET /segments/{id}/suggestions` | `routes.py:242` | List suggestions for a segment |
| `PATCH /suggestions/{id}` | `routes.py:255` | Updates status to accepted/rejected — **no auto-apply** |
| `GET /jobs/{id}/model-suggestions` | `routes.py:289` | List unknown-model candidates |
| `PATCH /model-suggestions/{id}` | `routes.py:306` | Updates status — **no model creation** |
| `GET /jobs/{id}/export-labels` | `routes.py:354` | Gold-label export |

---

## Remaining gaps

### Gap 6-A — Auto-apply on suggestion accept  *(inconsistency I-12)*

This is the most important gap.  Accepting a suggestion must write into the real
CMMS tables **inside the caller's RBAC**.

#### Table references

| Suggestion type | Action on accept | Table / model |
|----------------|-----------------|--------------|
| `tag` with `target_id` set | Create `TagDocumentLink` | `tag_management.models.TagDocumentLink` |
| `managed_model` with `target_id` set | Create `ModelDocumentLink` | `model_management.models.ModelDocumentLink` |
| `managed_model` with no `target_id` | Create `ManagedModel` first, then `ModelDocumentLink` | `model_management.models.ManagedModel` |

#### Implementation in `routes.py` — replace `patch_suggestion`

```python
from tag_management.models import TagDocumentLink
from model_management.models import ManagedModel, ModelDocumentLink
from tag_management.system_tag import SystemTag
from deps import require_permission

@router.patch("/suggestions/{suggestion_id}", response_model=SuggestionOut)
def patch_suggestion(
    suggestion_id: int,
    payload: SuggestionPatch,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_permission("document_intelligence:suggestion_review")),
):
    sug = (
        db.query(DocumentSegmentSuggestion)
        .filter(DocumentSegmentSuggestion.id == suggestion_id)
        .first()
    )
    if not sug:
        raise AppException(ErrorCode.DI_SUGGESTION_NOT_FOUND)

    if payload.status not in (DISuggestionStatus.ACCEPTED, DISuggestionStatus.REJECTED):
        raise AppException(ErrorCode.DI_INVALID_STATUS)

    sug.status = payload.status
    sug.reviewed_by_user_id = current_user.id
    sug.reviewed_at = datetime.utcnow()

    if payload.status == DISuggestionStatus.ACCEPTED:
        _apply_suggestion(db, sug, current_user)

    db.commit()
    db.refresh(sug)
    return sug


def _apply_suggestion(db: Session, sug: DocumentSegmentSuggestion, user: User) -> None:
    """Write the accepted suggestion into the main CMMS tables."""
    seg = sug.segment   # the parent DocumentSegment (loaded via relationship)
    document_id = seg.document_id

    if sug.suggestion_type == DISuggestionType.TAG:
        if not sug.target_id:
            return   # can't link without a target; reviewer should have set it
        existing = db.query(TagDocumentLink).filter_by(
            tag_id=sug.target_id, document_id=document_id
        ).first()
        if not existing:
            link = TagDocumentLink(
                tag_id=sug.target_id,
                document_id=document_id,
                linked_by_user_id=user.id,
                start_page=seg.start_page,
                end_page=seg.end_page,
            )
            db.add(link)

    elif sug.suggestion_type == DISuggestionType.MANAGED_MODEL:
        if sug.target_id:
            # Link to an existing ManagedModel
            existing = db.query(ModelDocumentLink).filter_by(
                model_id=sug.target_id, document_id=document_id
            ).first()
            if not existing:
                link = ModelDocumentLink(
                    model_id=sug.target_id,
                    document_id=document_id,
                    linked_by_user_id=user.id,
                )
                db.add(link)
        else:
            # This path should not be reached for regular suggestions;
            # unknown-model candidates are handled via PATCH /model-suggestions/{id}.
            pass
```

**Important:** The auto-apply must check that the `SystemTag` or `ManagedModel`
belongs to the same company as `current_user`.  Add a company-scoping guard:

```python
if sug.suggestion_type == DISuggestionType.TAG and sug.target_id:
    tag = db.query(SystemTag).get(sug.target_id)
    if not tag or tag.company_id != current_user.company_id:
        raise AppException(ErrorCode.DI_SUGGESTION_NOT_FOUND)  # or PERMISSION_DENIED
```

---

### Gap 6-B — Accept unknown-model → create `ManagedModel`

Update `patch_model_creation_suggestion` in `routes.py`:

```python
@router.patch("/model-suggestions/{suggestion_id}", response_model=ModelCreationSuggestionOut)
def patch_model_creation_suggestion(
    suggestion_id: int,
    payload: ModelCreationSuggestionPatch,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_permission("document_intelligence:model_suggestion_review")),
):
    sug = db.query(DIModelCreationSuggestion).filter_by(id=suggestion_id).first()
    if not sug:
        raise AppException(ErrorCode.DI_SUGGESTION_NOT_FOUND)

    if payload.status not in (DISuggestionStatus.ACCEPTED, DISuggestionStatus.REJECTED):
        raise AppException(ErrorCode.DI_INVALID_STATUS)

    # Apply overrides before creating
    if payload.manufacturer: sug.manufacturer = payload.manufacturer
    if payload.model_name:   sug.model_name   = payload.model_name
    if payload.description:  sug.description  = payload.description

    sug.status = payload.status
    sug.reviewed_by_user_id = current_user.id
    sug.reviewed_at = datetime.utcnow()

    if payload.status == DISuggestionStatus.ACCEPTED:
        # Check for existing model to avoid duplicate
        existing = db.query(ManagedModel).filter_by(
            company_id=current_user.company_id,
            manufacturer=sug.manufacturer or "",
            model=sug.model_name,
        ).first()

        if existing:
            managed_model = existing
        else:
            managed_model = ManagedModel(
                company_id=current_user.company_id,
                manufacturer=sug.manufacturer or "Unknown",
                model=sug.model_name,
                description=sug.description,
                owner_id=current_user.id,
            )
            db.add(managed_model)
            db.flush()

        sug.created_managed_model_id = managed_model.id

        # Also link it to the source document
        existing_link = db.query(ModelDocumentLink).filter_by(
            model_id=managed_model.id, document_id=sug.document_id
        ).first()
        if not existing_link:
            db.add(ModelDocumentLink(
                model_id=managed_model.id,
                document_id=sug.document_id,
                linked_by_user_id=current_user.id,
            ))

    db.commit()
    db.refresh(sug)
    return sug
```

---

### Gap 6-C — Child PDF split endpoint  *(table `document_split_outputs` — create in Phase 0)*

Add endpoint:
```
POST /document-intelligence/segments/{segment_id}/split
     permission: document_intelligence:job_create
     body: {} (no body required; uses segment's start_page/end_page)
     returns: { split_output_id, child_document_id, asset_id }
```

**Implementation steps:**

1. Load the segment and the parent `Document`.
2. Pull the original PDF bytes from object storage (`download_bytes` on the `original.pdf` key).
3. Use `pypdf` (already in requirements; if not, add it) to extract the page range:

```python
from pypdf import PdfReader, PdfWriter

def extract_page_range_pdf(pdf_bytes: bytes, start_page: int, end_page: int) -> bytes:
    reader = PdfReader(io.BytesIO(pdf_bytes))
    writer = PdfWriter()
    for page_idx in range(start_page - 1, end_page):   # 0-based
        if page_idx < len(reader.pages):
            writer.add_page(reader.pages[page_idx])
    out = io.BytesIO()
    writer.write(out)
    return out.getvalue()
```

4. Upload the child PDF to object storage:
```python
key = split_output_key(parent_doc.id, segment.id)
upload_bytes(key, child_pdf_bytes, "application/pdf")
```

5. Create a `FileAsset` row for the new PDF (following the project's existing pattern
   for how `FileAsset` rows are created — check `backend/Models/file_asset.py` and
   existing upload routes).

6. Create a child `Document` row linked to the same owner and company:
```python
child_doc = Document(
    owner_id=current_user.id,
    filename=f"{parent_doc.filename}_part_{segment.start_page}-{segment.end_page}.pdf",
    n_pages=segment.end_page - segment.start_page + 1,
    n_chunks=0,
    status=DocumentStatusType.QUEUED,
    file_path=None,   # will be populated when the child is processed
    original_asset_id=file_asset.id,
)
db.add(child_doc)
db.flush()
```

7. Link child back to segment:
```python
segment.child_document_id = child_doc.id
```

8. Create `DocumentSplitOutput` row:
```python
split_out = DocumentSplitOutput(
    parent_document_id=parent_doc.id,
    segment_id=segment.id,
    child_document_id=child_doc.id,
    generated_asset_id=file_asset.id,
)
db.add(split_out)
db.commit()
```

> **Note:** Do not enqueue MinerU/DI processing for the child document here.
> That is the user's choice after reviewing.

---

### Gap 6-D — Re-run versioning  *(new feature)*

When a second DI job runs on the same document that already has reviewed/accepted
segments, the system must diff the new output against the existing accepted data
and surface "suggested changes" instead of silently overwriting or duplicating.

**Add a `revision` column to `DocumentSegment`:**

```python
revision = Column(Integer, nullable=False, default=1)
superseded_by_segment_id = Column(
    Integer, ForeignKey("document_segments.id", ondelete="SET NULL"),
    nullable=True,
)
```

Generate a new migration for these two columns.

**After Phase-3 / Phase-5 produces new segments for a document that has prior
accepted segments**, run a diff:

```python
def diff_against_existing(
    db, document_id: int, new_segments: list[DocumentSegment]
) -> list[dict]:
    """
    Compare new_segments to the latest accepted segments for document_id.
    Return a list of 'change suggestions': {old_segment_id, field, old_value, new_value}.
    """
    accepted = (
        db.query(DocumentSegment)
        .filter(
            DocumentSegment.document_id == document_id,
            DocumentSegment.status == DISegmentStatus.ACCEPTED,
        )
        .order_by(DocumentSegment.start_page)
        .all()
    )
    changes = []
    for new in new_segments:
        # Find the accepted segment with the most page overlap
        best = max(
            accepted,
            key=lambda a: min(a.end_page, new.end_page) - max(a.start_page, new.start_page),
            default=None,
        )
        if best is None:
            changes.append({"type": "new_segment", "new_start": new.start_page, "new_end": new.end_page})
            continue
        for field in ("document_type", "title", "summary", "detected_language"):
            old_val = getattr(best, field)
            new_val = getattr(new, field)
            if old_val != new_val:
                changes.append({
                    "type": "field_change",
                    "old_segment_id": best.id,
                    "new_segment_id": new.id,
                    "field": field,
                    "old_value": old_val,
                    "new_value": new_val,
                })
    return changes
```

New segments on re-runs start with a higher `revision` number.  Old accepted
segments are NOT deleted — `superseded_by_segment_id` is set to point to the
new version once the reviewer accepts the change.

---

## Tests (mandatory)

Create `backend/document_intelligence/tests/test_phase6.py`.

Required tests:
- Accept tag suggestion with valid `target_id` → `TagDocumentLink` row created.
- Accept tag suggestion with wrong `company_id` → 403 / `PERMISSION_DENIED`.
- Accept tag suggestion twice → only one `TagDocumentLink` row (idempotent).
- Accept `managed_model` suggestion with `target_id` → `ModelDocumentLink` row created.
- Accept unknown-model suggestion (no `target_id`) → `ManagedModel` row created + `ModelDocumentLink`.
- Accept unknown-model suggestion for an already-existing model → no duplicate model created.
- `POST /segments/{id}/split` → child PDF bytes extractable from object storage;
  `DocumentSplitOutput` row exists; child `Document` row exists.
- Second job on same document → diff returns change suggestions; old accepted segment
  NOT deleted; `superseded_by_segment_id` set after reviewer accepts the new version.
- Reject suggestion → no tag/model link created.

---

## Acceptance checklist

- [ ] Accepting a `tag` suggestion creates exactly one `TagDocumentLink` row with `start_page`/`end_page` from the segment.
- [ ] Accepting a `managed_model` suggestion with `target_id` creates exactly one `ModelDocumentLink`.
- [ ] Accepting an unknown-model suggestion creates a `ManagedModel` + `ModelDocumentLink`; the model is queryable through the normal model-management API.
- [ ] A rejected suggestion creates nothing in the CMMS tables.
- [ ] `POST /segments/{id}/split` generates a valid PDF (readable by `pypdf`) in object storage and a linked child `Document` row.
- [ ] Re-running a job on a document with prior accepted segments shows change suggestions, not duplicates or silent overwrites.
- [ ] All tests pass.
