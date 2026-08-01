import os

from huggingface_hub import snapshot_download


REPOSITORY_ID = "Qwen/Qwen3-30B-A3B-GGUF"
LOCAL_DIRECTORY = "Models/Qwen/Qwen3-30B-A3B-GGUF"
ALLOWED_PATTERNS = ["*Q4_K_M.gguf"]
IGNORED_PATTERNS = [".git/*"]


def download_model() -> str:
    token = os.getenv("HF_TOKEN") or None

    return snapshot_download(
        repo_id=REPOSITORY_ID,
        local_dir=LOCAL_DIRECTORY,
        local_dir_use_symlinks=False,
        allow_patterns=ALLOWED_PATTERNS,
        ignore_patterns=IGNORED_PATTERNS,
        token=token,
    )


def main() -> None:
    os.environ.setdefault("HF_HUB_TIMEOUT", "30")
    os.environ.setdefault("HF_HUB_RETRIES", "3")
    download_model()


if __name__ == "__main__":
    main()
