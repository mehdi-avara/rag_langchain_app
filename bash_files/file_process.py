import os
import shutil
import subprocess
from typing import List

# =======================
# CONFIG
# =======================
INPUT_DIR = "extracted_files"
OUTPUT_DIR = "processed"
ORIGINAL_DONE_DIR = "processed_pdf_original"
TMP_BASE = "work_tmp"

BACKEND = "vlm-vllm-engine"
DEVICE = "cuda"
MINERU_BIN = "/home/habib/.conda/envs/mineru310/bin/mineru"

BATCH_SIZE = 30  # process 30 at a time

# allow only these (lowercase; we always compare with ext.lower())
ALLOWED_EXT = {
    ".pdf", ".png", ".jpg", ".jpeg", ".tif", ".tiff", ".bmp", ".gif",
    ".docx", ".pptx", ".xlsx", ".txt"
}


# --------------------------
# FILE LISTING (SORT BY SIZE)
# --------------------------
def list_candidate_files() -> List[str]:
    """Return list of file paths sorted by size (ascending)."""
    all_entries = sorted(os.listdir(INPUT_DIR))
    valid_files = []
    for entry in all_entries:
        full_path = os.path.join(INPUT_DIR, entry)
        if os.path.isfile(full_path):
            _, ext = os.path.splitext(entry)
            if (not ALLOWED_EXT) or (ext.lower() in ALLOWED_EXT):
                valid_files.append(full_path)

    # sort by file size
    valid_files.sort(key=lambda f: os.path.getsize(f))
    print(f"📊 Found {len(valid_files)} valid files (sorted by size ascending).")
    return valid_files


def make_batches(files: List[str], batch_size: int) -> List[List[str]]:
    """Split files into equal batches of given size."""
    return [files[i:i + batch_size] for i in range(0, len(files), batch_size)]


def prepare_batch_dir(batch_files: List[str], batch_idx: int) -> str:
    """Create batch temp directory and copy its files there."""
    batch_dir_name = f"batch_{batch_idx:04d}"
    batch_tmp_dir = os.path.join(TMP_BASE, batch_dir_name)
    os.makedirs(batch_tmp_dir, exist_ok=True)

    print(f"📂 Creating batch folder {batch_tmp_dir} with {len(batch_files)} files")

    for f in batch_files:
        fname = os.path.basename(f)
        dst = os.path.join(batch_tmp_dir, fname)
        shutil.copy2(f, dst)

    return batch_tmp_dir


def run_mineru_on_batch(batch_tmp_dir: str, batch_idx: int) -> bool:
    """Run mineru (via systemd-run limits) on a batch folder."""
    unit_name = f"mineru_limit_batch_{batch_idx:04d}"
    cmd = [
        "sudo", "systemd-run", "--scope", f"--unit={unit_name}",
        "-p", "MemoryMax=65G",
        "-p", "MemorySwapMax=0",
        "-p", "CPUQuota=1100%",
        "-p", "ManagedOOMMemoryPressure=kill",
        MINERU_BIN,
        "-p", batch_tmp_dir,
        "-o", OUTPUT_DIR,
        "-b", BACKEND,
        "-d", DEVICE
    ]

    print(f"🚀 Running mineru on batch {batch_idx:04d} ({batch_tmp_dir})")
    try:
        process = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        stdout, stderr = process.communicate()

        if process.returncode != 0:
            print(f"[❌ ERROR] batch {batch_idx:04d} failed (exit {process.returncode})")
            print(stderr.decode('utf-8', errors='ignore'))
            return False
        else:
            print(f"[✅ OK] batch {batch_idx:04d} finished successfully")
            return True

    except Exception as e:
        print(f"[EXCEPTION] batch {batch_idx:04d}: {e}")
        return False


def cleanup_and_archive(batch_files: List[str], batch_tmp_dir: str, batch_idx: int):
    """Move processed originals and remove temp folder."""
    os.makedirs(ORIGINAL_DONE_DIR, exist_ok=True)

    for src_path in batch_files:
        fname = os.path.basename(src_path)
        dest_path = os.path.join(ORIGINAL_DONE_DIR, fname)
        if os.path.exists(src_path):
            try:
                shutil.move(src_path, dest_path)
                print(f"📦 Moved original {fname} → {dest_path}")
            except Exception as e:
                print(f"[WARN] Could not move {fname}: {e}")
        else:
            print(f"[WARN] Skipped moving {fname}; not found anymore")

    try:
        shutil.rmtree(batch_tmp_dir)
        print(f"🧹 Removed temp dir {batch_tmp_dir}")
    except Exception as e:
        print(f"[WARN] Could not remove temp dir {batch_tmp_dir}: {e}")

    print(f"🏁 Batch {batch_idx:04d} completed (success or fail).")


# --------------------------
# MAIN LOGIC
# --------------------------
def main():
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    os.makedirs(TMP_BASE, exist_ok=True)
    os.makedirs(ORIGINAL_DONE_DIR, exist_ok=True)

    all_files = list_candidate_files()
    if not all_files:
        print("No files to process.")
        return

    batches = make_batches(all_files, BATCH_SIZE)
    total_batches = len(batches)

    print(f"📦 Total: {len(all_files)} files → {total_batches} batches of {BATCH_SIZE} files each.")

    for batch_idx, batch_files in enumerate(batches, start=1):
        batch_tmp_dir = prepare_batch_dir(batch_files, batch_idx)
        ok = run_mineru_on_batch(batch_tmp_dir, batch_idx)
        cleanup_and_archive(batch_files, batch_tmp_dir, batch_idx)
        if not ok:
            print(f"[WARN] mineru error in batch {batch_idx:04d}, continuing...")

    print("🎉 All batches processed. Originals moved to processed_pdf_original/.")


if __name__ == "__main__":
    main()