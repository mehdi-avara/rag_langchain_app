from pathlib import Path

def get_full_processed_file_path(doc_dir: Path, file_ext: str) -> str:
    if not doc_dir.exists():
        raise FileNotFoundError(f"Directory not found: {doc_dir}")

    for file in doc_dir.rglob(f"*{file_ext}"):
        return str(file)  # first match
    raise FileNotFoundError(f"No file with extension {file_ext} found in {doc_dir}.")