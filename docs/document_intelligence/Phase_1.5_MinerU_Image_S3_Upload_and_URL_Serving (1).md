# Phase 1.5 — MinerU Image S3 Upload & URL-Based Serving (depends on: Phase 1)

## Problem

MinerU runs as a Celery worker subprocess and writes extracted images to **local disk**:
```
{settings.files_dir}/{storage_path}/original/auto/images/*.png
```
The FastAPI server currently serves those images from the same local path via:
```
GET /{doc_id}/images/{image_path:path}   →  FileResponse from disk
```
When the Celery worker and the API server run on different containers (horizontal scaling, Docker Compose, Kubernetes), the API server cannot find images the worker wrote. All `![]()` image references in chunk content become broken.

## Goal

After MinerU finishes processing a PDF, upload all extracted images to S3. Change the existing image-serving endpoint to redirect to an S3 presigned URL instead of serving from disk. Chunk content, URL patterns, and the database schema do not change.

## Why This Approach Is Correct

The codebase already rewrites image paths to full API URLs in `_rewrite_image_urls()` (inside `backend/components/stand_alone_functions/page_find_logic/mineru_main_file_creator.py`):

```python
# Input:  ![](images/page_0_img_1.png)
# Output: ![](https://api.example.com/{doc_id}/images/page_0_img_1.png)
```

These URLs already go through the API endpoint (which does authorization). We only need to change what that endpoint returns — presigned S3 URL redirect instead of a local file. **No changes to chunk content, `_rewrite_image_urls`, or the database.**

> **Critical:** Do NOT store presigned URLs in chunk content — they expire (default 1 hour). Store the stable API URL (already done) and generate presigned URLs at request time.

## S3 Key Convention

```
docs/{storage_path}/images/{filename}
```

`storage_path` is already available in the Celery task: it equals `str(doc_id)` for unversioned documents or `{doc_id}/versions/{version_number}` for versioned ones. `doc.file_path` holds the same value after ingestion completes, making it derivable at serve time.

Examples:
- Unversioned: `docs/42/images/page_0_img_1.png`
- Versioned:   `docs/42/versions/2/images/page_0_img_1.png`

---

## Files to Modify

| File | Change |
|------|--------|
| `backend/storage/manager.py` | Add `upload_file_to_key()` internal method |
| `backend/core/celery/tasks.py` | Add `_upload_mineru_images_to_s3()` helper; call it in `mineru_process_pdf` |
| `backend/routs/documents.py` | Replace body of `GET /{doc_id}/images/{image_path:path}` with S3 presigned redirect |

No migrations. No new models. No schema changes.

---

## Change 1 — Add `upload_file_to_key` to `StorageManager`

**File:** `backend/storage/manager.py`

Add after `_validate_upload()`, before `create_upload_url()`:

```python
def upload_file_to_key(self, local_path: str | Path, key: str) -> None:
    """Internal use: upload a local file directly to S3 without creating a FileAsset."""
    self._ensure_bucket()
    self.client.upload_file(str(local_path), self.bucket, key)
```

This bypasses the `FileAsset` model — MinerU images are derived/internal assets, not user uploads.

---

## Change 2 — Upload Images After MinerU Runs

**File:** `backend/core/celery/tasks.py`

Add this helper function before `mineru_process_pdf`:

```python
def _upload_mineru_images_to_s3(doc_id: int, storage_path: str, owner_id: int | None) -> None:
    doc_dir = Path(settings.files_dir) / storage_path
    image_extensions = {".png", ".jpg", ".jpeg", ".webp", ".gif"}
    image_files = [
        p for p in doc_dir.rglob("*")
        if p.is_file() and p.suffix.lower() in image_extensions
    ]

    if not image_files:
        print(f"[S3 upload] No images found for doc {doc_id}, skipping", flush=True)
        return

    with db_session() as db:
        user_id = owner_id
        if user_id is None:
            doc = db.query(Document).filter(Document.id == doc_id).first()
            if doc:
                user_id = doc.owner_id

        user = db.query(User).filter(User.id == user_id).first() if user_id else None
        if not user:
            print(f"[S3 upload] No user found for doc {doc_id}, skipping image upload", flush=True)
            return

        manager = StorageManager(db)
        uploaded = 0
        for img_path in image_files:
            key = f"docs/{storage_path}/images/{img_path.name}"
            try:
                manager.upload_file_to_key(img_path, key)
                uploaded += 1
            except Exception as exc:
                print(f"[S3 upload] Failed to upload {img_path.name}: {exc}", flush=True)

        print(f"[S3 upload] Uploaded {uploaded}/{len(image_files)} images for doc {doc_id}", flush=True)
```

In `mineru_process_pdf`, insert the upload call between `run_mineru_on_file()` and `_activate_document_version()`:

```python
        run_mineru_on_file(
            pdf_path=pdf_path,
            doc_id=doc_id,
            document_version_id=document_version_id,
            storage_path=storage_path,
        )

        # NEW: upload MinerU-extracted images to S3 before activating the document
        _upload_mineru_images_to_s3(
            doc_id=doc_id,
            storage_path=storage_path,
            owner_id=owner_id,
        )

        _activate_document_version(doc_id, document_version_id)
```

Upload happens before `_activate_document_version()` so images are on S3 before the document status becomes `DONE` and clients can access it.

---

## Change 3 — Image Endpoint: Serve from S3

**File:** `backend/routs/documents.py`

Find `GET /{doc_id}/images/{image_path:path}`. Keep the function signature and the `_get_accessible_document` auth check. Replace everything after the auth check with:

```python
@router.get("/{doc_id}/images/{image_path:path}")
async def get_document_image(
    doc_id: int,
    image_path: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    doc = _get_accessible_document(db, doc_id, current_user, "read")

    # Reject path traversal — only bare filenames are valid
    filename = Path(image_path).name
    if not filename or filename != image_path.lstrip("/"):
        raise HTTPException(status_code=400, detail="Invalid image path")

    key = f"docs/{doc.file_path}/images/{filename}"

    manager = StorageManager(db)
    try:
        presigned_url = manager.presign_client.generate_presigned_url(
            ClientMethod="get_object",
            Params={"Bucket": manager.bucket, "Key": key},
            ExpiresIn=settings.S3_DOWNLOAD_EXPIRES_SECONDS,
        )
    except Exception as exc:
        raise HTTPException(status_code=404, detail="Image not found") from exc

    return RedirectResponse(url=presigned_url, status_code=302)
```

Add `from fastapi.responses import RedirectResponse` to the imports at the top of `documents.py` if not already present. Remove the old filesystem path construction and `FileResponse` return entirely.

---

## Edge Cases

| Case | Behavior |
|------|----------|
| MinerU disabled / pypdf fallback | Pypdf extracts no images → `image_files` is empty → helper returns early silently |
| No `owner_id` in task args | Helper falls back to `doc.owner_id` from DB |
| Image upload fails for one file | Logs error, continues uploading remaining files |
| Document not yet DONE when image requested | `_get_accessible_document` raises 404 (document not accessible until DONE) |
| Path traversal attempt in `image_path` | Rejected with HTTP 400 before S3 key is formed |
| Versioned document | `doc.file_path` is set to `storage_path` (e.g., `42/versions/2`), key matches upload key |

---

## Verification Steps

1. **Upload check:** Process a PDF with images. After Celery task completes, inspect S3 bucket for keys under `docs/{doc_id}/images/`. Expect one key per extracted image.

2. **Serve check:** Retrieve a chunk containing `![](.../{doc_id}/images/...)`. Request that URL with a valid auth token. Expect `302` redirect to an S3 presigned URL. Follow the redirect — should return the image binary with correct `Content-Type`.

3. **Auth check:** Request the same image URL as a user from a different company. Expect `403` or `404`.

4. **No-image PDF:** Process a text-only PDF. Celery task logs `"No images found for doc X, skipping"`. No errors.

5. **Path traversal:** Request `GET /{doc_id}/images/../../../etc/passwd`. Expect `400 Invalid image path`.

---

## Acceptance Checklist

- [ ] `StorageManager.upload_file_to_key()` added and unit-testable independently
- [ ] Celery task logs image upload count per document
- [ ] Image endpoint returns `302` redirect to presigned S3 URL (not `FileResponse`)
- [ ] Document is not marked `DONE` until images are uploaded to S3
- [ ] No changes to chunk content, `_rewrite_image_urls`, migrations, or the `FileAsset` model
