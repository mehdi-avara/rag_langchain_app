# Document Intelligence — Phase Map & Inconsistencies

## What this folder is
Each file in this folder is a **self-contained implementation guide for one phase**.
A developer can deliver an entire phase using only the phase file and the codebase —
no other documentation is required.

---

## Phase dependency map

```
Phase 0 ─── Foundation (no deps)
    │
    ├── Phase 1 ─── PDF Pipeline
    │       │
    │       └──── Phase 2 ─── GPU Infrastructure
    │                   │
    │             Phase 3 ─── Teacher VLM  (needs 1 AND 2)
    │                   │
    │             Phase 4 ─── Student Methods  (needs 3)
    │                   │
    │             Phase 5 ─── Merge & Scoring  (needs 4)
    │                   │
    │             Phase 8 ─── Evaluation  (needs 5 AND 7) ─── Final deliverable
    │
    └── Phase 6 ─── Review / Accept  (needs 0 AND 3)
            │
        Phase 7 ─── Feedback Loop  (needs 4 AND 6)
                │
            (feeds back into Phase 4 re-distillation)

Phase 9 ─── Security (optional, no hard dependency)
```

### File → phase index

| File | Depends on |
|------|-----------|
| `Phase_0_Foundation.md` | — |
| `Phase_1_PDF_Pipeline (0).md` | Phase 0 |
| `Phase_2_GPU_Infrastructure (0).md` | Phase 0 |
| `Phase_3_Teacher_VLM (1,2).md` | Phase 1 **and** Phase 2 |
| `Phase_4_Student_Methods (3).md` | Phase 3 |
| `Phase_5_Merge_Scoring (4).md` | Phase 4 |
| `Phase_6_Review_Accept (0,3).md` | Phase 0 **and** Phase 3 |
| `Phase_7_Feedback_Loop (4,6).md` | Phase 4 **and** Phase 6 |
| `Phase_8_Evaluation (5,7).md` | Phase 5 **and** Phase 7 |
| `Phase_9_Security.md` | optional |

---

## Parallelism

Phases 1 and 2 can be worked **in parallel** after Phase 0 ships.
Phase 6 (read API) can be started after Phase 0; only P6.2 (auto-apply) needs Phase 3.
Phases 3–5 and Phase 7 form a sequential chain.

---

## Known inconsistencies between the plan and the current implementation

Read these before touching any DI code.

### I-1 · `DIJobStatus.CANCELLED` is missing
`backend/document_intelligence/models.py` defines `DIJobStatus` with only
`QUEUED | RUNNING | COMPLETED | FAILED`.  The original plan specifies a fifth
value `cancelled`.  Add it before Phase 6 ships a cancel endpoint.

### I-2 · `document_split_outputs` table never created
Phase 0 P0.1 listed five tables; only four were implemented and registered.
`document_split_outputs` (parent doc id, segment id, child doc id, generated PDF
asset id) is missing from `models.py`, from `Models/__init__.py`, and from the
Alembic migration.  Phase 6 P6.3 (child PDF split) depends on this table.
Add it in a new migration **before** implementing P6.3.

### I-3 · RBAC guards not applied to any DI route
Phase 0 P0.3 requires `require_permission("document_intelligence:<action>")` on
every route and the permission strings seeded in `backend/db/seed_rbac.py`.
Neither has been done.  All DI endpoints currently enforce only authentication
(bearer token), not authorization.  This violates project rule 4 in `AGENTS.md`.
Fix this as part of completing Phase 0 before any other phase ships.

### I-4 · Catalogued errors not used
All routes in `backend/document_intelligence/routes.py` raise bare
`HTTPException(status_code=404, ...)` instead of the project's catalogued
`AppException` from `core/exceptions/error_codes.py`.  Project rules require
only catalogued codes.  New DI error codes (`DI_JOB_NOT_FOUND`,
`DI_DOCUMENT_NOT_FOUND`, `DI_SEGMENT_NOT_FOUND`, `DI_SUGGESTION_NOT_FOUND`,
`DI_DOCUMENT_NOT_PROCESSED`) must be added to `core/exceptions/error_codes.py`
and raised consistently.

### I-5 · Celery task is not registered in the shared worker
`backend/document_intelligence/tasks.py` tries
`from celery_app import celery_app` but no `celery_app.py` exists at the
Python root.  The shared app lives at `core/celery/celery_app.py` and is
imported as `from core.celery.celery_app import celery_app`.
Additionally, the shared Celery worker's `include` list is
`["core.celery.tasks"]` — `document_intelligence.tasks` is not in it, so
the worker never registers `document_intelligence.process_document`.
Two fixes needed:
1. Fix the import in `tasks.py` to use `from core.celery.celery_app import celery_app`.
2. Add `"document_intelligence.tasks"` to the `include` list in
   `backend/core/celery/celery_app.py`.

### I-6 · Object storage not used — local filesystem only
The plan specifies all DI artifacts and results live in `StorageManager`
(bucket `porsa-assets`) under `documents/<doc_id>/di/...`.  The current
`pdf_artifacts.py` writes everything to the **local filesystem** under
`<settings.files_dir>/<document.file_path>/di_artifacts/`.  This will break
in any deployment where the app and Celery workers share no NFS/volume, and
it does not mirror the MinerU layout.  Phase 1 P1.4 must introduce a storage
key builder and migrate writes to `StorageManager`.

### I-7 · MinerU text reuse not implemented
Phase 1 P1.1 says to read the MinerU `_middle.json` first and reuse its
per-page text.  `pdf_artifacts.py` goes directly to `pdfminer.six` without
checking MinerU output.  This means DI re-extracts text that MinerU already
produced, wasting CPU and potentially producing different text from the search
index.

### I-8 · `pages.jsonl` not written
Phase 1 P1.3 requires `di/artifacts/pages.jsonl` — one line per page containing
`{page_num, text_storage_key, image_storage_key, text_hash}`.  This file is how
later phases (teacher, student, merge) locate artifacts without a DB query.
It is not written.

### I-9 · Phase 3 implemented before Phase 2
The VLM pipeline (`llm_vlm_method.py`) was written and wired into the Celery task
before the GPU fleet manager (Phase 2) exists.  This is valid for local/dev runs
(the `openai_base_url` points to a local model), but the batch dispatcher,
checkpoint resume, and per-batch raw response storage that Phase 2 defines are
missing.  Phase 3 P3.1 must be retrofitted to go through the Phase 2 dispatcher
once that ships.

### I-10 · Raw VLM responses not persisted
Phase 3 P3.1 requires raw JSON from each VLM call saved to
`di/teacher/raw_responses/seg-<id>.json` in object storage for audit and replay.
Nothing is saved today.

### I-11 · Result JSON files not written to object storage
Phase 3 P3.2 requires `di/results/segments.json`, `suggestions.json`, and
`metadata.json` in object storage with MinerU-compatible identifiers.  Not written.

### I-12 · Auto-apply on suggestion accept not implemented
Phase 6 P6.2 says accepting a `DocumentSegmentSuggestion` of type `tag` should
create a `TagDocumentLink` row; type `managed_model` should create a
`ModelDocumentLink` row; type `managed_model` with no `target_id` should first
create a `ManagedModel` then link it.  The current `PATCH /suggestions/{id}`
only sets `status = "accepted"` on the suggestion row; it writes nothing into
the main CMMS tables.

### I-13 · `Document.file_path` is nullable — crash risk
`pdf_artifacts.py` line builds `Path(settings.files_dir) / document.file_path`.
If `file_path` is `None` (the column is nullable in `documents`), Python raises
`TypeError`.  A guard must be added, raising a catalogued error
(`DI_DOCUMENT_NOT_PROCESSED`) before attempting path operations.

### I-14 · No tests exist for any DI code
All DI routes, services, and tasks are untested.  Project rules require tests
before any phase is considered done.  Each phase file lists its mandatory tests.
