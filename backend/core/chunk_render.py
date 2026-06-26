"""Retrieval-time rendering of chunk content for clients.

Chunk content is stored with a stable, host-relative image reference
(``/documents/{doc_id}/images/{filename}``) — good for storage, search and
re-ingestion, but not directly openable by a browser. When a chunk is *read*,
those references are rewritten to fresh presigned S3 GET URLs (minted per
response, because presigned URLs expire) so figures drop straight into an
``<img src>``. During migration, documents with no S3 object fall back to the
stable absolute app-route URL served from local disk.

See docs/MINERU_S3_AND_CHUNK_IMAGES_PLAN.md (D1c).
"""

from __future__ import annotations

import re
from typing import List, Optional

from settings import get_settings

settings = get_settings()


def _stored_image_pattern(doc_id: int) -> re.Pattern:
    return re.compile(
        r"/documents/" + str(int(doc_id)) + r"/images/(?P<filename>[^)\s\"'<>]+)"
    )


def _fallback_url(doc_id: int, filename: str) -> str:
    base = (settings.base_url or "").rstrip("/")
    return f"{base}/documents/{doc_id}/images/{filename}"


class ImageUrlResolver:
    """Resolves a figure filename to an openable URL for one document.

    Presigns the S3 object under the document's ``mineru/images/`` prefix when it
    exists; otherwise returns the stable absolute app-route URL. Caches a single
    StorageManager and per-filename results for the life of the resolver.
    """

    def __init__(self, doc, db):
        self.doc = doc
        self.db = db
        self.doc_id = doc.id
        self.mineru_prefix = getattr(doc, "mineru_prefix", None)
        self._cache: dict[str, str] = {}
        self._manager = None

    def _get_manager(self):
        if self._manager is None:
            try:
                from storage.manager import StorageManager
                self._manager = StorageManager(self.db)
            except Exception:
                self._manager = False  # sentinel: storage unavailable
        return self._manager or None

    def _storage_key(self, filename: str) -> Optional[str]:
        if not self.mineru_prefix:
            return None
        return f"{self.mineru_prefix.rstrip('/')}/images/{filename}"

    def resolve(self, filename: str) -> str:
        if filename in self._cache:
            return self._cache[filename]

        url = self._fallback(filename)
        key = self._storage_key(filename)
        if key:
            manager = self._get_manager()
            if manager is not None:
                try:
                    if manager.object_exists(key):
                        url = manager.create_presigned_get_for_key(key=key)
                except Exception:
                    url = self._fallback(filename)

        self._cache[filename] = url
        return url

    def _fallback(self, filename: str) -> str:
        return _fallback_url(self.doc_id, filename)


def render_chunk_content_for_client(content: str, doc, db) -> str:
    """Rewrite stored ``/documents/{id}/images/...`` refs to openable URLs."""
    if not content:
        return content

    resolver = ImageUrlResolver(doc, db)
    pattern = _stored_image_pattern(doc.id)

    def _replace(match: re.Match) -> str:
        filename = match.group("filename").split("/")[-1]
        return resolver.resolve(filename)

    return pattern.sub(_replace, content)


def build_chunk_images(chunk, doc, db) -> List[dict]:
    """Build the ``ChunkOut.images`` payload from a chunk's ImageChunk rows."""
    rows = getattr(chunk, "image_data", None) or []
    if not rows:
        return []

    resolver = ImageUrlResolver(doc, db)
    images: List[dict] = []
    for row in rows:
        filename = None
        if getattr(row, "storage_key", None):
            filename = str(row.storage_key).split("/")[-1]
        elif getattr(row, "position", None):
            filename = str(row.position).split("/")[-1]
        if not filename:
            continue
        images.append({
            "url": resolver.resolve(filename),
            "caption": getattr(row, "caption", None),
            "page_num": getattr(row, "page_num", None),
        })
    return images
