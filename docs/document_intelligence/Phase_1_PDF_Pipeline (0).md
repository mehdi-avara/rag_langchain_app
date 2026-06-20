# Phase 1 — PDF Page Pipeline + PDF→Text + Object-Storage Mirroring
**Depends on: Phase 0**
**Status: ~70 % complete. Core text + image extraction works. Object-storage integration and MinerU reuse missing.**

---

## Goal
For every document fed into the DI module, produce:
- Per-page **text** (MinerU first, pdfminer fallback, OCR last resort).
- Per-page **rendered PNG images** (full-res + thumbnail).
- A **`pages.jsonl`** index file in object storage.
- A `DocumentPageArtifact` row per page in the database.

Everything lives under the `di/artifacts/` prefix in object storage, mirroring
the MinerU layout so results can be joined on `(document_id, page_num)` with no
special-casing.

---

## What is already implemented

| Item | Location | Notes |
|------|----------|-------|
| pdfminer text extraction | `services/pdf_artifacts.py:55-71` | Per-page plain text |
| OCR fallback (pytesseract) | `services/pdf_artifacts.py:74-85` | Runs only when pdfminer produces empty text |
| pdf2image rendering | `services/pdf_artifacts.py:92-99` | Full-res PNG + thumbnail |
| Perceptual hash | `services/pdf_artifacts.py:102-109` | Used to detect unchanged pages |
| `DocumentPageArtifact` row creation | `services/pdf_artifacts.py:127-269` | Cached; re-run is no-op unless `force=True` |
| Task integration | `tasks.py:125-134` | `process_page_artifacts` called before methods |

---

## Remaining gaps

### Gap 1-A — Guard against `Document.file_path` being `None`  *(inconsistency I-13)*

`Document.file_path` is nullable.  If it is `None`, `Path(settings.files_dir) / None`
raises `TypeError`.

In `backend/document_intelligence/services/pdf_artifacts.py`,
replace the `_original_pdf_path` helper:

```python
from core.exceptions.error_codes import ErrorCode
from core.exceptions.app_exception import AppException

def _original_pdf_path(document: Document) -> Path:
    if not document.file_path:
        raise AppException(ErrorCode.DI_DOCUMENT_NOT_PROCESSED)
    files_dir = Path(settings.files_dir)
    return files_dir / document.file_path / "original.pdf"
```

The same guard applies in `_doc_dir`.

---

### Gap 1-B — Reuse MinerU per-page text  *(inconsistency I-7)*

MinerU writes a `_middle.json` file next to the PDF.  Its structure is a list of
page dicts each containing `"page_idx"` (0-based) and a `"preproc_blocks"` list.
Text can be reconstructed by joining the `"text"` fields of all blocks on a page.

Add a helper before `_extract_page_texts_pdfminer`:

```python
def _load_mineru_texts(doc_dir: Path, n_pages: int) -> list[str | None]:
    """Return per-page text from MinerU _middle.json, or None per page if absent."""
    result: list[str | None] = [None] * n_pages
    middle_path = doc_dir / "mineru" / "_middle.json"
    if not middle_path.exists():
        return result
    try:
        import json
        data = json.loads(middle_path.read_text())
        for page in data:
            idx = page.get("page_idx", -1)
            if 0 <= idx < n_pages:
                blocks = page.get("preproc_blocks", [])
                texts = [b.get("text", "") for b in blocks if b.get("text")]
                result[idx] = "\n".join(texts).strip() or None
    except Exception as exc:
        logger.warning("Failed to load MinerU _middle.json: %s", exc)
    return result
```

In `process_page_artifacts`, use this before falling back to pdfminer:

```python
mineru_texts = _load_mineru_texts(_doc_dir(document), n_pages_hint)
page_texts = [
    mineru_texts[i] or pdfminer_texts[i]
    for i in range(n_pages_hint)
]
```

---

### Gap 1-C — Switch artifact storage to `StorageManager` / object storage  *(inconsistency I-6)*

The plan specifies that all artifacts are stored under
`porsa-assets/documents/<doc_id>/di/artifacts/` using the project's
`StorageManager`.  Currently they are written to local disk.

**Step 1 — create a key-builder module** at
`backend/document_intelligence/services/storage_keys.py`:

```python
"""
Canonical object-storage key builder for Document Intelligence.

All DI artifacts live under:
  documents/<doc_id>/di/artifacts/   — page images, text, pages.jsonl
  documents/<doc_id>/di/teacher/     — raw VLM responses
  documents/<doc_id>/di/results/     — segments.json, suggestions.json, metadata.json
  documents/<doc_id>/di/outputs/     — child split PDFs

These keys mirror the MinerU layout:
  documents/<doc_id>/mineru/         — existing MinerU output

Joining DI results to MinerU output is a direct match on doc_id + page_num.
"""


def page_image_key(doc_id: int, page_num: int) -> str:
    return f"documents/{doc_id}/di/artifacts/page-{page_num:04d}.png"


def page_thumb_key(doc_id: int, page_num: int) -> str:
    return f"documents/{doc_id}/di/artifacts/page-{page_num:04d}_thumb.png"


def page_text_key(doc_id: int, page_num: int) -> str:
    return f"documents/{doc_id}/di/artifacts/page-{page_num:04d}.txt"


def pages_jsonl_key(doc_id: int) -> str:
    return f"documents/{doc_id}/di/artifacts/pages.jsonl"


def teacher_raw_key(doc_id: int, batch_id: str) -> str:
    return f"documents/{doc_id}/di/teacher/raw_responses/{batch_id}.json"


def results_segments_key(doc_id: int) -> str:
    return f"documents/{doc_id}/di/results/segments.json"


def results_suggestions_key(doc_id: int) -> str:
    return f"documents/{doc_id}/di/results/suggestions.json"


def results_metadata_key(doc_id: int) -> str:
    return f"documents/{doc_id}/di/results/metadata.json"


def split_output_key(doc_id: int, segment_id: int) -> str:
    return f"documents/{doc_id}/di/outputs/child-{segment_id}.pdf"
```

**Step 2 — find the project's `StorageManager`.**

Grep for `StorageManager` or `upload_file` in the existing codebase to find the
storage abstraction already used by MinerU ingestion.  Wrap upload/download behind
a thin helper in `storage_keys.py` so callers don't repeat the bucket name.

```python
# If the project uses boto3 / minio directly:
import boto3
from settings import get_settings

def _client():
    s = get_settings()
    return boto3.client(
        "s3",
        endpoint_url=s.s3_endpoint_url,
        aws_access_key_id=s.s3_access_key,
        aws_secret_access_key=s.s3_secret_key,
    )

BUCKET = "porsa-assets"

def upload_bytes(key: str, data: bytes, content_type: str = "application/octet-stream") -> None:
    _client().put_object(Bucket=BUCKET, Key=key, Body=data, ContentType=content_type)

def download_bytes(key: str) -> bytes:
    return _client().get_object(Bucket=BUCKET, Key=key)["Body"].read()

def key_exists(key: str) -> bool:
    try:
        _client().head_object(Bucket=BUCKET, Key=key)
        return True
    except Exception:
        return False
```

> **Adapt the client call to whatever `StorageManager` pattern the project
> already uses** — do not introduce a second storage layer.  Check
> `backend/core/` and `backend/components/` for the existing pattern.

**Step 3 — update `pdf_artifacts.py`** to upload images and text to object storage
instead of writing to local disk.  Store only the storage **key** (not the full path)
in `DocumentPageArtifact.image_path` and `.thumbnail_path`.

```python
from document_intelligence.services.storage_keys import (
    page_image_key, page_thumb_key, page_text_key, upload_bytes
)

# Inside the per-page loop:
img_key = page_image_key(document.id, page_num)
img_bytes = io.BytesIO()
img.save(img_bytes, format="PNG", optimize=True)
upload_bytes(img_key, img_bytes.getvalue(), "image/png")
image_path = img_key   # store key, not local path

thumb_key = page_thumb_key(document.id, page_num)
thumb_bytes = io.BytesIO()
thumb.save(thumb_bytes, format="PNG", optimize=True)
upload_bytes(thumb_key, thumb_bytes.getvalue(), "image/png")
thumbnail_path = thumb_key
```

The `image_path` and `thumbnail_path` columns on `DocumentPageArtifact` already
exist and are `String` — they can hold either a local path or an object-storage key.
Update the field comment in the model to say "object-storage key".

---

### Gap 1-D — Write `pages.jsonl`  *(inconsistency I-8)*

After building all artifacts, write a JSONL index to object storage.
Add this at the end of `process_page_artifacts`:

```python
import json
from document_intelligence.services.storage_keys import pages_jsonl_key, upload_bytes

lines = []
for art in artifacts:
    lines.append(json.dumps({
        "page_num": art.page_num,
        "text_key": page_text_key(document.id, art.page_num),
        "image_key": art.image_path,
        "thumb_key": art.thumbnail_path,
        "text_hash": art.text_hash,
        "image_hash": art.image_hash,
    }))

jsonl_bytes = "\n".join(lines).encode("utf-8")
upload_bytes(pages_jsonl_key(document.id), jsonl_bytes, "application/jsonl")
logger.info("Wrote pages.jsonl for doc %d (%d pages)", document.id, len(artifacts))
```

Also upload each page's text as a separate object (for later VLM batching):

```python
from document_intelligence.services.storage_keys import page_text_key, upload_bytes

text_content = (art.text or art.ocr_text or "").encode("utf-8")
upload_bytes(page_text_key(document.id, art.page_num), text_content, "text/plain")
```

---

## Data contracts

After Phase 1 runs, the following must be true:
- `DocumentPageArtifact` row exists for every page (1-based `page_num`).
- `image_path` and `thumbnail_path` contain object-storage keys, not local paths.
- `pages.jsonl` is readable from object storage and every row's `text_key` / `image_key`
  resolves to an accessible object.
- Re-running `process_page_artifacts(db, document, force=False)` is a no-op when
  artifacts already exist.
- Running with `force=True` deletes and re-creates all rows and overwrites object-storage objects.

---

## Tests (mandatory)

Create `backend/document_intelligence/tests/test_phase1.py`.

Required fixtures:
- A small text-only PDF (2–3 pages) stored at the path `Document.file_path` points to.
- A scanned (image-only) PDF for OCR testing.
- A PDF whose path exists next to a synthetic MinerU `_middle.json`.

Required tests:
- Text PDF → all `DocumentPageArtifact` rows have non-empty `text`; `ocr_text` is `None`.
- Scanned PDF → `text` is `None` or empty; `ocr_text` is non-empty; `ocr_quality > 0`.
- MinerU present → `text` matches the MinerU `_middle.json` content, not pdfminer output.
- Re-run with `force=False` → row count unchanged, no new uploads.
- Re-run with `force=True` → rows re-created, objects re-uploaded.
- `pages.jsonl` in object storage → parseable, row count matches artifact count.
- Missing `original.pdf` → raises `AppException(DI_DOCUMENT_NOT_PROCESSED)`.
- `Document.file_path = None` → raises `AppException(DI_DOCUMENT_NOT_PROCESSED)`.

Use `moto` or a local MinIO fixture to test object storage without a real S3.

---

## Acceptance checklist

- [ ] `DocumentPageArtifact` rows created for both text and scanned PDF fixtures.
- [ ] MinerU text is preferred over pdfminer when `_middle.json` is present.
- [ ] `image_path` and `thumbnail_path` are object-storage keys (not local paths).
- [ ] `pages.jsonl` readable from object storage after every run.
- [ ] `force=False` is a cached no-op.
- [ ] Missing / unprocessed document raises the catalogued `DI_DOCUMENT_NOT_PROCESSED` error.
- [ ] All tests pass.
