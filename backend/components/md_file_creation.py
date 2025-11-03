""""
impelimented module code
https://github.com/opendatalab/MinerU/blob/master/mineru/backend/pipeline/pipeline_middle_json_mkcontent.py
Convert MinerU middle-level JSON (pdf_info) to Markdown and optionally compare with an existing MD file.
"""
from mineru.utils.enum_class import BlockType, ContentType, MakeMode
from mineru_main_file_creator import union_make



#!/usr/bin/env python3
import argparse
import json
from pathlib import Path
from typing import List

# import your already-defined functions/enums from the same module or adjust the imports:
# from mineru_like_module import union_make

# ---------- Optional: similarity helpers (no extra deps required) ----------
def _normalize_line(s: str) -> str:
    import re
    s = s.casefold().strip()
    s = re.sub(r'\s+', ' ', s)
    return s

def _similarity_report(gen_md: str, ref_md: str) -> str:
    """Return a short, human-friendly similarity report between two MD strings."""
    import difflib

    # 1) Character-level similarity
    char_ratio = difflib.SequenceMatcher(None, gen_md, ref_md).ratio()

    # 2) Line-level similarity (normalized)
    gen_lines = [_normalize_line(l) for l in gen_md.splitlines() if l.strip()]
    ref_lines = [_normalize_line(l) for l in ref_md.splitlines() if l.strip()]

    # Jaccard over unique normalized lines (fast, robust to order)
    gen_set, ref_set = set(gen_lines), set(ref_lines)
    inter = len(gen_set & ref_set)
    union = len(gen_set | ref_set) or 1
    jaccard = inter / union

    # 3) difflib “quick ratio” on line-joined text (cheap second signal)
    line_ratio = difflib.SequenceMatcher(None, "\n".join(gen_lines), "\n".join(ref_lines)).ratio()

    return (
        f"Similarity report:\n"
        f"- Character-level ratio: {char_ratio*100:.2f}%\n"
        f"- Line Jaccard (unique, normalized): {jaccard*100:.2f}%\n"
        f"- Line-based ratio (difflib): {line_ratio*100:.2f}%"
    )

# ---------- Main ----------
def main():
    ap = argparse.ArgumentParser(description="Convert MinerU middle-level JSON (pdf_info) to Markdown and optionally compare.")
    ap.add_argument("json_path", type=Path, help="Path to JSON containing top-level key 'pdf_info'.")
    ap.add_argument("--out", type=Path, help="Output .md path (default: <json_stem>.md in current dir).")
    ap.add_argument("--compare", type=Path, help="Path to an existing .md file to compare against.")
    args = ap.parse_args()

    if not args.json_path.exists():
        raise SystemExit(f"Input JSON not found: {args.json_path}")

    # Load JSON
    with args.json_path.open("r", encoding="utf-8") as f:
        data = json.load(f)

    # Accept either {"pdf_info": [...]} or a raw list
    pdf_info = data.get("pdf_info", data)
    if not isinstance(pdf_info, list):
        raise SystemExit("Input JSON must contain a list under key 'pdf_info' (or be a list itself).")

    # Convert to Markdown using your function
    md_text,pages_list = union_make(pdf_info_dict=pdf_info, make_mode=MakeMode.MM_MD,img_buket_path="images")

    # Decide output path
    out_path: Path = args.out if args.out else Path.cwd() / f"{args.json_path.stem}.md"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with out_path.open("w", encoding="utf-8") as f:
        f.write(md_text)

    print(f"✅ Markdown written to: {out_path}")

    # Optional comparison
    if args.compare:
        if not args.compare.exists():
            raise SystemExit(f"--compare file not found: {args.compare}")
        with args.compare.open("r", encoding="utf-8") as f:
            ref_md = f.read()
        report = _similarity_report(md_text, ref_md)
        print(report)
    print(len(md_text))
    print(len(ref_md))

if __name__ == "__main__":
    main()