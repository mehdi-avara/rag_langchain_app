"""Persist MinerU-derived artifacts to S3 and keep their image references stable.

This module is the single place that:
  * rewrites the bare image filenames inside a MinerU ``_middle.json`` to the
    stable, host-relative app path ``/documents/{doc_id}/images/{filename}``
    (so the same canonical reference flows into the chunks built from it), and
  * uploads the processed bundle (working PDF, every figure, and the rewritten
    ``_middle.json``) next to the source asset under a parallel ``mineru/``
    prefix in object storage.

S3 upload is best-effort: a failure here is logged as a catalogued error but
never fails the text ingestion that already succeeded (artifacts can be retried
by the backfill task). See docs/MINERU_S3_AND_CHUNK_IMAGES_PLAN.md.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import List, Optional

from components.folders import find_processed_bundle
from core.exceptions import error_codes

# ---------------------------------------------------------------------------
# Image-reference rewriting (the "corrected references")
# ---------------------------------------------------------------------------

_ABSOLUTE_PREFIXES = ("/", "http://", "https://", "data:")


def canonical_image_ref(doc_id: int, filename: str) -> str:
    """Stable, host-relative, access-controlled image path baked into storage.

    Matches the real route ``GET /documents/{doc_id}/images/{path}``.
    """
    return f"/documents/{doc_id}/images/{filename}"


def _rewrite_node(node, doc_id: int, filenames: List[str]) -> None:
    if isinstance(node, dict):
        raw = node.get("image_path")
        if isinstance(raw, str) and raw.strip():
            value = raw.strip()
            if not value.startswith(("http://", "https://", "data:")):
                filename = os.path.basename(value)
                if filename:
                    # Preserve the original bare filename so the S3 key
                    # ``mineru/images/{filename}`` stays derivable, but only on
                    # first rewrite (keep it stable across idempotent re-runs).
                    if not node.get("image_name"):
                        node["image_name"] = filename
                    node["image_path"] = canonical_image_ref(doc_id, filename)
                    filenames.append(filename)
        for value in node.values():
            _rewrite_node(value, doc_id, filenames)
    elif isinstance(node, list):
        for item in node:
            _rewrite_node(item, doc_id, filenames)


def rewrite_middle_json_image_refs(pdf_info, doc_id: int) -> List[str]:
    """Rewrite every image reference in ``pdf_info`` to its canonical app path.

    Mutates ``pdf_info`` in place (walking pages → blocks → lines → spans and
    any nested structure) and returns the list of original image filenames
    encountered. Idempotent: re-running on already-rewritten data yields the
    same result and preserves the first-seen ``image_name``.
    """
    filenames: List[str] = []
    _rewrite_node(pdf_info, doc_id, filenames)
    # De-duplicate while preserving order.
    seen = set()
    unique: List[str] = []
    for name in filenames:
        if name not in seen:
            seen.add(name)
            unique.append(name)
    return unique


# ---------------------------------------------------------------------------
# Uploading the processed bundle to S3
# ---------------------------------------------------------------------------

def _log_catalogued(message: str) -> None:
    # Catalogued-error logging without raising: keep ingestion non-fatal.
    print(f"[mineru-s3][{error_codes.INTERNAL_SERVER_ERROR}] {message}", flush=True)


def upload_mineru_bundle(
    db,
    *,
    asset_id: int,
    doc_dir: Path,
    middle_json_obj: Optional[dict] = None,
    original_pdf_path: Optional[Path] = None,
) -> Optional[str]:
    """Upload the processed bundle for ``asset_id`` to its ``mineru/`` prefix.

    Uploads the rewritten ``_middle.json`` (``middle_json_obj``, already image-
    ref-rewritten by the caller), every file under the discovered ``images/``
    folder, and the working ``original.pdf`` if present. Returns the ``mineru/``
    prefix on success, or ``None`` if nothing could be uploaded. Never raises:
    any failure is logged as a catalogued error.
    """
    # Imported lazily to avoid importing boto3/Models at module import time
    # (this module is also imported by pure-unit tests for the rewrite logic).
    try:
        from Models import FileAsset
        from storage.manager import StorageManager
    except Exception as exc:  # pragma: no cover - defensive
        _log_catalogued(f"could not import storage layer for asset {asset_id}: {exc!r}")
        return None

    try:
        asset = db.query(FileAsset).filter(FileAsset.id == asset_id).first()
        if not asset:
            _log_catalogued(f"asset {asset_id} not found; skipping S3 artifact upload")
            return None

        manager = StorageManager(db)
        prefix = StorageManager.derived_prefix(asset)
        bundle = find_processed_bundle(Path(doc_dir))

        uploaded_any = False

        # 1) Rewritten middle.json
        if middle_json_obj is not None:
            data = json.dumps(middle_json_obj, ensure_ascii=False).encode("utf-8")
            manager.upload_bytes(
                key=StorageManager.derived_key(asset, "middle.json"),
                data=data,
                content_type="application/json",
            )
            uploaded_any = True
        elif bundle.middle_json is not None and bundle.middle_json.exists():
            manager.upload_path(
                key=StorageManager.derived_key(asset, "middle.json"),
                path=bundle.middle_json,
                content_type="application/json",
            )
            uploaded_any = True

        # 2) Every figure under the discovered images/ folder
        if bundle.images_dir is not None and bundle.images_dir.is_dir():
            for image_file in sorted(bundle.images_dir.iterdir()):
                if not image_file.is_file():
                    continue
                manager.upload_path(
                    key=StorageManager.derived_key(asset, f"images/{image_file.name}"),
                    path=image_file,
                )
                uploaded_any = True

        # 3) Working PDF copy (so the processed bundle is self-contained)
        pdf_path = original_pdf_path
        if pdf_path is None:
            candidate = Path(doc_dir) / "original.pdf"
            if candidate.exists():
                pdf_path = candidate
        if pdf_path is not None and Path(pdf_path).exists():
            manager.upload_path(
                key=StorageManager.derived_key(asset, "original.pdf"),
                path=pdf_path,
                content_type="application/pdf",
            )
            uploaded_any = True

        if not uploaded_any:
            _log_catalogued(f"no artifacts found to upload for asset {asset_id} under {doc_dir}")
            return None

        return prefix

    except Exception as exc:  # non-fatal by design
        _log_catalogued(f"failed to upload MinerU artifacts for asset {asset_id}: {exc!r}")
        return None
