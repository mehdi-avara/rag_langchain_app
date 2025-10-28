from pathlib import Path
import shutil

EXTRACTED = Path("processed_pdf_original")
PROCESSED = Path("processed")
DEST      = Path("proccessed_pdf_orginal")

DEST.mkdir(parents=True, exist_ok=True)

def has_output_for(basename: str) -> bool:
    """
    Success = processed/<basename>/ exists
    AND somewhere under it there is a .json file.
    """
    out_dir = PROCESSED / basename
    if not out_dir.is_dir():
        return False

    # recursively look for any json file
    for child in out_dir.rglob("*.json"):
        if child.is_file():
            return True

    return False

def unique_path(dst_dir: Path, name: str) -> Path:
    """
    Avoid overwriting. e.g. file.pdf → file (1).pdf → file (2).pdf ...
    """
    p = dst_dir / name
    if not p.exists():
        return p
    stem = Path(name).stem
    ext  = Path(name).suffix
    i = 1
    while True:
        cand = dst_dir / f"{stem} ({i}){ext}"
        if not cand.exists():
            return cand
        i += 1

moved = 0
skipped = 0

for pdf in EXTRACTED.iterdir():
    # only consider files that are PDFs, regardless of case
    if not (pdf.is_file() and pdf.suffix.lower() == ".pdf"):
        continue

    base = pdf.stem  # "SP0-100-CGTP-00-EL-RT-444"
    if has_output_for(base):
        target = unique_path(DEST, pdf.name)
        print(f"✔ Moving: {pdf.name}  →  {target.name}")
        shutil.move(str(pdf), str(target))
        moved += 1
    else:
        skipped += 1

print(f"\nDone. Moved: {moved}, Skipped: {skipped}.")