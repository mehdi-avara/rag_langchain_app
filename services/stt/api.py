import os
import tempfile
from fastapi import FastAPI, UploadFile, File, HTTPException

import torch
import whisper

app = FastAPI(title="Local Whisper STT (GPU)")

MODEL_NAME = os.getenv("WHISPER_MODEL", "small")  # tiny/base/small/medium/large-v3
LANGUAGE = os.getenv("WHISPER_LANGUAGE", "fa")
DEVICE = os.getenv("WHISPER_DEVICE", "cuda" if torch.cuda.is_available() else "cpu")

model = whisper.load_model(MODEL_NAME, device=DEVICE)

@app.get("/health")
def health():
    return {
        "ok": True,
        "model": MODEL_NAME,
        "device": DEVICE,
        "cuda_available": torch.cuda.is_available(),
        "cuda_device": torch.cuda.get_device_name(0) if torch.cuda.is_available() else None,
    }

@app.post("/transcribe")
async def transcribe(file: UploadFile = File(...)):
    if not file.filename:
        raise HTTPException(status_code=400, detail="No file uploaded")

    suffix = os.path.splitext(file.filename)[1] or ".wav"
    with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as tmp:
        tmp_path = tmp.name
        tmp.write(await file.read())

    try:
        result = model.transcribe(tmp_path, language=LANGUAGE, fp16=(DEVICE == "cuda"))
        return {"text": (result.get("text") or "").strip()}
    finally:
        try:
            os.remove(tmp_path)
        except OSError:
            pass