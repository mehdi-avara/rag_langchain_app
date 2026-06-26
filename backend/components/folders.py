from pathlib import Path
from typing import NamedTuple, Optional


def get_full_processed_file_path(doc_dir: Path, file_ext: str) -> str:
    if not doc_dir.exists():
        raise FileNotFoundError(f"Directory not found: {doc_dir}")

    for file in doc_dir.rglob(f"*{file_ext}"):
        return str(file)  # first match
    raise FileNotFoundError(f"No file with extension {file_ext} found in {doc_dir}.")


class ProcessedBundle(NamedTuple):
    """The MinerU processed bundle for a document, discovered dynamically.

    MinerU writes into a method-named subfolder (``original/auto/...``, where
    ``auto`` becomes ``vlm``/``ocr``/``txt`` depending on ``MINERU_METHOD``).
    These paths are discovered via ``rglob`` so nothing hardcodes ``auto``.
    """

    middle_json: Optional[Path]
    images_dir: Optional[Path]
    method_dir: Optional[Path]


def find_processed_bundle(doc_dir: Path) -> ProcessedBundle:
    """Locate the MinerU output bundle under ``doc_dir`` (method-agnostic).

    Returns a :class:`ProcessedBundle`; any member is ``None`` if not found.
    The ``method_dir`` is the directory that contains ``*_middle.json`` (i.e.
    the ``original/<method>`` folder), and ``images_dir`` is the figures folder
    inside it.
    """
    doc_dir = Path(doc_dir)
    if not doc_dir.exists():
        return ProcessedBundle(None, None, None)

    middle_json: Optional[Path] = None
    for candidate in doc_dir.rglob("*_middle.json"):
        middle_json = candidate
        break

    method_dir: Optional[Path] = middle_json.parent if middle_json is not None else None

    images_dir: Optional[Path] = None
    if method_dir is not None:
        candidate_images = method_dir / "images"
        if candidate_images.is_dir():
            images_dir = candidate_images

    if images_dir is None:
        # Fall back to discovering any images/ directory under the doc dir.
        for candidate in doc_dir.rglob("images"):
            if candidate.is_dir():
                images_dir = candidate
                break

    return ProcessedBundle(middle_json=middle_json, images_dir=images_dir, method_dir=method_dir)


def find_processed_images_dir(doc_dir: Path) -> Optional[Path]:
    """Convenience wrapper returning just the discovered ``images/`` directory."""
    return find_processed_bundle(doc_dir).images_dir
