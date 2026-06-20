# Phase 5 — Result Merging + Scoring
**Depends on: Phase 4**
**Status: Not started.**

---

## Goal
Combine predictions from all three methods (image, embedding, teacher VLM) into
one set of **non-overlapping segments** with a **calibrated confidence score** per
segment.  The merged result is what the reviewer sees in Phase 6.

---

## P5.1 — Normalize and merge

### Location
`backend/document_intelligence/services/merge.py`

### Inputs
- `job_id: int` — a completed DI job that may have multiple `DocumentMethodRun` rows
  (one per method), each with its own `DocumentSegment` rows in the DB.
- `n_pages: int` — total page count.

### Algorithm

Three methods may each predict different page ranges.  The merge must produce:
1. A set of non-overlapping segments that covers all pages exactly once.
2. Each merged segment records which methods agreed.

**Step 1 — collect all segment predictions**

```python
from document_intelligence.models import DocumentSegment, DocumentMethodRun, DISegmentStatus

def load_method_segments(db, job_id: int) -> dict[str, list[DocumentSegment]]:
    """Return {method_name: [segments ordered by start_page]}."""
    runs = db.query(DocumentMethodRun).filter(
        DocumentMethodRun.job_id == job_id,
        DocumentMethodRun.status == "completed",
    ).all()

    result = {}
    for run in runs:
        segs = (
            db.query(DocumentSegment)
            .filter(
                DocumentSegment.job_id == job_id,
                DocumentSegment.method == run.method,
            )
            .order_by(DocumentSegment.start_page)
            .all()
        )
        result[run.method] = segs
    return result
```

**Step 2 — collect boundary votes**

Convert each method's segments to a set of "boundary after page N" votes:

```python
def segments_to_boundaries(segments: list) -> set[int]:
    """Return the set of pages after which a new segment starts."""
    return {seg.start_page - 1 for seg in segments if seg.start_page > 1}

def count_boundary_votes(
    method_segments: dict[str, list],
) -> dict[int, int]:
    """Count how many methods voted for a boundary after each page."""
    votes: dict[int, int] = {}
    for segs in method_segments.values():
        for b in segments_to_boundaries(segs):
            votes[b] = votes.get(b, 0) + 1
    return votes
```

**Step 3 — apply majority threshold**

```python
DI_MERGE_MIN_VOTES = int(os.getenv("DI_MERGE_MIN_VOTES", "1"))

def apply_threshold(
    vote_counts: dict[int, int],
    min_votes: int,
) -> set[int]:
    return {page for page, count in vote_counts.items() if count >= min_votes}
```

With one method: any boundary is accepted (`min_votes=1`).
With two methods: a boundary needs 1 vote to appear (still `min_votes=1`).
With three methods: you can require 2+ for high confidence (`min_votes=2`).

**Step 4 — build merged page ranges**

```python
def boundaries_to_ranges(boundary_after: set[int], n_pages: int) -> list[tuple[int, int]]:
    """Convert boundary set to sorted (start_page, end_page) list (1-based)."""
    sorted_boundaries = sorted(boundary_after)
    ranges = []
    start = 1
    for b in sorted_boundaries:
        if 1 <= b < n_pages:
            ranges.append((start, b))
            start = b + 1
    ranges.append((start, n_pages))
    return [(s, e) for s, e in ranges if s <= e]
```

**Step 5 — create merged `DocumentSegment` rows with method `"fusion"`**

```python
from document_intelligence.models import DIMethod, DISegmentStatus

def create_merged_segments(
    db, job_id: int, document_id: int,
    ranges: list[tuple[int, int]],
    vote_counts: dict[int, int],
) -> list[DocumentSegment]:
    created = []
    for start, end in ranges:
        votes_for_start = vote_counts.get(start - 1, 0)
        seg = DocumentSegment(
            job_id=job_id,
            document_id=document_id,
            method=DIMethod.FUSION,
            start_page=start,
            end_page=end,
            status=DISegmentStatus.PREDICTED,
            evidence=[{"page": start, "kind": "merge", "value": f"{votes_for_start} method(s) agreed"}],
        )
        db.add(seg)
        created.append(seg)
    db.flush()
    return created
```

### Merge API endpoint

Add to `routes.py`:
```
POST /document-intelligence/jobs/{job_id}/merge
     permission: document_intelligence:job_create
     body: { min_votes: int = 1 }
     returns: List[SegmentOut]   # the newly created fusion segments
```

The endpoint calls the merge service, creates fusion `DocumentSegment` rows,
and returns them.

---

## P5.2 — Confidence scoring

### Location
`backend/document_intelligence/services/confidence.py`

### Per-segment confidence score

For each merged segment, blend:
1. **Method agreement:** `method_agreement = votes / n_methods_run`
2. **Per-method confidence:** average of each contributing method's own confidence
   on the overlapping page range.
3. **Teacher weight:** if the teacher (VLM) agreed, apply a multiplier (teacher is
   the ground truth, so its vote counts more).

```python
DI_TEACHER_WEIGHT = float(os.getenv("DI_TEACHER_WEIGHT", "1.5"))

def compute_merged_confidence(
    start_page: int,
    end_page: int,
    method_segments: dict[str, list[DocumentSegment]],
    n_methods: int,
) -> float:
    """Compute a blended 0-1 confidence for a merged segment."""
    from document_intelligence.models import DIMethod

    contributing_confidences = []
    methods_that_agreed = 0

    for method, segs in method_segments.items():
        # Find the segment from this method that overlaps [start_page, end_page]
        overlap = [
            s for s in segs
            if s.start_page <= end_page and s.end_page >= start_page
        ]
        if overlap:
            methods_that_agreed += 1
            best = max(overlap, key=lambda s: s.confidence or 0.0)
            conf = (best.confidence or 0.5)
            # Teacher gets extra weight
            if method == DIMethod.LLM_VLM:
                conf = min(1.0, conf * DI_TEACHER_WEIGHT)
            contributing_confidences.append(conf)

    agreement_score = methods_that_agreed / max(n_methods, 1)
    avg_method_conf = sum(contributing_confidences) / len(contributing_confidences) if contributing_confidences else 0.5

    # Blend: 40% agreement, 60% per-method confidence
    return round(0.4 * agreement_score + 0.6 * avg_method_conf, 4)
```

### Apply scores to merged segments

After creating merged segments (P5.1), update their confidence:

```python
for seg in merged_segments:
    seg.confidence = compute_merged_confidence(
        seg.start_page, seg.end_page, method_segments, len(method_segments)
    )
db.commit()
```

### Threshold for review queue ordering

The reviewer's queue (Phase 6) should display segments sorted by confidence
descending (high-confidence results reviewed first for quick bulk-accept).
The `GET /documents/{doc_id}/segments` endpoint already supports ordering —
add `?order_by=confidence_desc` query param.

---

## Tests (mandatory)

Create `backend/document_intelligence/tests/test_phase5.py`.

Required tests:
- `segments_to_boundaries`: segments `[(1,5), (6,10)]` → boundaries `{5}`.
- `count_boundary_votes`: two methods both voting boundary at page 5 → `{5: 2}`.
- `apply_threshold` with `min_votes=2` on `{5:2, 8:1}` → `{5}` only.
- `boundaries_to_ranges` with `{5}` and `n_pages=10` → `[(1,5), (6,10)]`.
- Fully overlapping methods → merged result = same as either method's segments.
- Three methods disagree on boundary positions → merged result uses only the page(s) with ≥ `min_votes` votes.
- `compute_merged_confidence`: teacher confidence 0.9 + student confidence 0.7 + 2/3 method agreement → result is in `[0.7, 1.0]`.
- `POST /jobs/{id}/merge` → creates `DocumentSegment` rows with `method="fusion"`.
- Merged segments are non-overlapping and cover all pages exactly once.

---

## Acceptance checklist

- [ ] `POST /jobs/{id}/merge` produces exactly one `DocumentSegment` per non-overlapping page range.
- [ ] Merged segments cover all pages (no gap, no overlap).
- [ ] Each merged segment has a non-null `confidence` between 0.0 and 1.0.
- [ ] Higher method agreement produces higher confidence.
- [ ] Teacher agreement boosts confidence relative to students-only.
- [ ] `GET /documents/{id}/segments?order_by=confidence_desc` returns segments in correct order.
- [ ] All tests pass.
