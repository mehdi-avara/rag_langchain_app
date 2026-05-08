from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
import json


ERROR_LOG_PATH = Path(__file__).resolve().parent / "embedding_errors.log"


@dataclass
class EmbeddingErrorRecord:
    error_code: str
    error_type: str
    error_text: str
    context: str


class EmbeddingErrorRegistry:
    EMBEDDING_UNAVAILABLE = "EMBEDDING_UNAVAILABLE"
    EMBEDDING_BAD_RESPONSE = "EMBEDDING_BAD_RESPONSE"
    EMBEDDING_CONFIGURATION_CHANGED = "EMBEDDING_CONFIGURATION_CHANGED"


def log_embedding_error(record: EmbeddingErrorRecord) -> None:
    ERROR_LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "error_code": record.error_code,
        "error_type": record.error_type,
        "error_text": record.error_text,
        "context": record.context,
    }
    with ERROR_LOG_PATH.open("a", encoding="utf-8") as f:
        f.write(json.dumps(payload, ensure_ascii=False) + "\n")
