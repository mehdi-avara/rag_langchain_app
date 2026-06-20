# Phase 7 — Human-Correction Feedback Loop
**Depends on: Phase 4 AND Phase 6**
**Status: ~30 % complete. `DocumentIntelligenceLabel` model and label-export endpoint exist. Re-distillation is not implemented.**

---

## Goal
Close the loop: reviewer edits and accept/reject decisions from Phase 6 become
**gold labels** that are fed back into Phase 4 so the student methods keep improving
and more documents clear without touching the GPU teacher.

---

## What is already implemented

| Item | Location | Notes |
|------|----------|-------|
| `DocumentIntelligenceLabel` model | `models.py:379-410` | One row per document; `gold_segments` JSON column |
| `GET /jobs/{id}/export-labels` | `routes.py:354` | Upserts a `DocumentIntelligenceLabel` row from accepted segments |

---

## P7.1 — Capture corrections as gold labels (complete the existing endpoint)

The existing export endpoint only captures accepted/modified segments at the time
of export.  We need to also capture **per-decision corrections** so we know when
the reviewer changed the teacher's output.

### Add a correction capture hook to `patch_segment` and `patch_suggestion`

Every time a reviewer modifies a field that differs from what the teacher predicted,
record the correction as a `DIHumanCorrection` row:

#### New model

```python
class DIHumanCorrection(Base):
    """One human edit/correction tied to a segment field or suggestion."""
    __tablename__ = "di_human_corrections"

    id = Column(Integer, primary_key=True)
    segment_id = Column(
        Integer, ForeignKey("document_segments.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )
    job_id = Column(
        Integer, ForeignKey("document_intelligence_jobs.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )
    document_id = Column(
        Integer, ForeignKey("documents.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )
    corrected_by_user_id = Column(
        Integer, ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )
    field_name = Column(String, nullable=False)     # e.g. "document_type", "start_page", "suggestion_accepted"
    original_value = Column(Text, nullable=True)    # teacher's prediction
    corrected_value = Column(Text, nullable=True)   # reviewer's final value
    method_source = Column(String, nullable=True)   # which method produced the original
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)

    segment = relationship("DocumentSegment")
    corrected_by = relationship("User", foreign_keys=[corrected_by_user_id])
```

Register in `Models/__init__.py` and generate a migration.

#### Capture hook in `patch_segment`

```python
@router.patch("/segments/{segment_id}", response_model=SegmentOut)
def patch_segment(segment_id, payload, db, current_user):
    seg = ...  # existing lookup

    update_data = payload.model_dump(exclude_none=True)
    for field, new_value in update_data.items():
        old_value = getattr(seg, field, None)
        if old_value != new_value:
            db.add(DIHumanCorrection(
                segment_id=seg.id,
                job_id=seg.job_id,
                document_id=seg.document_id,
                corrected_by_user_id=current_user.id,
                field_name=field,
                original_value=str(old_value) if old_value is not None else None,
                corrected_value=str(new_value),
                method_source=seg.method,
            ))
        setattr(seg, field, new_value)
    ...
```

#### Capture suggestion accept/reject

```python
# In patch_suggestion (Phase 6 _apply_suggestion) — add after status update:
db.add(DIHumanCorrection(
    segment_id=sug.segment_id,
    job_id=sug.segment.job_id,
    document_id=sug.segment.document_id,
    corrected_by_user_id=current_user.id,
    field_name=f"suggestion_{sug.suggestion_type}",
    original_value=f"pending",
    corrected_value=payload.status,  # "accepted" or "rejected"
    method_source=sug.segment.method,
))
```

### Updated `export_teacher_labels`

The label export in `label_export.py` (Phase 3) should be updated to merge
teacher labels + human corrections into one dataset row:

```python
def export_human_labels(db, document_id: int) -> list[dict]:
    """
    Export the latest human-reviewed labels for a document.
    Includes both teacher output (as base) and all human corrections applied on top.
    """
    label = (
        db.query(DocumentIntelligenceLabel)
        .filter_by(document_id=document_id)
        .first()
    )
    base_segments = label.gold_segments if label else []

    corrections = (
        db.query(DIHumanCorrection)
        .filter_by(document_id=document_id)
        .order_by(DIHumanCorrection.created_at)
        .all()
    )

    correction_map: dict[int, list] = {}
    for c in corrections:
        correction_map.setdefault(c.segment_id, []).append({
            "field": c.field_name,
            "original": c.original_value,
            "corrected": c.corrected_value,
        })

    rows = []
    for seg in base_segments:
        seg_id = seg.get("segment_id")
        rows.append({
            **seg,
            "corrections": correction_map.get(seg_id, []),
            "source": "human_reviewed",
        })
    return rows
```

---

## P7.2 — Periodic re-distillation

After enough human corrections accumulate, re-run Phase 4 distillation with the
updated label set.

### New endpoint

```
POST /document-intelligence/redisill
     permission: document_intelligence:distill
     body: { min_corrections: int = 10 }
     returns: { triggered: bool, report: dict | null }
```

Logic:
1. Count uncounted `DIHumanCorrection` rows since the last distillation run.
2. If count < `min_corrections`, return `{"triggered": false}`.
3. Otherwise, call `export_human_labels` for all documents with corrections,
   merge with teacher labels, and pass the combined dataset to Phase 4's
   `distillation.py` `run_distillation(labels)`.
4. Compare the new `boundary_f1` to the previous `DIDistillationResult` for the
   same method.
5. If `boundary_f1` improved, update `DIMethodConfig` thresholds.
6. Return the comparison report.

### Human-agreement metric

Track how closely the student methods now agree with human reviewers (not just
with the teacher):

```python
def human_agreement(
    method: str,
    db,
    document_id: int,
) -> float:
    """
    Compare the student method's segments to human-reviewed segments for document_id.
    Returns boundary F1 vs. human labels.
    """
    ...
```

Include `human_agreement` in the `DIDistillationResult.metrics` JSON.

### Re-distillation triggers "skip the teacher" threshold update

After re-distillation, if `human_agreement > DI_SKIP_TEACHER_THRESHOLD` (default 0.90),
update `DIMethodConfig("skip_teacher_threshold", str(new_threshold))` so future
documents with high-confidence student predictions skip the VLM call entirely.

The Celery task skeleton in `tasks.py` already has the structure for this:

```python
# At the start of method selection in process_document_task:
skip_teacher = False
if method_name == DIMethod.LLM_VLM:
    # Check if a cheaper method already ran with high confidence
    student_conf = _best_student_confidence(db, job_id)
    skip_threshold = float(_get_config(db, "skip_teacher_threshold", "0.90"))
    if student_conf >= skip_threshold:
        logger.info("Student confidence %.2f ≥ threshold %.2f — skipping teacher for job %d",
                    student_conf, skip_threshold, job_id)
        skip_teacher = True

if not skip_teacher and method_name == DIMethod.LLM_VLM:
    _run_async(run_llm_vlm_pipeline(...))
```

---

## Tests (mandatory)

Create `backend/document_intelligence/tests/test_phase7.py`.

Required tests:
- `patch_segment` with a changed `document_type` → `DIHumanCorrection` row created with
  `field_name="document_type"`, `original_value=original`, `corrected_value=new`.
- `patch_segment` with no change to a field → no correction row for that field.
- Accept suggestion → `DIHumanCorrection` row with `field_name="suggestion_tag"` and `corrected_value="accepted"`.
- `export_human_labels` → merges teacher base segments with correction list.
- `POST /redisill` with fewer corrections than `min_corrections` → `{"triggered": false}`.
- `POST /redisill` with enough corrections → calls distillation, returns report with `boundary_f1`.
- `DIMethodConfig` threshold is updated when `human_agreement > DI_SKIP_TEACHER_THRESHOLD`.
- Skip-teacher logic: student confidence above threshold → `llm_vlm` method skipped in Celery task.

---

## Acceptance checklist

- [ ] Every reviewer field-edit creates a `DIHumanCorrection` row.
- [ ] Every suggestion accept/reject creates a `DIHumanCorrection` row.
- [ ] `export_human_labels` includes corrections merged into the segment dict.
- [ ] `POST /redisill` runs distillation on the combined label set and returns a comparison report.
- [ ] `DIDistillationResult` shows measured change in `human_agreement` vs. prior run.
- [ ] `DIMethodConfig("skip_teacher_threshold")` is updated when agreement improves past the threshold.
- [ ] All tests pass.
