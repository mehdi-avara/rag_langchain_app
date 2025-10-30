import os
import shutil
import subprocess
from typing import List

# =======================
# CONFIG
# =======================
INPUT_DIR = "extracted_files"
OUTPUT_DIR = "processed1"
ORIGINAL_DONE_DIR = "processed_pdf_original1"
TMP_BASE = "work_tmp"

BACKEND = "vlm-vllm-engine"
DEVICE = "cuda"
MINERU_BIN = "/home/habib/.conda/envs/mineru310/bin/mineru"

BATCH_SIZE = 5  # process 30 at a time

# allow only these (lowercase; we always compare with ext.lower())
ALLOWED_EXT = {
    ".pdf"
}


def run_cmd(cmd: list, capture_output: bool = True) -> subprocess.CompletedProcess:
    """
    Small helper to run shell commands.
    Doesn't raise exception if fails; we handle manually.
    """
    try:
        if capture_output:
            return subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        else:
            return subprocess.run(cmd)
    except Exception as e:
        # We'll just fake a CompletedProcess-like object
        class Fake:
            def __init__(self, e):
                self.returncode = 999
                self.stdout = ""
                self.stderr = str(e)
        return Fake(e)


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


def kill_scope(unit_name: str):
    """
    Force-kill the entire systemd scope for this batch.
    This should kill mineru + any child processes like vllm.
    Safe to call even if already dead.
    """
    # systemctl kill <unit> sends SIGTERM to all PIDs in the cgroup
    kill_term = run_cmd(["sudo", "systemctl", "kill", unit_name])
    if kill_term.returncode != 0:
        print(f"[INFO] systemctl kill {unit_name} returncode={kill_term.returncode} stderr={kill_term.stderr.strip()}")

    # As insurance, send SIGKILL (9) if anything still alive in that scope
    kill_kill = run_cmd(["sudo", "systemctl", "kill", unit_name, "-s", "KILL"])
    if kill_kill.returncode != 0:
        print(f"[INFO] systemctl kill -s KILL {unit_name} returncode={kill_kill.returncode} stderr={kill_kill.stderr.strip()}")


def kill_leftover_vllm():
    """
    Emergency cleanup. If for any reason vllm server is still alive
    (holding GPU VRAM), nuke it.
    We match on 'vllm' in the command line.
    """
    
    proc = run_cmd(["pgrep", "-fa", "VLLM::EngineCore"])
    
    if proc.returncode == 0 and proc.stdout.strip():
        print("⚠️  Leftover vllm processes detected:")
        print(proc.stdout)

        # extract PIDs safely
        pids = [line.split()[0] for line in proc.stdout.strip().splitlines()]
        for pid in pids:
            run_cmd(["kill", "-9", pid], capture_output=False)
            print(f"💀 Killed leftover vllm process PID {pid}")
            print("💀 Killed leftover vllm processes.")

def run_mineru_on_batch(batch_tmp_dir: str, batch_idx: int) -> bool:
    """
    Run mineru (via systemd-run limits) on a batch folder,
    wait for it to finish, capture success/failure,
    and ensure cleanup of child procs.
    """
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
    unit_name = f"{unit_name}.scope"
    print(f"🚀 Running mineru on batch {batch_idx:04d} ({batch_tmp_dir})")
    try:
        process = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        stdout, stderr = process.communicate()
    except Exception as e:
        print(f"[EXCEPTION] Failed to launch mineru for batch {batch_idx:04d}: {e}")
        # kill scope just in case something partially started
        kill_scope(unit_name)
        kill_leftover_vllm()
        return False

    rc = process.returncode
    if rc != 0:
        print(f"[❌ ERROR] batch {batch_idx:04d} failed (exit {rc})")
        if stdout:
            print("----- mineru stdout -----")
            print(stdout)
        if stderr:
            print("----- mineru stderr -----")
            print(stderr)

        # Force kill children from that scope (vllm, etc.)
        kill_scope(unit_name)
        kill_leftover_vllm()
        return False

    else:
        print(f"[✅ OK] batch {batch_idx:04d} finished successfully")
        # Even on success, be strict: kill scope so vllm doesn't keep running.
        kill_scope(unit_name)
        kill_leftover_vllm()
        return True


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
