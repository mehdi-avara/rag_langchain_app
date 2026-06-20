# Phase 4 — Cheaper Student Methods + Distillation
**Depends on: Phase 3**
**Status: Not started. The task skeleton skips any non-`llm_vlm` method with a warning.**

---

## Goal
Build two cheaper methods that reproduce the teacher's output without a GPU for
most future documents, then distill them against the teacher labels.

- **Method A — Image Processing:** detect document boundaries visually (page hash changes,
  layout shifts, logo/header patterns). No text needed.
- **Method B — Text + Embeddings:** semantic shift between adjacent pages, tag/model name
  detection, clustering into sections. Uses the same embedding model already in the project.
- **Distillation:** fit A and B to teacher labels; measure agreement; set a confidence
  threshold above which students run without calling the GPU teacher.

---

## P4.1 — Image Processing Method (Method A)

### Location
`backend/document_intelligence/services/image_method.py`

### Inputs
- `List[DocumentPageArtifact]` — the per-page artifacts from Phase 1.
  The artifacts carry `image_hash` (perceptual hash) and `image_density`,
  `text_density`, `layout_features` (JSON).

### Algorithm

```
For each adjacent pair (page_i, page_j):
  1. Perceptual hash distance:
       hamming_distance = bin(int(hash_i, 16) ^ int(hash_j, 16)).count("1")
       visual_similarity = 1 - (hamming_distance / hash_length_bits)
  2. Text density jump:
       td_ratio = abs(text_density_j - text_density_i) / (text_density_i + 1e-6)
  3. Image density jump (similar computation).
  4. Header similarity: extract first ~200 chars of each page's text;
       compare with difflib.SequenceMatcher ratio.
  5. Boundary score:
       score = w1 * (1 - visual_similarity) + w2 * td_ratio + w3 * (1 - header_sim)
       [weights w1=0.4, w2=0.3, w3=0.3 — tunable via env vars]
  6. If score > DI_IMAGE_BOUNDARY_THRESHOLD (default 0.55): mark as new_document.
```

### Output format

Return a `CanonicalMethodOutput` with the same schema as the teacher:

```python
from document_intelligence.schemas import (
    CanonicalMethodOutput, CanonicalSegmentPayload
)
from document_intelligence.models import DIMethod

def run_image_method(
    document_id: int,
    artifacts: list[DocumentPageArtifact],
) -> CanonicalMethodOutput:
    boundary_after_pages = _detect_boundaries(artifacts)
    page_ranges = _build_ranges(len(artifacts), boundary_after_pages)
    segments = [
        CanonicalSegmentPayload(
            start_page=s, end_page=e,
            document_type="unknown",
            confidence=_confidence_for_range(artifacts, s, e),
        )
        for s, e in page_ranges
    ]
    return CanonicalMethodOutput(
        document_id=document_id,
        method=DIMethod.IMAGE_PROCESSING,
        segments=segments,
    )
```

### Wiring into the Celery task

In `backend/document_intelligence/tasks.py`, inside the method loop:

```python
if method_name == DIMethod.IMAGE_PROCESSING:
    from document_intelligence.services.image_method import run_image_method
    canonical = run_image_method(document.id, artifacts)
    store_llm_predictions(db, job_id, document.id, canonical, method_run)
    method_run.status = "completed"
    method_run.completed_at = datetime.utcnow()
```

---

## P4.2 — Text + Embedding Method (Method B)

### Location
`backend/document_intelligence/services/embedding_method.py`

### Inputs
- `List[DocumentPageArtifact]` — `text` field per page.
- Access to the project's embedding service (`backend/components/embedding_service.py`).

### Algorithm

```
1. Embed each page's text using the project embedding service.
   (Batch the calls: DI_EMBEDDING_BATCH_SIZE pages per call, default 20.)

2. Semantic shift detection:
   For each adjacent pair (page_i, page_j):
     cosine_sim = dot(embed_i, embed_j) / (norm(embed_i) * norm(embed_j))
     if cosine_sim < DI_EMBED_BOUNDARY_THRESHOLD (default 0.70): boundary.

3. Tag / model name matching:
   For each segment [start..end]:
     candidate_text = " ".join(page texts in range).lower()
     For each SystemTag in the caller's company:
       if tag_name.lower() in candidate_text:
         add suggestion(type="tag", proposed_name=tag_name, confidence=0.8, evidence=...)
     For each ManagedModel in the caller's company:
       manufacturer_match = manufacturer.lower() in candidate_text
       model_match = model.lower() in candidate_text
       if manufacturer_match and model_match:
         add suggestion(type="managed_model", target_id=model.id, confidence=0.85)
       elif model_match:
         add suggestion(type="managed_model", target_id=model.id, confidence=0.6)

4. Return CanonicalMethodOutput(method="text_embedding", ...).
```

### Important: company scoping

Tags and models are company-scoped.  The embedding method must receive the
`company_id` of the user who triggered the job:

```python
def run_embedding_method(
    document_id: int,
    artifacts: list[DocumentPageArtifact],
    db: Session,
    company_id: int,            # from job.triggered_by.company_id
) -> CanonicalMethodOutput:
    ...
```

In `tasks.py`, load the user to get `company_id`:

```python
user = db.query(User).get(job.triggered_by_user_id)
company_id = user.company_id if user else None
```

### Wiring into the Celery task

```python
if method_name == DIMethod.TEXT_EMBEDDING:
    from document_intelligence.services.embedding_method import run_embedding_method
    canonical = run_embedding_method(document.id, artifacts, db, company_id)
    store_llm_predictions(db, job_id, document.id, canonical, method_run)
    method_run.status = "completed"
    method_run.completed_at = datetime.utcnow()
```

---

## P4.3 — Distillation + threshold calibration

### Location
`backend/document_intelligence/services/distillation.py`

### Input
Teacher labels from Phase 3 (`export_teacher_labels(db, job_id)` — a list of
labeled segment dicts).  Each row:
```json
{
  "document_id": 42,
  "start_page": 1,
  "end_page": 15,
  "document_type": "manual",
  "tags": ["pump", "centrifugal"],
  "source": "teacher"
}
```

### What distillation does

For **image method** (boundary detection):
- Compare image method's predicted boundaries to teacher's.
- Compute precision, recall, F1 on page-level boundary positions.
- Fit a threshold on the image method's `boundary_score` that maximises F1 on
  the labeled set.  Store as `DI_IMAGE_BOUNDARY_THRESHOLD` in a config table.

For **embedding method** (boundary detection + classification):
- Compare embedding method's cosine-similarity breakpoints to teacher's.
- Compute boundary F1.
- For classification: compute per-class accuracy (document_type, tag presence).
- Fit the `DI_EMBED_BOUNDARY_THRESHOLD` similarly.

### Storage

Add a `DIDistillationResult` table (new migration):

```python
class DIDistillationResult(Base):
    __tablename__ = "di_distillation_results"

    id = Column(Integer, primary_key=True)
    method = Column(String, nullable=False)         # "image_processing" | "text_embedding"
    run_date = Column(DateTime, nullable=False, default=datetime.utcnow)
    n_labeled_segments = Column(Integer, nullable=False)
    boundary_precision = Column(Float, nullable=True)
    boundary_recall = Column(Float, nullable=True)
    boundary_f1 = Column(Float, nullable=True)
    classification_accuracy = Column(Float, nullable=True)
    recommended_threshold = Column(Float, nullable=True)
    # JSON with full metrics breakdown
    metrics = Column(JSON, nullable=True)
```

Register in `Models/__init__.py` and generate a migration.

### Threshold config table

```python
class DIMethodConfig(Base):
    __tablename__ = "di_method_configs"
    __table_args__ = (UniqueConstraint("config_key"),)

    id = Column(Integer, primary_key=True)
    config_key = Column(String, nullable=False)   # e.g. "image_boundary_threshold"
    config_value = Column(String, nullable=False)  # serialized as string
    updated_at = Column(DateTime, nullable=False, default=datetime.utcnow)
```

After each distillation run, update the config:
```python
db.merge(DIMethodConfig(
    config_key="image_boundary_threshold",
    config_value=str(best_threshold),
))
```

Both methods read their threshold at startup from this table (falling back to
the env-var default if the table has no entry).

### Management endpoint

Add to `routes.py`:
```
POST /document-intelligence/distill
     body: { job_ids: [int] }   # teacher-labeled jobs to use as training set
     returns: { image: {...metrics}, embedding: {...metrics} }
     permission: document_intelligence:distill
```

---

## Tests (mandatory)

Create `backend/document_intelligence/tests/test_phase4.py`.

Required tests:
- Image method on a 3-page artifact list where page 2 has a very different hash →
  boundary detected between pages 2 and 3.
- Image method on 3 identical pages → no boundary (single segment).
- Embedding method: mock the embedding service to return vectors; two groups of
  pages with low cosine similarity between groups → boundary detected.
- Embedding method: page text contains a known tag name →
  `tag` suggestion returned in canonical output.
- Embedding method: page text contains known manufacturer + model name →
  `managed_model` suggestion with `target_id` returned.
- Distillation: given synthetic teacher labels and image-method output, produces
  a `DIDistillationResult` row and a `DIMethodConfig` row with the fitted threshold.
- Company scoping: embedding method run with `company_id=1` does NOT return tags
  belonging to `company_id=2`.

---

## Acceptance checklist

- [ ] `DIMethod.IMAGE_PROCESSING` and `DIMethod.TEXT_EMBEDDING` produce `DocumentSegment` rows.
- [ ] Distillation script runs from `POST /distill` with a list of teacher-labeled job IDs.
- [ ] `DIDistillationResult` row written after each distillation.
- [ ] `DIMethodConfig` row with the fitted threshold updated after distillation.
- [ ] Agreement metrics (boundary F1, classification accuracy) are non-zero on the eval set.
- [ ] The doc says which threshold drives GPU-free execution (e.g., "above 0.82 F1, skip teacher").
- [ ] All tests pass.
