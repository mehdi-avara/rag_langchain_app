# Phase 8 — Evaluation + Report
**Depends on: Phase 5 AND Phase 7**
**Status: Not started.**

---

## Goal
Compare all three methods on a labeled evaluation dataset, measure the cost/quality
tradeoff, and produce a reproducible academic report.  This phase is the academic
deliverable — it proves which method is best for which situation.

---

## Research questions

1. Which method best detects document boundaries in mixed technical PDFs?
2. Which method best classifies page ranges into tags/models/process parts?
3. What is the accuracy ↔ latency ↔ cost tradeoff per method?
4. Do the lightweight students match the teacher well enough to run GPU-free on most documents?

---

## Evaluation dataset

Create a labeled dataset of at least 20 mixed PDFs covering:
- Simple single-document PDFs (baseline).
- Scanned multi-page PDFs (OCR path).
- Multi-instrument PDFs (several manuals concatenated).
- PDFs with unknown models (no match in `managed_models`).

For each PDF, the ground truth is:
- True page ranges (where each logical document starts/ends).
- True document type per range.
- True tags and managed models per range.

Store the dataset in `tests/di_eval_dataset/` as:
```
tests/di_eval_dataset/
  doc_001.pdf
  doc_001_labels.json   # {page_ranges: [{start,end,type,tags,models}]}
  doc_002.pdf
  doc_002_labels.json
  ...
  dataset_index.json    # [{doc_id, filename, category}]
```

---

## P8.1 — Evaluation harness

### Location
`backend/document_intelligence/eval/eval_harness.py`

### Metrics per method

| Metric | Formula | Unit |
|--------|---------|------|
| Boundary precision | TP / (TP + FP) at page level | 0–1 |
| Boundary recall | TP / (TP + FN) at page level | 0–1 |
| Boundary F1 | 2·P·R/(P+R) | 0–1 |
| Type accuracy | (correctly typed segments) / (total segments) | 0–1 |
| Tag precision/recall | standard IR P/R over tag sets | 0–1 |
| Model precision/recall | standard IR P/R over model IDs | 0–1 |
| Processing time | wall-clock seconds per page | s/page |
| Cost per document | `node_cost_per_day × (pages / pages_per_day)` | USD |

### Run the harness

```python
# eval_harness.py
import json, time
from pathlib import Path
from document_intelligence.services.pdf_artifacts import process_page_artifacts
from document_intelligence.services.image_method import run_image_method
from document_intelligence.services.embedding_method import run_embedding_method
from document_intelligence.services.llm_vlm_method import run_llm_vlm_pipeline

DATASET_DIR = Path("tests/di_eval_dataset")


def run_eval(db, company_id: int) -> dict:
    index = json.loads((DATASET_DIR / "dataset_index.json").read_text())
    results = {"image": [], "embedding": [], "teacher": []}

    for entry in index:
        labels = json.loads((DATASET_DIR / entry["labels_file"]).read_text())
        doc = _get_or_create_eval_doc(db, entry)

        # Build artifacts (Phase 1)
        artifacts = process_page_artifacts(db, doc, force=False)
        db.commit()

        # Run each method and time it
        for method_name, run_fn in [
            ("image", lambda: run_image_method(doc.id, artifacts)),
            ("embedding", lambda: run_embedding_method(doc.id, artifacts, db, company_id)),
            ("teacher", lambda: _run_teacher(db, doc, artifacts)),
        ]:
            t0 = time.monotonic()
            try:
                canonical = run_fn()
                elapsed = time.monotonic() - t0
                metrics = _compute_metrics(canonical, labels, elapsed, method_name)
                results[method_name].append(metrics)
            except Exception as e:
                results[method_name].append({"error": str(e), "doc": entry["doc_id"]})

    return _aggregate(results)


def _compute_metrics(canonical, labels, elapsed_s, method_name) -> dict:
    true_ranges = {(r["start"], r["end"]) for r in labels["page_ranges"]}
    pred_ranges = {(s.start_page, s.end_page) for s in canonical.segments}

    # Boundary-level TP/FP/FN
    true_boundaries = {r["start"] - 1 for r in labels["page_ranges"] if r["start"] > 1}
    pred_boundaries = {s.start_page - 1 for s in canonical.segments if s.start_page > 1}

    tp = len(true_boundaries & pred_boundaries)
    fp = len(pred_boundaries - true_boundaries)
    fn = len(true_boundaries - pred_boundaries)

    precision = tp / (tp + fp) if (tp + fp) > 0 else 1.0
    recall    = tp / (tp + fn) if (tp + fn) > 0 else 1.0
    f1        = 2 * precision * recall / (precision + recall) if (precision + recall) > 0 else 0.0

    n_pages = max(s.end_page for s in canonical.segments) if canonical.segments else 1

    return {
        "method": method_name,
        "boundary_precision": round(precision, 4),
        "boundary_recall": round(recall, 4),
        "boundary_f1": round(f1, 4),
        "n_segments_pred": len(pred_ranges),
        "n_segments_true": len(true_ranges),
        "elapsed_s": round(elapsed_s, 2),
        "s_per_page": round(elapsed_s / n_pages, 4),
    }


def _aggregate(results: dict) -> dict:
    summary = {}
    for method, rows in results.items():
        valid = [r for r in rows if "error" not in r]
        if not valid:
            summary[method] = {"error": "all runs failed"}
            continue
        summary[method] = {
            "boundary_f1_mean":       round(sum(r["boundary_f1"] for r in valid) / len(valid), 4),
            "boundary_precision_mean": round(sum(r["boundary_precision"] for r in valid) / len(valid), 4),
            "boundary_recall_mean":    round(sum(r["boundary_recall"] for r in valid) / len(valid), 4),
            "s_per_page_mean":         round(sum(r["s_per_page"] for r in valid) / len(valid), 4),
            "n_docs": len(valid),
        }
    return summary
```

### CLI entry point

```
python -m document_intelligence.eval.eval_harness --output eval_report.json
```

The command runs all three methods on the full dataset and writes a JSON report
that can be converted to a table in the academic write-up.

### Cost per document estimate

For the teacher (VLM on rented GPU):
```python
GPU_COST_PER_DAY_USD = float(os.getenv("DI_GPU_COST_PER_DAY", "100.0"))
GPU_DOCS_PER_DAY     = float(os.getenv("DI_GPU_DOCS_PER_DAY",  "200.0"))

cost_per_doc = GPU_COST_PER_DAY_USD / GPU_DOCS_PER_DAY
```

For the students (CPU-only):
- Image method: negligible (PIL + hashlib).
- Embedding method: embedding API cost or local model electricity cost.

Include cost estimates in the report.

---

## P8.2 — Final report + docs

### Report structure

Write `docs/DI_EVALUATION_REPORT.md` with:

1. **Introduction** — problem statement (mixed PDF segmentation), corpus description,
   three methods overview.
2. **Evaluation dataset** — doc count per category, page count distribution, annotation process.
3. **Results table** — boundary P/R/F1, type accuracy, tag precision/recall,
   model precision/recall, processing time per page, cost per document for each method.
4. **Discussion** — where the teacher beats students and why; cost/quality tradeoff;
   at what confidence threshold students are reliable.
5. **Infrastructure runbook** — how to rent a node, load weights, run batches, shut down.
6. **Distillation results** — before/after student agreement with teacher and with humans.
7. **Conclusion** — recommended operating mode (teacher only / teacher + students / students-only above threshold).

### Implementation docs

Write `docs/document_intelligence/RUNBOOK.md` covering:
- How to start a DI job from the API.
- How to run the fleet batch for a large backlog.
- How to check progress and identify the "safe to shut down" signal.
- How to review and accept segments in the API.
- How to trigger re-distillation after accumulating human corrections.
- Environment variables reference (`DI_LLM_MODEL`, `DI_LLM_VISION_ENABLED`,
  `DI_IMAGE_BOUNDARY_THRESHOLD`, `DI_EMBED_BOUNDARY_THRESHOLD`,
  `DI_MERGE_MIN_VOTES`, `DI_TEACHER_WEIGHT`, `DI_SKIP_TEACHER_THRESHOLD`,
  `DI_GPU_COST_PER_DAY`, `DI_GPU_DOCS_PER_DAY`).

---

## Tests (mandatory)

Create `backend/document_intelligence/tests/test_phase8.py`.

Required tests:
- `_compute_metrics` with perfect prediction (pred == true) → F1 = 1.0.
- `_compute_metrics` with no predicted boundaries but true has 2 → recall = 0.0, precision = 1.0.
- `_aggregate` with 2 docs per method → means computed correctly.
- CLI dry-run on the 1-doc fixture → JSON output file written with `boundary_f1` key.

---

## Acceptance checklist

- [ ] `python -m document_intelligence.eval.eval_harness` runs without error on the eval dataset.
- [ ] Output JSON contains per-method `boundary_f1_mean`, `s_per_page_mean`, and doc count.
- [ ] Report compares all three methods in a side-by-side table.
- [ ] Report includes cost per document for each method.
- [ ] Report documents the threshold above which students run GPU-free.
- [ ] `RUNBOOK.md` covers the full operator workflow from job creation to node shutdown.
- [ ] All tests pass.
