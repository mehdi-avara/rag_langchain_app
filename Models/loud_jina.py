# fastapi_jina_embed_batched.py
from fastapi import FastAPI
from pydantic import BaseModel
from typing import List, Iterable
from transformers import AutoTokenizer, AutoModel
import torch
import uvicorn

app = FastAPI()

# ---------- Config ----------
MODEL_PATH = "Models/jinaai/jina-embeddings-v3"
DEVICE = "cuda" if torch.cuda.is_available() else "cpu"
BATCH_SIZE = 16             # adjust to your VRAM (try 32/16/8/4/2/1)
USE_FP16 = True if DEVICE == "cuda" else False
MAX_LENGTH = None           # None -> tokenizer default/model max. Or set e.g. 8192/4096.

# ---------- Load model ----------
tokenizer = AutoTokenizer.from_pretrained(MODEL_PATH)
model = AutoModel.from_pretrained(MODEL_PATH).to(DEVICE)
model.eval()

class EmbReq(BaseModel):
    input: List[str]

def batchify(xs: List[str], n: int) -> Iterable[List[str]]:
    for i in range(0, len(xs), n):
        yield xs[i:i+n]

def masked_mean_pool(last_hidden_state: torch.Tensor, attention_mask: torch.Tensor) -> torch.Tensor:
    # last_hidden_state: [B, T, H], attention_mask: [B, T]
    mask = attention_mask.unsqueeze(-1)  # [B, T, 1]
    summed = (last_hidden_state * mask).sum(dim=1)                    # [B, H]
    counts = mask.sum(dim=1).clamp(min=1e-9)                          # [B, 1]
    return summed / counts

@torch.inference_mode()
def embed_batch(texts: List[str]) -> List[List[float]]:
    """
    Embeds a list of strings in VRAM-friendly batches.
    Returns a list of L2-normalized vectors (as Python lists).
    """
    global BATCH_SIZE
    all_vecs: List[List[float]] = []

    # optional cap for sequence length
    max_len = MAX_LENGTH if MAX_LENGTH is not None else tokenizer.model_max_length

    # Try current batch size; if OOM happens, halve and retry current batch
    i = 0
    while i < len(texts):
        bs = BATCH_SIZE
        succeeded = False
        while not succeeded and bs >= 1:
            try:
                chunk = texts[i:i+bs]
                # Tokenize
                inputs = tokenizer(
                    chunk,
                    padding=True,
                    truncation=True,
                    max_length=max_len,
                    return_tensors="pt"
                ).to(DEVICE)

                # Forward (with optional FP16 autocast on CUDA)
                if USE_FP16:
                    with torch.cuda.amp.autocast():
                        outputs = model(**inputs)
                else:
                    outputs = model(**inputs)

                # Attention-masked mean pooling
                embs = masked_mean_pool(outputs.last_hidden_state, inputs["attention_mask"])

                # L2 normalize
                embs = torch.nn.functional.normalize(embs, p=2, dim=1)

                all_vecs.extend(embs.detach().cpu().tolist())
                i += bs
                succeeded = True

            except RuntimeError as e:
                # Handle OOM by reducing batch size for this iteration
                if "CUDA out of memory" in str(e):
                    if DEVICE == "cuda":
                        torch.cuda.empty_cache()
                    bs //= 2
                    if bs < 1:
                        raise
                else:
                    raise
    return all_vecs

@app.post("/v1/embeddings")
def emb(req: EmbReq):
    vecs = embed_batch(req.input)
    return {
        "data": [
            {"embedding": v, "index": i, "object": "embedding"}
            for i, v in enumerate(vecs)
        ],
        "model": "jinaai/jina-embeddings-v3",
        "object": "list"
    }

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8088)