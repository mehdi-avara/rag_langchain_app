import json
import re
from pathlib import Path
from collections import defaultdict
from typing import Dict, List, Tuple
import html

from settings import get_settings
from db.session import db_session
from db.models import Document, Chunk
from components.folders import get_full_processed_file_path


_IMG_MD_RE = re.compile(r'!\[[^\]]*\]\(([^)]+)\)')
_TABLE_BLOCK_RE = re.compile(r'<table\b[^>]*>.*?</table>', re.I | re.S)

def _extract_table_blocks_from_markdown(text: str) -> List[str]:
    """Return raw <table>...</table> HTML blocks from the markdown chunk."""
    if not text:
        return []
    return _TABLE_BLOCK_RE.findall(text)

def _table_html_to_lines(table_html: str) -> List[str]:
    """
    Convert an HTML <table>...</table> string into a list of row-like text lines.
    We do a very light HTML-to-text without external libs:
      - replace <tr> with row breaks
      - replace <th>/<td> with cell separators
      - strip tags, unescape entities, collapse whitespace
    """
    if not table_html:
        return []

    s = table_html
    # normalize row/cell boundaries to make splitting easier
    s = re.sub(r'(?is)</tr\s*>', '\n', s)
    s = re.sub(r'(?is)<tr\b[^>]*>', '', s)
    s = re.sub(r'(?is)</t[hd]\s*>', ' ', s)
    s = re.sub(r'(?is)<t[hd]\b[^>]*>', ' ', s)

    # drop the rest of tags
    s = re.sub(r'(?is)<[^>]+>', ' ', s)

    # HTML entities → text
    s = html.unescape(s)

    # Split rows, clean
    lines = []
    for raw in s.splitlines():
        raw = raw.strip()
        if not raw:
            continue
        # collapse spaces and normalize
        raw = re.sub(r'\s+', ' ', raw)
        if raw:
            lines.append(raw)
    return lines


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
        
        elif item.get("type") == "table":
            # map table image (if any)
            img_path = item.get("img_path") or ""
            name = Path(img_path).name
            if name:
                image_name_to_page[name] = p

            # captions / footnotes
            for part in (item.get("table_caption") or []):
                nln = _normalize(part or "")
                if nln:
                    page_text_parts[p].append(nln)
                    page_lines_norm[p].append(nln)
            for part in (item.get("table_footnote") or []):
                nln = _normalize(part or "")
                if nln:
                    page_text_parts[p].append(nln)
                    page_lines_norm[p].append(nln)

            # table body (HTML → lines)
            tbody = item.get("table_body") or ""
            for ln in _table_html_to_lines(tbody):
                nln = _normalize(ln)
                if nln:
                    page_text_parts[p].append(nln)
                    page_lines_norm[p].append(nln)

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

    # also parse any HTML <table> blocks present in the markdown chunk
    md_table_blocks = _extract_table_blocks_from_markdown(chunk_content)
    for tb in md_table_blocks:
        for tln in _table_html_to_lines(tb):
            nln = _normalize(tln)
            if nln and len(nln) >= 6:
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
    for doc_id in range(93, 195):
        with db_session() as db:
            # process only chunks missing page_num; drop .limit(400) or paginate
            chunks = (db.query(Chunk)
                        .filter(Chunk.doc_id == doc_id)
                        # .filter((Chunk.page_num == None) | (Chunk.page_num == -1))
                        .order_by(Chunk.id)
                        .all())

            print(f"[doc {doc_id}] Found {len(chunks)} chunks without page_num")
            updated = not_updated = 0
            older_page = None  # don’t force 0 before first success

            # simple per-doc cache to avoid reloading JSON for each chunk
            _page_cache = {}  # optional if you modify get_chunk_page_using_json to accept cached indices

            for ch in chunks:
                pg = get_chunk_page_using_json(ch)  # ideally pass cache here

                if pg != -1:
                    # enforce non-decreasing pages if you really want that behavior
                    if older_page is not None and pg < older_page:
                        # choose one policy: clamp or skip
                        # clamp:
                        pg = older_page
                        # or: continue  # to skip assigning
                    ch.page_num = pg
                    older_page = pg if older_page is None or pg > older_page else older_page
                    updated += 1
                    print(f"  Chunk {ch.id} → page {pg}")
                else:
                    # only carry forward if we already have a valid page; else leave unset
                    if older_page is not None:
                        ch.page_num = older_page  # optional: carry-forward
                        print(f"  Chunk {ch.id} not found; carry-forward {older_page}")
                    else:
                        # keep as NULL/-1 to revisit later
                        print(f"  Chunk {ch.id} not found; leaving unset")
                    not_updated += 1

            db.commit()
            print(f"[doc {doc_id}] ✅ Updated {updated} | ❌ Not updated {not_updated}")