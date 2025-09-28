
import os
# Set timeout and retry parameters
os.environ['HF_HUB_TIMEOUT'] = '30'
os.environ['HF_HUB_RETRIES'] = '3'
from  huggingface_hub import snapshot_download, login
access_token = "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"
login(token=access_token)
#snapshot_download(
#    repo_id='deepseek-ai/deepseek-coder-6.7b-base',
#    local_dir='Models/deepseek-ai/deepseek-coder-6.7b-base',
#    local_dir_use_symlinks=False,
#    ignore_patterns=[".git/","*.bin"]
#)



snapshot_download(
    repo_id="Qwen/Qwen3-30B-A3B-GGUF",
    local_dir="Models/Qwen/Qwen3-30B-A3B-GGUF",
    local_dir_use_symlinks=False,
    allow_patterns=[
        "*Q4_K_M.gguf"              # the 4-bit model (pick your quant)
    ],
    ignore_patterns=[".git/*"],
)
#snapshot_download(
#   repo_id='jinaai/jina-embeddings-v3',
#   local_dir='Models/jinaai/jina-embeddings-v3',
#  local_dir_use_symlinks=False,
#   ignore_patterns=[".git/","*.bin"],
#   )