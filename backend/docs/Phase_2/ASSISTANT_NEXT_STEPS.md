# Assistant Next Steps

This file tracks planned assistant improvements that are not part of the current
implemented baseline.

## LLM Relevance Judge For Reference Candidates

### Problem

The assistant currently resolves FK-like references by:

1. Calling the owning module's existing search service.
2. Getting candidate rows.
3. Applying deterministic plausibility checks.
4. Returning `resolved`, `ambiguous`, or `missing`.

This is safe, but it can be too conservative for real operations data.

Example user request:

```text
چسب belzona مدل m22
```

If search returns unrelated weak candidates such as:

```text
32412312 - test - material
LEGACY-WI-1 - Legacy tewtwe tetw #C77700 - material
```

the assistant should not ask the user to choose from those records. It should
mark the item as `missing` and offer create/search-again.

The deterministic filter now handles this safer behavior, but it may reject
valid semantic matches when names are noisy, multilingual, abbreviated,
transliterated, or model-number-heavy.

### Desired Improvement

Add an optional LLM relevance judge after module search.

The LLM should judge only the top server-provided candidates, usually top 5.
It must not search independently and must not invent ids.

Flow:

1. Module search returns top candidates using existing search services.
2. Deterministic filter removes obvious garbage.
3. If uncertain, send the raw user reference and top candidates to the LLM.
4. LLM returns strict JSON.
5. Server validates that any chosen id exists in the candidate list.
6. Server maps the result to existing reference statuses:
   - `resolved`
   - `ambiguous`
   - `missing`

### Strict JSON Output

```json
{
  "status": "resolved",
  "chosen_id": 42,
  "reason": "Candidate contains Belzona M22 adhesive."
}
```

Allowed statuses:

- `resolved`: exactly one candidate clearly matches the user request.
- `ambiguous`: multiple candidates are plausible and the user must choose.
- `missing`: none of the candidates are good enough.

For missing:

```json
{
  "status": "missing",
  "chosen_id": null,
  "reason": "None of the candidates mention Belzona, adhesive, or M22."
}
```

For ambiguous:

```json
{
  "status": "ambiguous",
  "chosen_id": null,
  "reason": "Two candidates mention Belzona M22 but differ by package size."
}
```

### Server-Side Safeguards

The LLM relevance judge must be advisory only.

Required safeguards:

- LLM may only choose ids from the candidate list.
- If `chosen_id` is not in the candidate list, ignore the LLM result.
- If JSON is malformed, fall back to deterministic resolver behavior.
- If LLM says `resolved` without a valid `chosen_id`, treat as `missing`.
- If LLM says `ambiguous`, expose only server-provided candidates as alternatives.
- Never let the LLM create arbitrary ids.
- Never let this step commit writes.
- Preserve caller RBAC.
- Keep draft payload keys in English.

### Prompt Shape

The prompt should make clear that the model is judging relevance only:

```json
{
  "raw_reference": "چسب belzona مدل m22",
  "resource_type": "material_item",
  "candidates": [
    {
      "id": 11,
      "label": "32412312 - test - material",
      "data": {
        "item_code": "32412312",
        "name": "test",
        "item_type": "material"
      }
    },
    {
      "id": 42,
      "label": "BEL-M22 - Belzona M22 adhesive",
      "data": {
        "item_code": "BEL-M22",
        "name": "Belzona M22 adhesive",
        "item_type": "material"
      }
    }
  ]
}
```

Expected result:

```json
{
  "status": "resolved",
  "chosen_id": 42,
  "reason": "Candidate 42 matches Belzona M22 adhesive."
}
```

### Integration Point

Likely integration point:

```text
backend/assistant/resolve.py
```

Add this as an optional second-stage resolver after deterministic candidate
filtering and before returning final `ReferenceResolution`.

This should remain generic and module-agnostic. Module adapters should continue
to provide candidates through `ResourceSpec` providers.

### Tests To Add

Add focused tests for:

- LLM chooses one valid id from top candidates -> `resolved`
- LLM returns `missing` for weak candidates -> `missing` with create suggestion
- LLM returns `ambiguous` -> alternatives are exposed
- LLM invents id not in candidates -> fallback / reject
- malformed JSON -> fallback / reject
- no model call when deterministic exact match is enough
- no model call when there are zero candidates
- Persian raw reference with mixed Latin brand/model text
- graph still returns `partial_draft` for unresolved references
- graph still never commits writes

### Current Baseline Until This Is Implemented

Current behavior is conservative:

- exact match resolves
- one plausible candidate resolves
- multiple plausible candidates become ambiguous
- weak unrelated candidates become missing
- missing creatable resources include `create_suggestion`

This is safe for drafts, but may ask users to create/search again more often than
necessary until the LLM relevance judge is added.
