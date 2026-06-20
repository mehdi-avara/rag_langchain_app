# Phase 0 — Foundation
**Status: ~85 % complete. Several gaps must be closed before this phase is done.**

---

## Goal
The DI module, its tables, Pydantic schemas, API routes, and Celery task skeleton
exist and are fully wired to the project.  No heavy processing yet, but all
infrastructure is in place so later phases can add behaviour without touching
the scaffold.

---

## What is already implemented

| Item | Location | Notes |
|------|----------|-------|
| SQLAlchemy models (7 tables) | `backend/document_intelligence/models.py` | See gap I-2 below |
| Model registration for Alembic | `backend/Models/__init__.py` lines 62-70 | Done |
| Alembic migration | `backend/alembic/versions/46a0f80fa1aa_initial_schema.py` | All DI tables present |
| Pydantic schemas | `backend/document_intelligence/schemas.py` | Complete |
| API routes | `backend/document_intelligence/routes.py` | RBAC missing (gap I-3) |
| Router registration | `backend/api.py` line 96 | `app.include_router(di_router)` |
| Celery task skeleton | `backend/document_intelligence/tasks.py` | Wrong import (gap I-5) |

---

## Remaining gaps (must fix before phase is done)

### Gap 0-A — Add `document_split_outputs` table  *(inconsistency I-2)*

Add to `backend/document_intelligence/models.py`:

```python
class DocumentSplitOutput(Base):
    """Links a generated child PDF/document back to its parent segment."""
    __tablename__ = "document_split_outputs"

    id = Column(Integer, primary_key=True)
    parent_document_id = Column(
        Integer, ForeignKey("documents.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )
    segment_id = Column(
        Integer, ForeignKey("document_segments.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )
    child_document_id = Column(
        Integer, ForeignKey("documents.id", ondelete="SET NULL"),
        nullable=True, index=True,
    )
    # FileAsset id of the generated split PDF
    generated_asset_id = Column(
        Integer, ForeignKey("file_assets.id", ondelete="SET NULL"),
        nullable=True,
    )
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)

    parent_document = relationship("Document", foreign_keys=[parent_document_id])
    segment = relationship("DocumentSegment")
    child_document = relationship("Document", foreign_keys=[child_document_id])
    generated_asset = relationship("FileAsset", foreign_keys=[generated_asset_id])
```

Register in `backend/Models/__init__.py`:

```python
from document_intelligence.models import (
    ...
    DocumentSplitOutput,   # add this
)
```

And add to `__all__`.

Then generate and apply a new migration:
```
alembic revision --autogenerate -m "add document_split_outputs"
```

Review the generated file for FK ordering before running `alembic upgrade head`.

---

### Gap 0-B — Add `CANCELLED` job status  *(inconsistency I-1)*

In `backend/document_intelligence/models.py`, extend `DIJobStatus`:

```python
class DIJobStatus(str, enum.Enum):
    QUEUED    = "queued"
    RUNNING   = "running"
    COMPLETED = "completed"
    FAILED    = "failed"
    CANCELLED = "cancelled"   # add this
```

No migration needed (the column stores a plain `String`, not a PG enum type).

---

### Gap 0-C — Fix Celery task import  *(inconsistency I-5)*

In `backend/document_intelligence/tasks.py`, replace the try/except block at the top:

```python
# WRONG (no celery_app.py exists at root):
try:
    from celery_app import celery_app
except ImportError:
    celery_app = Celery(...)

# CORRECT:
from core.celery.celery_app import celery_app
```

Then add the DI task module to the shared worker's include list in
`backend/core/celery/celery_app.py`:

```python
celery_app = Celery(
    "porsa",
    broker=redis_url,
    include=[
        "core.celery.tasks",
        "document_intelligence.tasks",   # add this
    ],
)
```

---

### Gap 0-D — Add RBAC permissions to every route  *(inconsistency I-3)*

Project rule: every route must be protected with `require_permission(...)` and
the permission must be seeded in `seed_rbac.py`.

**Step 1 — seed the permissions.**

In `backend/db/seed_rbac.py`, add these strings to `permissions_data`:

```python
"document_intelligence:job_create",
"document_intelligence:job_read",
"document_intelligence:segment_read",
"document_intelligence:segment_review",
"document_intelligence:suggestion_review",
"document_intelligence:model_suggestion_review",
"document_intelligence:artifact_read",
"document_intelligence:label_export",
```

**Step 2 — import and apply in routes.**

In `backend/document_intelligence/routes.py`, import the dependency:

```python
from deps import require_permission
```

Then add the dependency to each endpoint:

```python
# Example — apply to all endpoints in the same pattern
@router.post("/jobs", ...)
def create_job(
    payload: JobCreate,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_permission("document_intelligence:job_create")),
):
    ...
```

Mapping of endpoint → permission string:

| Endpoint | Permission |
|----------|-----------|
| `POST /jobs` | `document_intelligence:job_create` |
| `GET /jobs` | `document_intelligence:job_read` |
| `GET /jobs/{job_id}` | `document_intelligence:job_read` |
| `GET /documents/{doc_id}/jobs` | `document_intelligence:job_read` |
| `GET /documents/{doc_id}/artifacts` | `document_intelligence:artifact_read` |
| `GET /documents/{doc_id}/segments` | `document_intelligence:segment_read` |
| `GET /segments/{segment_id}` | `document_intelligence:segment_read` |
| `PATCH /segments/{segment_id}` | `document_intelligence:segment_review` |
| `GET /segments/{segment_id}/suggestions` | `document_intelligence:segment_read` |
| `PATCH /suggestions/{suggestion_id}` | `document_intelligence:suggestion_review` |
| `GET /jobs/{job_id}/model-suggestions` | `document_intelligence:segment_read` |
| `PATCH /model-suggestions/{suggestion_id}` | `document_intelligence:model_suggestion_review` |
| `GET /jobs/{job_id}/export-labels` | `document_intelligence:label_export` |

---

### Gap 0-E — Replace bare `HTTPException` with catalogued errors  *(inconsistency I-4)*

**Step 1 — add DI error codes to `backend/core/exceptions/error_codes.py`.**

Find the `ErrorCode` enum and add:

```python
DI_JOB_NOT_FOUND          = "DI_JOB_NOT_FOUND"
DI_DOCUMENT_NOT_FOUND     = "DI_DOCUMENT_NOT_FOUND"
DI_SEGMENT_NOT_FOUND      = "DI_SEGMENT_NOT_FOUND"
DI_SUGGESTION_NOT_FOUND   = "DI_SUGGESTION_NOT_FOUND"
DI_DOCUMENT_NOT_PROCESSED = "DI_DOCUMENT_NOT_PROCESSED"
DI_INVALID_STATUS         = "DI_INVALID_STATUS"
```

Also add corresponding entries in the catalog dict (HTTP status + message) in the
same file, following the existing pattern.

**Step 2 — update routes.**

Replace `raise HTTPException(status_code=404, detail="...")` with
`raise AppException(ErrorCode.DI_JOB_NOT_FOUND)` etc., importing
`AppException` and `ErrorCode` from `core.exceptions`.

---

### Gap 0-F — Add a `POST /jobs/{job_id}/cancel` endpoint

The plan specified `cancelled` as a valid status.  Add a cancel endpoint:

```python
@router.post("/jobs/{job_id}/cancel", response_model=JobSummaryOut)
def cancel_job(
    job_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_permission("document_intelligence:job_create")),
):
    job = _get_job_or_404(db, job_id)
    if job.status not in (DIJobStatus.QUEUED, DIJobStatus.RUNNING):
        raise AppException(ErrorCode.DI_INVALID_STATUS)
    job.status = DIJobStatus.CANCELLED
    job.completed_at = datetime.utcnow()
    db.commit()
    db.refresh(job)
    return job
```

Celery tasks already running can't be killed from here; the status change is
informational and prevents the task from writing results if it checks before committing.

---

## Tests (mandatory — `AGENTS.md` rule 9)

Create `backend/document_intelligence/tests/test_phase0.py`.

Required test cases:
- `POST /jobs` without token → 401.
- `POST /jobs` with token but no `document_intelligence:job_create` permission → 403 `PERMISSION_DENIED`.
- `POST /jobs` with permission and a valid `document_id` → 201, job row in DB, status `queued`.
- `POST /jobs` with permission but unknown `document_id` → 404 `DI_DOCUMENT_NOT_FOUND`.
- `GET /jobs/{job_id}` with permission → 200, returns the job.
- `PATCH /suggestions/{id}` with status `"accepted"` → 200, status updated.
- `PATCH /suggestions/{id}` with status `"invalid"` → 422 `DI_INVALID_STATUS`.
- Job status cycle: `queued → running → completed` or `queued → cancelled`.
- Schema validation: `JobCreate` with an empty `methods_requested` → Pydantic 422.

Use `pytest` + `TestClient`.  Mock the Celery `delay` call so tests don't
need a running worker.

---

## Acceptance checklist

- [ ] `alembic check` passes (no model/DB drift).
- [ ] All 9 permission strings appear in `seed_rbac.py`.
- [ ] Every route returns 403 without the right permission; 200/201/202 with it.
- [ ] `POST /jobs` returns 201 (not 202 — the task is enqueued via `BackgroundTasks`; the 202 in the plan was approximate).
- [ ] Job row transitions through the expected statuses.
- [ ] `document_split_outputs` table exists in the DB.
- [ ] `document_intelligence.process_document` task is visible in Celery (`celery inspect registered`).
- [ ] All tests pass.
