# Reference (FK) Resolution + Existence Lookups — PR notes

Implements `fk_resolution_implementation_prompt.md`. No DB migration: all new persisted
data lives inside the existing `Draft.validation` JSON column.

## What changed (backend)

- **`financial_management/search/service.py`** — extracted the card/customer search out of the
  route handlers into interface functions `search_card_hits()` / `search_customer_hits()`. The
  `/cards/search` and `/customers/search` routes now delegate to them (offset/limit windowing kept
  in the route, so responses are byte-for-byte identical).
- **`assistant/module_interface.py`** (new) — `Candidate`, the `SearchProvider` protocol, the
  in-process `FunctionSearchProvider`, `ResourceSpec`, and the resource registry. A future
  `HttpSearchProvider` implements the same `.search(...)` and is registered instead — no caller
  changes.
- **`assistant/resolve.py`** (new) — pure `resolve_reference` (ranking) + `resolve_field`
  (explicit-id short-circuit → RBAC → provider search → create-suggestion).
- **`assistant/registry.py`** — `DraftData.references`.
- **`assistant/schemas.py` / `service.py` / `routes.py`** — `DraftPatchRequest.resolved_references`
  and the create-callback in `patch_draft` (writes the reported id into the payload, flips the
  reference to `resolved`, clears it from `references_pending`).
- **`assistant/runner.py`** — `_build_context` now also renders generic lookup items by label.
- **`assistant/router.py`** — prompt rule: never invent ids; pass text into `credit_card_query` /
  `customer_query` / `counterparty`.
- **`financial_management/assistant_tools.py`** — registers the `financial_card` / `financial_customer`
  resources, wires resolution into create/update-receipt builders, and adds `lookup_customer` /
  `lookup_card` read intents.

## Frontend contract

Each draft now carries `validation.references` (array) and `validation.references_pending` (array of
field names not yet settled). Each reference:

```json
{
  "field": "credit_card_id",
  "raw": "Ali's Mellat card",
  "status": "resolved | ambiguous | missing",
  "chosen": { "id": 12, "label": "Mellat — Bank Mellat — ••••4821 — Ali Rezaei" },
  "alternatives": [ { "id": 19, "label": "…" } ],
  "create_suggestion": {
    "resource": "financial_customer", "method": "POST",
    "endpoint": "/financial_management/customers",
    "permission": "financial_management:customers:create",
    "payload": { "name": "Ali Rezaei" }
  },
  "note": null
}
```

Behavior:
- **`resolved`** → show `chosen.label`; the id is already in `draft.payload`. Allow override via
  `alternatives`.
- **`ambiguous`** → show `chosen` as default + `alternatives`; on pick, PATCH the draft with
  `resolved_references: { "<field>": { "id": <picked>, "label": "<picked label>" } }`.
- **`missing`** → offer "create" using `create_suggestion` (call that endpoint), then PATCH the draft
  with `resolved_references: { "<field>": { "id": <new id>, "label": "<new label>" } }`.
- **Do not allow commit while `references_pending` is non-empty.**

A draft with pending references is still emitted as **valid** (persisted + streamed); the frontend
settles every pending reference before committing to the module's own endpoint.

## Tests

`backend/assistant/tests/test_resolve.py`, `test_resolve_receipt_builders.py`,
`test_resolve_callback_and_lookups.py`, plus updates to `fakes.py` and `test_build_drafts.py`.

Run the assistant suite and the financial suites separately — `test_runner_streaming.py` installs a
fake `routs.chat` into `sys.modules`, which shadows the real module for any later-collected test that
imports `from routs.chat import router` (pre-existing isolation quirk, not introduced here):

```
pytest assistant/tests/
pytest financial_management/tests/ tests/test_phase1_search_ask_contracts.py
```
