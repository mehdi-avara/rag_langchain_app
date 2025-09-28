# fastapi_jina_embed.py
from fastapi import FastAPI
from pydantic import BaseModel
from transformers import AutoTokenizer, AutoModel
import torch
import uvicorn

app = FastAPI()

# Load tokenizer + model
device = "cuda" if torch.cuda.is_available() else "cpu"
tokenizer = AutoTokenizer.from_pretrained("jinaai/jina-embeddings-v3")
model = AutoModel.from_pretrained("jinaai/jina-embeddings-v3").to(device)


class EmbReq(BaseModel):
    input: list[str]


@app.post("/v1/embeddings")
def emb(req: EmbReq):
    # Tokenize
    inputs = tokenizer(req.input, padding=True, truncation=True, return_tensors="pt").to(device)
    with torch.no_grad():
        outputs = model(**inputs)

    # Get sentence embeddings (usually use mean pooling on last_hidden_state)
    embeddings = outputs.last_hidden_state.mean(dim=1)

    # Normalize
    embeddings = torch.nn.functional.normalize(embeddings, p=2, dim=1)

    vecs = embeddings.cpu().tolist()

    return {
        "data": [
            {"embedding": v, "index": i, "object": "embedding"} for i, v in enumerate(vecs)
        ],
        "model": "jinaai/jina-embeddings-v3",
        "object": "list"
    }


if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8088)