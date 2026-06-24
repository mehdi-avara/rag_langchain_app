# Plan — Persist MinerU Output to S3 + Show Images With Chunks

## Summary
Two coupled problems, fixed together because they share the same root cause (MinerU
artifacts live only on a single worker's local disk):

1. **S3 persistence.** The MinerU pipeline downloads the original PDF from S3, runs
   MinerU into a **local** directory, saves text chunks to Postgres, and stops. The
   derived artifacts (`_middle.json`, per-page markdown, and the extracted figure
   `images/`) are **never uploaded to object storage**. If the worker's disk is lost,
   or a second worker/box serves a request, those artifacts are gone.
2. **Images with chunks.** When a chunk is displayed, its figures should display too.
   Today a chunk's image references are only markdown URLs baked into the chunk text,
   pointing at a route that reads local disk. The `image_chunks` table that should hold
   this association exists but is never written.

The plan pushes all MinerU artifacts to S3 at ingestion time, persists a real
chunk↔image link (S3-keyed), serves images from S3, and backfills existing documents.
The DI module's `mineru_source` reader is extended to read `_middle.json` from S3 so
nothing depends on local disk.

> Repo rules still apply (`AGENTS.md` / `docs/KEEP_IN_MIND.md`): Alembic owns the schema,
> register new models in `backend/Models/__init__.py`, routes are permission-protected
> and seeded, heavy work runs in Celery, catalogued errors only, backward compatibility
> is mandatory, tests are required.

---

## Current state (grounded in code)

| Artifact | Where it lives today | Reachable across boxes? |
|---|---|---|
| Original PDF (`FileAsset`) | **S3** — `companies/{company_id}/assets/{asset_id}/original` | Yes |
| `original.pdf` working copy | Local disk — `files_dir/{file_path}/original.pdf` | No |
| MinerU `_middle.json` | Local disk — `files_dir/{file_path}/original/auto/*_middle.json` | No |
| Per-page markdown | Local disk — same `auto/` dir | No |
| Extracted figures (`images/`) | Local disk — `files_dir/{file_path}/original/auto/images/` | No |
| Text chunks + embeddings (`chunks`) | **Postgres** | Yes |
| Chunk→image link (`image_chunks`) | Table exists, **never populated** | n/a |

Key code touchpoints:
- `core/celery/tasks.py::mineru_process_pdf` — downloads PDF from S3, calls `run_mineru_on_file`.
- `core/simple_ingestion.py::run_mineru_on_file` / `process_pdf_with_mineru` — runs MinerU into local `doc_dir`, parses `_middle.json`, saves chunks. No S3 upload of outputs.
- `core/chunking.py::chunk_text` → `build_dual_mode_chunks_from_pdf_info` — builds chunk text; image refs become markdown `![](.../{doc_id}/images/{file})`.
- `routs/documents.py::get_document_image` (`GET /{doc_id}/images/{path}`) — serves a figure from **local** `auto/images/`.
- `Models/image_chunk.py::ImageChunk` (`chunk_id, image_data, caption, position`) — defined, related to `Chunk.image_data`, **unused**.
- `schemas/document.py::ChunkOut` — returns text fields only; no images.
- `storage/manager.py::StorageManager` — has `create_upload_url`, `complete_upload`, `download_asset_to_path`; **no helper to upload a server-side file** to S3.

---

## Goals / Non-goals

**Goals**
- Every MinerU-derived artifact is durably stored in S3 after ingestion.
- A chunk's figures are persisted as a real association and returned by the chunk APIs.
- Image serving resolves from S3 (with a local fallback during migration).
- Existing documents are backfilled, not orphaned.
- DI's `mineru_source` can read `_middle.json` from S3, removing its local-disk assumption.

**Non-goals**
- Changing MinerU itself or the chunking algorithm.
- Re-OCR / re-embedding existing documents (text is already in Postgres).
- Moving the `files_dir` working area off local disk (it stays as scratch during processing).

---

## Design decisions

### D1 — S3 key layout for derived artifacts
Store derived artifacts next to the source asset, under a parallel prefix so access
control and lifecycle mirror the original:

```
companies/{company_id}/assets/{asset_id}/original                # existing: source PDF
companies/{company_id}/assets/{asset_id}/mineru/middle.json      # NEW
companies/{company_id}/assets/{asset_id}/mineru/full.md          # NEW
companies/{company_id}/assets/{asset_id}/mineru/images/<name>    # NEW (one per figure)
```

Keying off `asset_id` (not `doc_id`) keeps versions isolated — each `DocumentVersion`
has its own `asset_id`, so re-uploads don't clobber a prior version's images.

### D2 — Upload helper on StorageManager
Add `StorageManager.upload_path(...)` and `upload_bytes(...)` (server-side `put_object`,
no presign) plus a `derived_key(asset, suffix)` helper. This is the single chokepoint for
writing derived data and keeps `boto3` out of the ingestion code.

### D3 — Chunk↔image association: populate `image_chunks` with S3 keys
Repurpose the dead `image_chunks` table. Recommended column changes (one Alembic
migration, additive):
- keep `chunk_id`, `caption`, `position`;
- replace the unused `image_data: Text` with `storage_key: String` (S3 object key),
  `page_num: Integer`, and nullable `bbox: JSON` (MinerU block bbox);
- add an index on `chunk_id`.

During ingestion, when a chunk's source blocks include figure spans, write one
`ImageChunk` row per figure with its S3 `storage_key`. This makes "show the chunk's
images" a simple join instead of regex-parsing markdown.

> Alternative considered: promote each figure to its own `FileAsset` (gets presigned
> URLs + company access for free). Heavier (one asset row per figure); deferred unless
> figures need independent ACLs. `image_chunks` + a serving route is sufficient.

### D4 — Serving: S3 with local fallback
Update `GET /{doc_id}/images/{path}` to stream the object from S3 when present, falling
back to local disk if not yet migrated. `ChunkOut` gains an `images: [{url, caption,
page_num}]` field; `url` points at this same route (stable, access-controlled) rather
than a short-lived presigned URL embedded in stored text.

### D5 — Backward compatibility
- New columns/fields are additive and nullable; old chunk markdown URLs keep resolving
  via the local fallback until backfill completes.
- The opt-in DI flag and the existing upload flow are untouched.

---

## Phases

### Phase 1 — Upload MinerU artifacts to S3 at ingestion
- **P1.1** Add `upload_path`, `upload_bytes`, and `derived_key(asset, suffix)` to
  `StorageManager`. *Acceptance:* unit test round-trips a local file to S3 and back.
- **P1.2** In `run_mineru_on_file` (after MinerU succeeds and `_middle.json` is parsed),
  upload `_middle.json`, the full markdown, and every file under `auto/images/` to the
  `mineru/` prefix (D1). Record the `middle.json` key on the `DocumentVersion`/`Document`
  (new nullable column `mineru_prefix` or `mineru_middle_key`). *Acceptance:* after a real
  ingest, the three artifact types exist in S3 under the asset's `mineru/` prefix.
- **P1.3** Make the upload non-fatal: an S3 upload failure logs a catalogued error but does
  not fail the chunk-saving that already succeeded. *Acceptance:* simulated S3 outage still
  completes text ingestion; artifacts retried on re-run.

### Phase 2 — Persist chunk↔image links
- **P2.1** Alembic migration to reshape `image_chunks` (D3); register/confirm in
  `Models/__init__.py`. *Acceptance:* `alembic check` clean; existing rows (none today) unaffected.
- **P2.2** In the chunk builder (`core/chunking.py` / `simple_ingestion.save_text_chunks` /
  `ingest_processed_middle_json`), collect figure spans per chunk and write `ImageChunk`
  rows with the S3 `storage_key`, `page_num`, `caption`, `bbox`. *Acceptance:* a PDF with
  figures yields `image_chunks` rows linked to the right chunks and S3 keys.

### Phase 3 — Serve images from S3 + return them with chunks
- **P3.1** Update `get_document_image` to stream from S3 (local fallback). *Acceptance:*
  a migrated doc serves its figure with the local copy deleted.
- **P3.2** Extend `ChunkOut` with `images: List[ChunkImageOut]` and populate it in
  `get_chunk` / `GET /{doc_id}/chunks`. *Acceptance:* the chunk endpoints return image URLs;
  a chunk with no figures returns `[]`.

### Phase 4 — Backfill existing documents
- **P4.1** A management Celery task `backfill_mineru_to_s3(doc_id|all)` that, for documents
  whose `auto/` dir exists locally, uploads artifacts (Phase 1) and creates `image_chunks`
  rows (Phase 2) without re-running MinerU. For documents with no local artifacts, re-run
  MinerU from the S3 original. *Acceptance:* a previously-ingested doc gains S3 artifacts and
  chunk-image links; idempotent on re-run.

### Phase 5 — Point DI at S3
- **P5.1** Extend `document_intelligence/services/mineru_source.py` to fetch `_middle.json`
  from the asset's `mineru/` prefix when the local file is absent (it already falls back to
  the `chunks` table). *Acceptance:* DI builds artifacts on a worker with no local copy of the
  doc, reading `_middle.json` from S3.

### Phase 6 — Tests + cleanup
- **P6.1** Tests: S3 upload helper; ingestion writes artifacts + image links; image route S3
  path; `ChunkOut.images` payload; backfill idempotency; DI S3 read. *Acceptance:* suite green.
- **P6.2** Remove the now-obsolete local-only assumptions / dead `image_data` column usage;
  document the `mineru/` layout in `docs/KEEP_IN_MIND.md`. *Acceptance:* no references to the
  dropped column remain.

---

## Risks & mitigations
- **Duplicate storage / cost.** Figures also stay on local scratch. Mitigate by treating
  `files_dir` as ephemeral and optionally pruning `auto/` after successful S3 upload.
- **Presigned-URL churn in stored text.** Avoided by serving via the stable
  `/{doc_id}/images/{path}` route instead of baking presigned URLs into chunk content.
- **Version collisions.** Keying derived artifacts by `asset_id` (not `doc_id`) isolates
  versions.
- **Partial migration.** Local fallback in the image route keeps un-backfilled docs working.

## Open questions
1. Promote figures to first-class `FileAsset`s (independent ACL/lifecycle) or keep them as
   `image_chunks` rows referencing raw S3 keys? (Plan assumes the latter.)
2. After successful S3 upload, delete the local `auto/` working copy, or keep it as a hot
   cache for serving? (Affects disk usage vs. latency.)
3. Should backfill re-run MinerU for docs missing local artifacts, or only migrate what
   exists locally and leave the rest text-only?
```
