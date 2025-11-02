import json
import re
from pathlib import Path
from collections import defaultdict
from typing import Dict, List, Tuple

from settings import get_settings
from db.session import db_session
from db.models import Document, Chunk
from components.folders import get_full_processed_file_path


_IMG_MD_RE = re.compile(r'!\[[^\]]*\]\(([^)]+)\)')

def _normalize(s: str) -> str:
    """
    Light normalization per your rule: compare without !@#$%^&*,
    plus lowercase + whitespace collapse.
    """
    if not s:
        return ""
    s = s.casefold()
    s = re.sub(r'[!@#$%^&*]', ' ', s)        # remove requested symbols
    s = re.sub(r'\s+', ' ', s).strip()       # collapse spaces
    return s

def _extract_image_path_from_markdown(text: str) -> List[str]:
    """Return all image paths found in markdown image syntax."""
    return [m.group(1) for m in _IMG_MD_RE.finditer(text or "")]

def _build_page_text_and_images(content_list: List[dict]) -> Tuple[Dict[int, str], Dict[str, int], Dict[int, List[str]]]:
    """
    Build:
      - page_text_norm: page_idx -> concatenated normalized text
      - image_name_to_page: image filename (basename) -> page_idx
      - page_lines_norm: page_idx -> list of normalized text segments (for fuzzy granularity)
    """
    page_text_parts: Dict[int, List[str]] = defaultdict(list)
    page_lines_norm: Dict[int, List[str]] = defaultdict(list)
    image_name_to_page: Dict[str, int] = {}

    for item in content_list:
        p = item.get("page_idx")
        if p is None:
            continue

        if item.get("type") == "text":
            raw = item.get("text") or ""
            # split on hard breaks if any, then normalize per-line for granular matching
            for ln in filter(None, (seg.strip() for seg in raw.splitlines())):
                nln = _normalize(ln)
                if nln:
                    page_text_parts[p].append(nln)
                    page_lines_norm[p].append(nln)

        elif item.get("type") == "image":
            img_path = item.get("img_path") or ""
            name = Path(img_path).name
            if name:
                image_name_to_page[name] = p

    page_text_norm = {p: " ".join(parts) for p, parts in page_text_parts.items()}
    return page_text_norm, image_name_to_page, page_lines_norm

def _best_fuzzy(line_norm: str, page_lines: List[str]) -> float:
    """
    Return best fuzzy similarity in [0,100] for line_norm against lines on a page.
    Uses rapidfuzz if available, else falls back to difflib.
    """
    if not line_norm or not page_lines:
        return 0.0

    from rapidfuzz.fuzz import partial_ratio
    best = 0.0
    # small early-out for very short lines to avoid noisy matches
    if len(line_norm) < 6:
        return 0.0
    for pl in page_lines:
        # skip trivially short targets
        if len(pl) < 6:
            continue
        sc = partial_ratio(line_norm, pl)
        if sc > best:
            best = sc
    return float(best)


def get_chunk_page_using_json(chunk: Chunk) -> int:
    """Approximate the page number for a chunk using the extracted JSON."""

    # 1) locate JSON
    settings = get_settings()
    doc_dir = Path(settings.files_dir) / str(chunk.doc_id)
    json_path = get_full_processed_file_path(doc_dir, "_content_list.json")
    if not json_path or not Path(json_path).exists():
        return -1

    # 2) load JSON + build indices
    with open(json_path, "r", encoding="utf-8") as f:
        content_list = json.load(f)

    page_text_norm, image_name_to_page, page_lines_norm = _build_page_text_and_images(content_list)

    chunk_content = chunk.content or ""

    # 3) Image-first resolution
    #    If chunk references an image path, map its basename to page
    img_paths = _extract_image_path_from_markdown(chunk_content)
    for ip in img_paths:
        name = Path(ip).name
        if name in image_name_to_page:
            return int(image_name_to_page[name])

    # 4) Text-based scoring (exact substr + fuzzy)
    # Prepare chunk lines (skip markdown image lines)
    raw_lines = [ln.strip() for ln in chunk_content.splitlines()]
    raw_lines = [ln for ln in raw_lines if ln and not _IMG_MD_RE.search(ln)]

    # normalize lines and keep only useful ones
    norm_lines = []
    for ln in raw_lines:
        nln = _normalize(ln)
        if not nln:
            continue
        # skip ultra-short (very noisy)
        if len(nln) < 6:
            continue
        norm_lines.append(nln)

    if not norm_lines:
        return -1

    # weights / thresholds
    W_EXACT = 3.0
    W_FUZZY = 1.0
    FUZZY_MIN = 70.0  # only count fuzzy matches >= 70
    SCORE_MIN_ACCEPT = 2.0  # require at least this much to trust a page

    page_scores: Dict[int, float] = defaultdict(float)

    # exact substring matches against concatenated page text
    for p, ptext in page_text_norm.items():
        if not ptext:
            continue
        for nln in norm_lines:
            if nln in ptext:
                page_scores[p] += W_EXACT

    # fuzzy only for lines that didn't hit exact on that page
    for p, ptext in page_text_norm.items():
        if not ptext:
            continue
        # per-page lines (granular fuzzy target)
        plines = page_lines_norm.get(p, [])
        if not plines:
            continue
        for nln in norm_lines:
            # skip fuzzy if exact already credited for this line-page pair
            if nln in ptext:
                continue
            best = _best_fuzzy(nln, plines)
            if best >= FUZZY_MIN:
                page_scores[p] += W_FUZZY * (best / 100.0)

    if not page_scores:
        return -1

    # pick best page
    best_page, best_score = max(page_scores.items(), key=lambda kv: kv[1])
    if best_score < SCORE_MIN_ACCEPT:
        return -1

    return int(best_page)

if __name__ == "__main__":
    with db_session() as db:
        # test run: find all chunks without page_num and try to assign
        chunks = db.query(Chunk).limit(400).all()
        print(f"Found {len(chunks)} chunks without page_num")
        updated = 0
        not_updated = 0
        for ch in chunks:
            pg = get_chunk_page_using_json(ch)
            if pg != -1:
                # ch.page_num = pg
                updated += 1
                print(f"Chunk {ch.id} to page {pg}")
            else:
                not_updated+=1
                print(f"Chunk {ch.id} not found")
                
            # input("testing pause...")
        # db.commit()
        print(f"Updated {updated} chunks with page numbers")
        print(f"Not updated {not_updated} chunks")