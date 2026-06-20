# Phase 2 — GPU Serving Infrastructure
**Depends on: Phase 0**
**Status: Not started (only a config env-var hook exists in Phase 3 code).**

---

## Goal
Provide an automated, cost-optimized way to run the two private GPU stages
(**MinerU GPU node** then **VLM node**) against rented, non-interruptible
whole-day nodes.  The system never terminates a rented node — it reports
progress/cost and signals "safe to shut down"; you stop the node manually.

Two GPU job types run in order:
1. **MinerU node** — GPU-accelerated PDF→text/images.  Batches many PDFs; adaptive batch shrink on error.
2. **VLM node** — one VLM instance sharded across 3 GPUs (`--tensor-parallel-size 3`), quantized 8/16-bit, OpenAI-compatible endpoint.

---

## Design decisions (already resolved)

| Decision | Value |
|----------|-------|
| Rental model | Whole-day exclusive, non-interruptible |
| Teardown | Manual — code only reports "safe to shut down" |
| Weight storage | Object storage in the same region as the GPU provider (`porsa-models/<model>/<revision>/`) |
| Boot strategy | Pre-baked node image; weights mirrored to local NVMe at boot (checksum-verified) |
| VLM parallelism | One instance, 3-GPU tensor parallel |
| Quantization | 8-bit or 16-bit depending on VRAM |
| Batch checkpoint | After each batch, written to object storage |
| Resume | Re-rent the same or a new node; dispatcher reads the last checkpoint |

---

## P2.1 — Model registry + weight sync

### Object-storage layout

```
porsa-models/
  <model_slug>/
    <revision>/
      config.json
      tokenizer/
      weights/
        model-00001-of-00003.safetensors
        model-00002-of-00003.safetensors
        model-00003-of-00003.safetensors
```

`model_slug` examples: `mineru-gpu-v1`, `qwen2-vl-72b-int8`.
`revision` is a short SHA or date tag.

### Boot-time weight sync script

Create `infra/scripts/sync_weights.sh` (runs on the GPU node at boot):

```bash
#!/usr/bin/env bash
set -euo pipefail

MODEL_SLUG="${MODEL_SLUG:?MODEL_SLUG not set}"
REVISION="${REVISION:?REVISION not set}"
LOCAL_CACHE="/mnt/nvme/models/${MODEL_SLUG}/${REVISION}"
S3_PREFIX="s3://${MODEL_BUCKET:-porsa-models}/${MODEL_SLUG}/${REVISION}/"

mkdir -p "$LOCAL_CACHE"

echo "Syncing weights from $S3_PREFIX -> $LOCAL_CACHE ..."
aws s3 sync "$S3_PREFIX" "$LOCAL_CACHE" \
    --checksum-mode ENABLED \
    --no-progress \
    --endpoint-url "${S3_ENDPOINT_URL:-}"

echo "Sync complete. Cache: $LOCAL_CACHE"
```

The script runs at node boot via a `systemd` one-shot unit or in the
container's `ENTRYPOINT` before starting vLLM.  If weights are pre-baked
into the image, the sync becomes a checksum-only verify (AWS SDK skips
files whose ETag matches).

### Python helper

Create `backend/document_intelligence/services/model_registry.py`:

```python
"""Model registry helpers — used by Fleet Manager to query available models."""

from dataclasses import dataclass

@dataclass
class ModelSpec:
    slug: str
    revision: str
    s3_prefix: str          # e.g. "porsa-models/qwen2-vl-72b-int8/2025-06/"
    min_gpus: int           # number of GPUs required for tensor-parallel load
    vram_per_gpu_gb: float  # estimated VRAM per GPU
    quantization: str       # "int8", "fp16", "bf16"
    serve_command: str      # vLLM or llama.cpp launch command template

REGISTERED_MODELS: dict[str, ModelSpec] = {
    "qwen2-vl-72b-int8": ModelSpec(
        slug="qwen2-vl-72b-int8",
        revision="2025-06",
        s3_prefix="porsa-models/qwen2-vl-72b-int8/2025-06/",
        min_gpus=3,
        vram_per_gpu_gb=32.0,
        quantization="int8",
        serve_command=(
            "vllm serve {local_path} "
            "--tensor-parallel-size 3 "
            "--quantization awq "
            "--port 8000 "
            "--served-model-name di-vlm"
        ),
    ),
    "mineru-gpu-v1": ModelSpec(
        slug="mineru-gpu-v1",
        revision="2025-06",
        s3_prefix="porsa-models/mineru-gpu-v1/2025-06/",
        min_gpus=1,
        vram_per_gpu_gb=16.0,
        quantization="fp16",
        serve_command="python -m magic_pdf.service --port 8001",
    ),
}
```

---

## P2.2 — Pre-baked node images

### MinerU GPU image

Build context: `infra/docker/mineru/Dockerfile`

```dockerfile
FROM nvidia/cuda:12.1.0-cudnn8-runtime-ubuntu22.04

RUN pip install magic-pdf[gpu] torch torchvision --extra-index-url https://download.pytorch.org/whl/cu121

# Pre-bake weights (optional; can be replaced by sync_weights.sh at boot)
# COPY weights/mineru-gpu-v1/ /mnt/nvme/models/mineru-gpu-v1/

COPY infra/scripts/sync_weights.sh /entrypoint/sync_weights.sh
COPY infra/scripts/serve_mineru.sh /entrypoint/serve_mineru.sh

ENTRYPOINT ["/entrypoint/serve_mineru.sh"]
```

`serve_mineru.sh`:
```bash
#!/usr/bin/env bash
set -e
bash /entrypoint/sync_weights.sh
exec python -m magic_pdf.service --host 0.0.0.0 --port 8001
```

### VLM image (vLLM, 3-GPU tensor parallel)

Build context: `infra/docker/vlm/Dockerfile`

```dockerfile
FROM nvidia/cuda:12.1.0-cudnn8-devel-ubuntu22.04

RUN pip install vllm==0.5.0

COPY infra/scripts/sync_weights.sh /entrypoint/sync_weights.sh
COPY infra/scripts/serve_vlm.sh    /entrypoint/serve_vlm.sh

ENTRYPOINT ["/entrypoint/serve_vlm.sh"]
```

`serve_vlm.sh`:
```bash
#!/usr/bin/env bash
set -e
export MODEL_SLUG="${VLM_MODEL_SLUG:-qwen2-vl-72b-int8}"
export REVISION="${VLM_REVISION:-2025-06}"
bash /entrypoint/sync_weights.sh
LOCAL_PATH="/mnt/nvme/models/${MODEL_SLUG}/${REVISION}"
exec vllm serve "$LOCAL_PATH" \
    --tensor-parallel-size 3 \
    --quantization awq \
    --port 8000 \
    --served-model-name di-vlm \
    --host 0.0.0.0
```

**Acceptance check:** running the VLM image on a 3-GPU node and querying
`GET /v1/models` on port 8000 returns `di-vlm` as a listed model.

---

## P2.3 — Fleet Manager

### Location
`backend/document_intelligence/fleet/manager.py`

### Responsibilities
1. Given a `ModelSpec`, pick the cheapest GPU box (price data from the provider API).
2. Rent the node and boot it from the pre-baked image.
3. Health-check the endpoint (poll until the `/v1/models` or `/health` route responds).
4. Register the endpoint URL in the database / a config table for the dispatcher.
5. Report queue drain progress and cost per node-day.
6. When queue is empty or the rented day is ending: emit `"SAFE_TO_SHUTDOWN"` status — **do not terminate the node**.

### Data model addition

Add a `DIFleetNode` table (new migration):

```python
class DIFleetNode(Base):
    __tablename__ = "di_fleet_nodes"

    id = Column(Integer, primary_key=True)
    provider = Column(String, nullable=False)           # e.g. "vast.ai", "lambda"
    node_id = Column(String, nullable=False)            # provider-assigned node ID
    model_slug = Column(String, nullable=False)
    endpoint_url = Column(String, nullable=True)        # base URL once healthy
    status = Column(String, nullable=False, default="booting")
    # "booting" | "healthy" | "draining" | "safe_to_shutdown"
    rented_at = Column(DateTime, nullable=True)
    cost_per_day_usd = Column(Float, nullable=True)
    node_days_used = Column(Float, nullable=False, default=0.0)
    cost_total_usd = Column(Float, nullable=False, default=0.0)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
```

Register in `Models/__init__.py` and generate a new migration.

### Fleet Manager interface

```python
class FleetManager:
    """
    Manages one rented GPU node for the duration of a batch run.
    Pluggable provider driver: implement RentProvider for each GPU host.
    """

    def __init__(self, model_spec: ModelSpec, provider: "RentProvider"):
        self.model_spec = model_spec
        self.provider = provider

    def dry_run(self) -> dict:
        """Return estimated $/day without renting anything."""
        return self.provider.estimate_cost(self.model_spec)

    def rent_and_boot(self, db: Session) -> DIFleetNode:
        """Pick cheapest box, rent it, record node row, return node."""
        ...

    def wait_until_healthy(self, node: DIFleetNode, timeout_s: int = 600) -> None:
        """Poll the endpoint until it responds or timeout."""
        ...

    def report_progress(self, node: DIFleetNode, done: int, total: int, db: Session) -> None:
        """Update cost_total_usd and log progress."""
        ...

    def signal_safe_to_shutdown(self, node: DIFleetNode, db: Session) -> None:
        """Set status = 'safe_to_shutdown'. Do NOT call provider.terminate()."""
        node.status = "safe_to_shutdown"
        db.commit()
        logger.info(
            "NODE SAFE TO SHUT DOWN: %s (%s) — cost so far: $%.2f",
            node.node_id, node.provider, node.cost_total_usd,
        )
```

### Provider driver interface

```python
from abc import ABC, abstractmethod

class RentProvider(ABC):
    @abstractmethod
    def list_offers(self, min_gpus: int, vram_per_gpu_gb: float) -> list[dict]:
        """Return list of {node_type, price_per_day, available_count}."""

    @abstractmethod
    def rent(self, offer: dict, image_id: str, env: dict) -> str:
        """Rent the node; return provider node_id."""

    @abstractmethod
    def estimate_cost(self, spec: ModelSpec) -> dict:
        """Return {'price_per_day': float, 'node_type': str} without renting."""
```

Implement at minimum a `VastAIProvider` (or whichever provider you use).

---

## P2.4 — Resumable batch dispatcher

### Location
`backend/document_intelligence/services/batch_dispatcher.py`

### Design

Work is grouped into batches of at most `DI_BATCH_SIZE` documents (default 10).
After each batch, a checkpoint is written to object storage.  On restart, the
dispatcher reads the checkpoint and skips already-done batches.

```python
# Checkpoint key per DI job
# porsa-assets/documents/<doc_id>/di/artifacts/checkpoint.json

import json
from document_intelligence.services.storage_keys import upload_bytes, download_bytes

CHECKPOINT_KEY = "di_dispatcher/checkpoint-{run_id}.json"

def load_checkpoint(run_id: str) -> dict:
    try:
        return json.loads(download_bytes(CHECKPOINT_KEY.format(run_id=run_id)))
    except Exception:
        return {"done_doc_ids": []}

def save_checkpoint(run_id: str, done_doc_ids: list[int]) -> None:
    data = json.dumps({"done_doc_ids": done_doc_ids}).encode()
    upload_bytes(CHECKPOINT_KEY.format(run_id=run_id), data)

def dispatch_batches(
    run_id: str,
    doc_ids: list[int],
    endpoint_url: str,
    batch_size: int = 10,
) -> None:
    checkpoint = load_checkpoint(run_id)
    done = set(checkpoint["done_doc_ids"])
    remaining = [d for d in doc_ids if d not in done]

    for i in range(0, len(remaining), batch_size):
        batch = remaining[i : i + batch_size]
        process_batch(batch, endpoint_url)   # call MinerU or VLM endpoint
        done.update(batch)
        save_checkpoint(run_id, list(done))
        logger.info("Batch done: %d/%d docs", len(done), len(doc_ids))
```

---

## P2.5 — MinerU adaptive batching

When calling the MinerU GPU endpoint in batches, a single malformed or oversized
PDF can fail the whole batch.  Implement adaptive halving:

```python
def process_mineru_batch_with_retry(
    doc_ids: list[int],
    endpoint_url: str,
    min_batch_size: int = 1,
) -> tuple[list[int], list[int]]:
    """
    Process a batch, halving and retrying on failure.
    Returns (succeeded_ids, quarantined_ids).
    """
    succeeded = []
    quarantined = []

    def _try(batch: list[int]) -> None:
        if not batch:
            return
        try:
            _call_mineru(batch, endpoint_url)
            succeeded.extend(batch)
        except Exception as exc:
            if len(batch) == 1:
                logger.error("Quarantining doc %d: %s", batch[0], exc)
                quarantined.append(batch[0])
                return
            half = len(batch) // 2
            logger.warning("Batch of %d failed, halving to %d+%d", len(batch), half, len(batch)-half)
            _try(batch[:half])
            _try(batch[half:])

    _try(doc_ids)
    return succeeded, quarantined
```

---

## P2.6 — Endpoint wiring (env-var only)

The `llm_vlm_method.py` already reads the endpoint from settings:

```python
# backend/document_intelligence/services/llm_vlm_method.py
_MODEL = os.getenv("DI_LLM_MODEL", settings.openai_model)
```

And `AsyncOpenAI` is constructed with `base_url=settings.openai_base_url`.

To switch between local and rented endpoint:
```bash
# Local (dev):
DI_LLM_MODEL=llama3.2-vision
OPENAI_BASE_URL=http://localhost:11434/v1

# Rented node (production run):
DI_LLM_MODEL=di-vlm
OPENAI_BASE_URL=http://<rented-node-ip>:8000/v1
```

No code change is needed — only `.env` updates.  The Fleet Manager sets
`DIFleetNode.endpoint_url` which the operator then copies to `.env`.

---

## Tests (mandatory)

Create `backend/document_intelligence/tests/test_phase2.py`.

Required tests:
- `FleetManager.dry_run()` with a mock provider returns a `$/day` estimate — no network call.
- Checkpoint save/load round-trip via mocked object storage.
- Dispatcher with a pre-existing checkpoint skips already-done doc IDs.
- Adaptive batch: a list of 4 docs where doc #2 always fails → docs 1, 3, 4 succeed; doc 2 quarantined.
- Fleet Manager `signal_safe_to_shutdown` sets `DIFleetNode.status = "safe_to_shutdown"` and does **not** call `provider.terminate()`.

---

## Acceptance checklist

- [ ] Dry-run estimates `$/day` for the target model without renting anything.
- [ ] A real or simulated boot produces a `DIFleetNode` row with `status = "healthy"` and a non-empty `endpoint_url`.
- [ ] Killing the dispatcher mid-run and restarting resumes from the last saved checkpoint.
- [ ] A batch containing one bad PDF still processes all good PDFs; bad PDF is quarantined with a logged error.
- [ ] `signal_safe_to_shutdown` emits the log message and sets the node row status; the node is NOT terminated by code.
- [ ] Switching between local and rented endpoint requires only env-var changes.
