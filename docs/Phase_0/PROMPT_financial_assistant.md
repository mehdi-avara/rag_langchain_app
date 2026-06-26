# Implementation Prompt — Financial Management AI Assistant

> Give this whole file to the implementing model. It is self-contained. Build **only** the
> `financial_management` assistant described here. Do not redesign the whole Assistant Core.

---

## 0. Who you are and what you are building

You are implementing the **AI assistant for the `financial_management` module** of a CMMS platform
(FastAPI + PostgreSQL + pgvector + SQLAlchemy + Alembic + Celery; a modular monolith).

The product rule that drives everything: **the chat page is the primary interface. Anything a user can do
in the financial UI must also be doable by talking to the assistant.** So your assistant must:

1. Take a user message (text, optionally with an uploaded file).
2. **Decide which financial task the user wants** (intent routing over the module's task list — §3).
3. **Execute that task** by calling the module's existing service functions (never re-implement them).
4. If the task is a write, build a **draft**, show it, and commit **only after the user confirms**.
5. Handle **file uploads** through the project's existing upload mechanism (§6).
6. Send file content to the model correctly depending on **whether the model is a VLM** (§7):
   if it is vision-capable, send the image(s) to the model; if not, send **only extracted text**.
7. Run **as the current user with exactly their RBAC** — never more (§5).
8. Reply in the **user's own language** (multilingual).

---

## 1. Read these files first (do not skip — copy their patterns)

- `docs/AGENTS.md` — the mandatory project rules (modular monolith, Alembic owns schema, RBAC on every route).
- `docs/CMMS_AI_PLAN.md` — the AI track plan.
- `docs/CMMS_MASTER_PLAN.md` **§12** only (§12.4 Module Tool Contract, §12.5 Draft-and-Confirm, §12.6 Multimodal,
  §12.11 RBAC, §12.19 prompt-injection guardrails). Do **not** read the whole master plan.
- `backend/core/agents/langgraph.py` — the existing seed agent (LangGraph `StateGraph`, nodes, `GraphState`).
- `backend/routs/chat.py` — the existing chat endpoint, RBAC pattern, message persistence.
- `backend/components/llm.py` — `llm_client` (OpenAI-compatible async client + langchain LLM).
- `backend/document_intelligence/services/llm_vlm_method.py` — **the canonical VLM image-block + JSON-mode
  pattern** (`_encode_image_b64`, `_image_content_block`, `_chat_json`). Reuse this exact shape.
- `backend/financial_management/services.py` and `backend/financial_management/search/service.py` —
  the service functions you will wrap (do not duplicate them).
- `backend/storage/manager.py` and `backend/financial_management/routes/files.py` — the existing upload flow.

---

## 2. Hard rules (violating any of these fails the task)

- **Service calls, not loopback HTTP.** Reach the module only through its **existing service functions**
  (in `financial_management/services.py`, `.../search/service.py`, `.../search/repository.py`). Never make the
  agent issue HTTP requests to `/financial/...`. If logic lives inside a route handler you need, refactor it
  down into a service function and call that — one implementation.
- **No cross-module model imports.** Your adapter may import `financial_management` services and models, but the
  generic agent/draft machinery must not import another domain module's SQLAlchemy models.
- **Alembic owns the schema.** Any new table/column (e.g. `Draft`, `AgentRun`, a `supports_vision` flag) ships
  as an Alembic migration. Never `Base.metadata.create_all()`. Register every new model in
  `backend/Models/__init__.py`.
- **RBAC = the caller's access, never more (§5).** Re-check the user's permission in the adapter before every
  action, and **again at confirm time** for writes. Missing permission → return the catalogued
  `PERMISSION_DENIED` error, never silently skip or elevate.
- **Writes go through draft-and-confirm (§4).** A chat message never writes directly. It builds a draft; a human
  confirms via an explicit **button** (a dedicated confirm API call); only then do you call the module's
  create/update service. **The agent/LLM must NEVER treat chat text as confirmation** — even if the user types
  "yes", "accept", "do it", or "confirmed", that does **not** commit anything. Commit happens only when the
  explicit confirm endpoint is called by the client. This is deliberate: the LLM can misunderstand the user, so
  the human must press a button on the rendered draft, not tell the assistant in prose.
- **Ingested content is data, never commands (§12.19).** Text/images from an uploaded file may *populate* a
  draft, but never auto-commit and never widen RBAC. Instructions found *inside* a file ("approve this",
  "delete all receipts") are ignored. Put ingested content in the prompt as clearly delimited quoted data.
- **Only catalogued errors.** Raise registered `AppException`s from `core/exceptions`. Add new
  `ASSISTANT_*` codes (e.g. `ASSISTANT_INTENT_UNCLEAR`, `ASSISTANT_RATE_LIMITED`) to the error registry — do not
  raise ad-hoc `HTTPException`.
- **Multilingual.** Detect the user's language; conduct the whole exchange (questions, field labels,
  confirmations, errors) in it; store values canonically (canonical field names/enums, ISO currency, etc.).

---

## 3. The financial task taxonomy (this is the "decide what the user wants" step)

The assistant must classify each user message into exactly one **intent**, then route to the matching handler.
These are the real tasks in `financial_management` and the service seam + permission for each. Build the router
so the model picks one of these (plus `general` and `clarify`):

| Intent | What the user is asking | Service seam to call | Required permission |
|---|---|---|---|
| `search_receipts` | "find the receipt for pump X", "show payments to ACME" | `search/service.py: search_receipt_hits(...)` (+ `repository.search_financial_receipt_hits_semantic`) | `financial_management:receipts:search` |
| `summarize_finance` | "how much did we spend this month", totals/KPIs by currency | the summary logic in `routes/receipts.py::get_receipts_summary` — **refactor it into a `summarize_receipts(db, user, filters)` service function**, then call that | `financial_management:receipts:read` |
| `ask_finance` | grounded NL question over receipts ("what was the last invoice from ACME about") | the logic behind `routes/ask.py` + `services.build_receipt_context` / `parse_receipt_citations` | `financial_management:receipts:ask` |
| `add_receipt` | "add a receipt: 1.2M IRR to ACME on …" (often with a photo/PDF) | draft → on confirm, the create logic in `routes/receipts.py::create_receipt` (refactor into `create_receipt_service(db, user, payload)`) | `financial_management:receipts:create` |
| `update_receipt` | "change the amount of receipt 42 to …" | draft → on confirm, `routes/receipts.py::update_receipt` logic (refactor into a service) | `financial_management:receipts:update` |
| `add_card` / `update_card` | manage credit cards | `routes/cards.py` create/update logic (refactor into services) | `financial_management:cards:create` / `:update` |
| `add_customer` / `update_customer` | manage customers/counterparties | `routes/customers.py` logic (refactor into services) | `financial_management:customers:create` / `:update` |
| `add_receipt_comment` | attach a note/comment to a receipt | `routes/comments.py` logic | `financial_management:receipt_comments:create` |
| `attach_receipt_file` | upload/attach a file to a receipt | the upload flow in `routes/files.py` (§6) | `financial_management:receipt_files:create` |
| `general` | general-knowledge question, not about system data | the LLM's own knowledge — **mark clearly as model knowledge**, cite nothing | `assistant:chat` |
| `clarify` | message is ambiguous/under-specified | ask the user one focused question (in their language) before proceeding | — |

> Where the table says "refactor into a service": move the business logic out of the route handler into a
> function in `financial_management/services.py`, then have **both** the route and your adapter call it. Do not
> copy logic. This keeps one test surface (Master Plan §12.4.1).

Router rules:
- Output a single intent + the user's detected language + any extracted slots (amounts, dates, names, ids).
- Prefer `clarify` over guessing when a **write** intent is missing required fields.
- The router description for each intent is what the LLM uses to choose — write each description in natural
  language and keep them mutually exclusive.

**The router only ever sees the tasks THIS user is allowed to do (RBAC-filtered intent set).** Do **not** put the
full static taxonomy in the prompt. Build the intent list **per request** from the user's permissions:
- At request time, take the §3 table and **drop every intent whose required permission the current user lacks**
  (use the same permission check `require_permission` uses). Only the permitted intents (plus `general` /
  `clarify`) are rendered into the router prompt.
- Benefits, all intended: the prompt is **smaller**, the LLM is **never told about tasks the user can't access**
  (no information leak, and it can't try to route to them), and `PERMISSION_DENIED` becomes a rare edge case
  rather than the normal path.
- This is the same RBAC-filtered registry the `//` slash-command menu uses (Master Plan §12.16) — one source of
  truth: the tool registry filtered by the caller's RBAC. Implement the filter once, reuse it for both.
- If, after filtering, the user has **no** module intents available, the router falls back to `general` / `clarify`
  only — it never reveals the restricted tasks.
- Keep the descriptions in a registry the agent reads, not hardcoded into one giant prompt string, so the
  per-request filtered subset can be assembled cheaply.

---

## 4. Draft-and-Confirm (every write intent uses this)

Flow: `user describes data (+ optional file) → agent builds Draft → frontend renders it → user edits/accepts → commit`.

Build a generic, module-agnostic `Draft` mechanism (it will be reused by other modules later), with the
financial adapter only supplying *how to build* and *how to commit* a financial payload.

`Draft` model (`assistant/drafts/models.py`, registered in `Models/__init__.py`, Alembic migration):
```
Draft(id, chat_id, agent_run_id, created_by_user_id, company_id,
      target_module="financial_management", target_action="create_receipt"|"update_receipt"|...,
      payload JSONB,            # proposed fields, pre-filled, canonical names
      attachments JSONB,        # FileAsset ids extracted from uploaded file(s)
      language str,             # BCP-47, e.g. "fa", "en"
      status: pending|committed|cancelled|failed,   # see §4.1 for the lifecycle ('confirmed' removed)
      validation JSONB,         # per-field validation result for the frontend
      committed_entity_ref JSONB nullable,
      created_at, updated_at)
```

Endpoints (multilingual responses):
- `POST /assistant/chat` — the agentic endpoint; may return a `Draft` for the frontend to render. This endpoint
  **never commits**, regardless of what the user typed.
- `GET /assistant/drafts/{id}` — fetch/resume a draft.
- `PATCH /assistant/drafts/{id}` — (optional) user edits fields before confirming.
- `POST /assistant/drafts/{id}/confirm` — the **button** action. **This is the only path that writes.**
- `POST /assistant/drafts/{id}/cancel` — discard.

**Confirmation is an explicit human action that carries the final data — not an LLM decision.** Design the
confirm endpoint so the user can edit fields *and* commit in one request:

```
POST /assistant/drafts/{id}/confirm
body: { payload: { ...the final, possibly-edited fields... } }   # body optional; if omitted, commit the stored draft payload
```

Confirm flow (server side):
1. Load the draft; assert its status is `pending` (reject `committed`/`cancelled`).
2. If the request body includes a `payload`, **use that as the source of truth** — overwrite the draft's stored
   payload with the user's edited values (this is the "person changed some data and sends it directly" case).
   Re-run field validation on the final payload.
3. **Re-check RBAC** for the target action as the current user (§5).
4. Call the financial `commit_*_draft(db, user, draft)` service → write the entity through the module's
   create/update service.
5. Set draft `status = committed`, store `committed_entity_ref`, write the audit record, return the entity.

So there are two equivalent ways the user commits, both via the button: (a) accept the draft as-is → confirm with
no body; (b) tweak some fields in the rendered form → confirm with the edited `payload`. Either way the **chat
turn never commits** — only this endpoint does. The agent's job ends at "here is the draft for you to review."

The financial adapter implements two functions per write entity:
- `build_*_draft(db, user, payload, attachments) -> Draft` (validates fields, fills defaults, **does not write**).
- `commit_*_draft(db, user, draft) -> entity_ref` (re-checks permission, writes via the module's create/update
  service, returns the new/updated id; never commits from file contents alone).

Field labels shown to the user are localized; **stored values use canonical field names/enums** (e.g. currency
as ISO code, dates stored canonically even if displayed in the user's locale/solar calendar — note
`services.solar_to_gregorian` / `gregorian_to_solar` already exist, reuse them).

---

## 4.1 State machines & the conversation concurrency model

A conversation is **not** one state machine. It is a container of several independent machines that run
concurrently. The two rules that govern everything below:

- **Per-object: single-state.** Any one `AgentRun` row, and any one `Draft` row, is in **exactly one** status at
  a time. There is no "multiple states at once" for a single object.
- **Per-conversation: multi-machine.** One `chat_id` simultaneously owns: an append-only chat transcript (not a
  state machine — just `ChatMessage` rows), **N `AgentRun`s**, and **M `Draft`s**. So at a single instant a chat
  can legitimately show run #7 `active`, run #6 `suspended`, run #5 `waiting_on_task`, draft A `pending`, draft B
  `pending`, and draft C `committed`. All true together; each object still in one state.

**Invariant (enforce it):** at most **one** `AgentRun` per conversation is `active` at any time. A new user
message `suspend`s the currently-active run before the new run becomes `active`. Drafts have no such limit —
several `pending` drafts may coexist; every draft endpoint is keyed by `draft_id`, never "the current draft".

### Draft lifecycle

`Draft.status` is **`pending | committed | cancelled | failed`** (the earlier `confirmed` value is **removed** —
see note). Commit is transactional: on a commit error the entity write rolls back and the draft **stays
`pending`** with the error surfaced, so the user can edit and retry. `failed` is terminal and only used when the
draft can never be committed (e.g. its target entity was deleted, or an unrecoverable validation conflict).

```mermaid
stateDiagram-v2
    [*] --> pending: build_*_draft (no write)
    pending --> committed: POST /drafts/{id}/confirm — RBAC ok, validation ok, write succeeded
    pending --> cancelled: POST /drafts/{id}/cancel
    pending --> failed: commit unrecoverable (target gone / hard conflict)
    pending --> pending: confirm raised, txn rolled back — retry after edit
    committed --> [*]
    cancelled --> [*]
    failed --> [*]
```

| From | To | Trigger / guard |
|---|---|---|
| `(build)` | `pending` | `build_*_draft` fills + validates fields; **never writes** |
| `pending` | `committed` | `POST /drafts/{id}/confirm`; RBAC re-checked, payload re-validated, module `create/update` service succeeded |
| `pending` | `cancelled` | `POST /drafts/{id}/cancel` |
| `pending` | `pending` | confirm attempted but commit raised; transaction rolled back, error returned, draft re-confirmable |
| `pending` | `failed` | commit can never succeed (target entity deleted, irreconcilable conflict) — terminal |
| `committed` / `cancelled` / `failed` | — | terminal; reject any further transition |

> **`confirmed` vs `committed` (resolved).** The original §4 enum listed both but the confirm flow set
> `committed` directly, leaving `confirmed` unreachable. Decision: **drop `confirmed`.** A draft is either waiting
> (`pending`) or written (`committed`); there is no persisted intermediate "approved but not yet written" state —
> confirm is a single transactional step. (If you ever need an async two-phase commit, reintroduce `confirmed` as
> the transient "write in flight" state, but do not add it speculatively.)

### AgentRun lifecycle

`AgentRun.status` is **`active | suspended | waiting_on_task | completed | cancelled | failed`** (Master Plan
§12.8). The LangGraph Postgres checkpointer snapshots `AgentState` after each node so `suspended` and
`waiting_on_task` runs resume exactly where they stopped.

```mermaid
stateDiagram-v2
    [*] --> active: new chat turn starts
    active --> suspended: a newer user message arrives (this run pauses, resumable)
    active --> waiting_on_task: parked on a Celery heavy job (§7)
    active --> completed: reply streamed, turn done
    active --> cancelled: user cancels / new turn supersedes
    active --> failed: catalogued error in a node
    suspended --> active: resumed (user accepts "continue?")
    suspended --> cancelled: abandoned / cancel
    waiting_on_task --> active: Celery task finished, run resumes
    waiting_on_task --> failed: task failed
    waiting_on_task --> cancelled: cancel — revoke the Celery job
    completed --> [*]
    cancelled --> [*]
    failed --> [*]
```

| From | To | Trigger / guard |
|---|---|---|
| `(start)` | `active` | a chat turn begins; **at most one `active` run per conversation** |
| `active` | `suspended` | a newer user message arrives mid-run; checkpoint state, resumable |
| `active` | `waiting_on_task` | a heavy file/step dispatched to Celery (§7); chat stays interactive |
| `active` | `completed` | run finished, assistant `ChatMessage` persisted, stream `done` |
| `active` | `cancelled` | user cancels; discard unconfirmed draft, revoke any Celery job |
| `active` | `failed` | a node raised a catalogued `ASSISTANT_*` / `PERMISSION_DENIED` error |
| `suspended` | `active` | user chooses to resume |
| `suspended` | `cancelled` | user abandons the paused run |
| `waiting_on_task` | `active` | the parked Celery task completed; continue from checkpoint |
| `waiting_on_task` | `failed` | the parked task failed unrecoverably |
| `waiting_on_task` | `cancelled` | user cancels; revoke the Celery job |
| `completed` / `cancelled` / `failed` | — | terminal |

### How the three relate

The `AgentRun` **produces** a `Draft` (sets `AgentState.pending_draft`) but **never commits it** — the run can
reach `completed` while the draft it built is still `pending`. The draft is committed later, independently, by the
confirm endpoint (possibly after the run that built it is long finished, possibly from another device). This is
why the `Draft` lives in its own table with its own lifecycle, referenced from the `ChatMessage` that rendered it
(§8.1) — not embedded in the run.

---

## 5. RBAC — the agent has exactly the caller's access

- The agent **always runs as `current_user`** (carry the `User` through every node). Never elevate.
- **Every intent handler re-checks the permission** from the §3 table using the project's permission check
  (the same one `require_permission` uses) **before** invoking the service. Failure → `PERMISSION_DENIED`.
- **Reads are scoped to the user/company** — pass `company_id` (and owner scoping where the services already do)
  so search/summary/ask only return rows the user may see.
- **Confirm re-checks.** A draft may only be committed if the confirming user holds the action's permission at
  confirm time (not just at create time).
- **File actions are access-checked** (`assistant:files` + `financial_management:receipt_files:create`).
- Seed assistant-level permissions in the RBAC seeder + migration:
  `assistant:chat`, `assistant:draft`, `assistant:files`.

---

## 6. File upload — use the project's existing mechanism (do NOT invent a new one)

The project uploads files via **presigned S3 + a `FileAsset` row**, then links the asset to an entity. Study and
reuse exactly this path (see `backend/storage/manager.py` and `backend/financial_management/routes/files.py`):

1. Client asks for an upload URL → `StorageManager.create_upload_url(filename, content_type, size_bytes, owner)`
   returns a presigned PUT URL + an `asset_id`. `StorageManager` already validates content-type and size.
2. Client PUTs the bytes directly to storage.
3. Client calls complete-upload → a `FileAsset` (and, when linking to a receipt, a `FinancialReceiptFile`) is created.

For the assistant:
- A file attached to a chat message is **already (or becomes) a `FileAsset`**. The chat request carries the
  `asset_id`(s). Your adapter records them in `Draft.attachments` and resolves bytes/preview via
  `StorageManager` (`get_download_url` / the download path used in `routes/files.py`).
- **Do not** read or write files with ad-hoc paths or your own S3 calls — always go through `StorageManager`.
- `attach_receipt_file` reuses the same presign → complete-upload → link flow that `routes/files.py` already
  implements; refactor that linking step into a service function if it currently lives in the route.
- Validation (type/size) is already enforced by `StorageManager`; surface failures as catalogued errors.

---

## 7. VLM vs. text — branch on the model's vision capability

When a file is part of a task (e.g. `add_receipt` from a receipt photo, or "what does this say"), how you feed it
to the model depends on whether the **active chat model is vision-capable (a VLM)**:

- **If the model IS a VLM:** send the file to the model as image content block(s), exactly like
  `document_intelligence/services/llm_vlm_method.py`:
  ```python
  # base64 data URL, OpenAI-compatible image block
  {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{b64}", "detail": "low"}}
  ```
  Build the user message as a list mixing the image block(s) first and the text instruction after, and call the
  chat completion (use JSON mode — `response_format={"type":"json_object"}` — when you need structured slots for a
  draft). Reuse `_encode_image_b64` / `_image_content_block` (lift them into a shared `assistant/intake` helper;
  do not import the `document_intelligence` module — copy the small helper or move it to `backend/shared/`).
  - For PDFs, render/extract first (the heavy path, §below) and pass page images if vision is wanted.
- **If the model is NOT a VLM:** never send image blocks. Instead extract **text** from the file and send only the
  text. Reuse the project's existing extraction/OCR (the document pipeline / MinerU path the repo already uses for
  documents) to get text, then pass that text as the quoted, delimited context.

**How to know if the model is a VLM** (pick one, implement cleanly):
- Preferred: add a boolean **`supports_vision`** column to the `ChatAIModels` table
  (`backend/Models` + `schemas/chat_ai_models.py` + Alembic migration, default `false`), set per configured model.
  The chat code already selects a model from `ChatAIModels`; read `supports_vision` off the selected row.
- Fallback if you must avoid a migration now: read a settings/env flag like the existing
  `DI_LLM_VISION_ENABLED` used in `llm_vlm_method.py`. Document whichever you choose.

**Routing heavy vs. inline (§12.6):**
- Inline (no permanent document record): a single small image to read off a receipt/nameplate, a quick "what does
  this say" — pass straight to the vision/parse step.
- Heavy (reuse existing pipeline): a multi-page PDF needing full OCR/chunking — dispatch to the existing
  Celery-backed document pipeline; park the agent run as `waiting_on_task` and continue when it finishes.
- Record the heavy-vs-inline choice on the `AgentRun` for traceability.

---

## 8. Agent control flow (reuse the seed agent's LangGraph shape)

Model it on `core/agents/langgraph.py` (a `StateGraph` with typed state and nodes).

**Define the graph state explicitly as this exact `AgentState` TypedDict** (do not abbreviate it — every field
below must exist; add more only if needed):

```python
class AgentState(TypedDict, total=False):
    # --- identity & request context (set once at entry) ---
    chat_id: int
    agent_run_id: int
    user: User                      # the current user; carried into every node for RBAC (§5)
    user_id: int
    company_id: int
    db: Session                     # request-scoped session (as the seed agent does)
    language: str                   # detected user language, BCP-47 (e.g. "fa", "en")

    # --- the current turn's input ---
    question: str                   # the user's raw message
    rewritten_query: str | None     # optional query rewrite for retrieval
    attachments: list[int]          # FileAsset ids attached to this message (§6)
    model_is_vlm: bool              # whether the active chat model supports vision (§7)

    # --- router output ---
    intent: str                     # one of §3: search_receipts | summarize_finance | ask_finance |
                                    #   add_receipt | update_receipt | add_card | update_card |
                                    #   add_customer | update_customer | add_receipt_comment |
                                    #   attach_receipt_file | general | clarify
    slots: dict                     # extracted fields (amounts, dates, names, ids, currency, ...)
    clarify_question: str | None    # set when intent == "clarify"

    # --- planning / multi-step control ---
    plan: list[str]                 # ordered remaining steps (e.g. ["file_intake","add_receipt","await_confirm"])
    current_step: str               # the step being executed now
    next_step: str | None           # what decide_next chose; None => finish
    step_count: int                 # guard against infinite loops (cap it)

    # --- results produced by handlers ---
    retrieved_items: list[dict]     # search/ask hits + sources, in the existing chat.py shape
    summary: dict | None            # KPI/summary payload (summarize_finance)
    pending_draft: dict | None      # the Draft object built for a write intent (NOT yet committed)
    answer: str                     # the assistant's natural-language reply (streamed as deltas)
    citations: list[str]            # citation keys for the answer

    # --- file intake bookkeeping (§6/§7) ---
    intake_mode: str | None         # "inline" | "heavy" | None — recorded on AgentRun for traceability
    extracted_text: str | None      # text path for non-VLM models
    image_blocks: list[dict]        # OpenAI image_url blocks, only when model_is_vlm is true

    # --- async / interruption ---
    task_id: str | None             # Celery task id when a step is parked (waiting_on_task)
    error_code: str | None          # a catalogued ASSISTANT_* / PERMISSION_DENIED code if a node failed
```

Notes on the state:
- `user` / `db` / `company_id` are threaded through **every** node so RBAC and scoping are always enforced (§5);
  never fetch a privileged session inside a node.
- `pending_draft` holds the built-but-uncommitted draft. The graph **never** commits — commit is the separate
  button endpoint (§4). Reaching a write step ends the turn with `pending_draft` set + an `await_confirm` status.
- `image_blocks` is populated **only** when `model_is_vlm` is true; otherwise leave it empty and use
  `extracted_text` (§7). A handler must assert this invariant.
- `step_count` + a hard cap prevent runaway loops in `decide_next`.

**This `AgentState` (the live graph state) is distinct from the `AgentRun.status` lifecycle** — the persisted run
status enum (store these exact values on the `AgentRun` row): `active | suspended | waiting_on_task | completed |
cancelled | failed` (Master Plan §12.8). `suspended` = interrupted by a new user request (resumable);
`waiting_on_task` = parked on a Celery job (§7 heavy path). The checkpointer snapshots `AgentState` after each
node so any of these can resume.

Nodes: `router` (classify intent + language + slots) → branch to one handler per §3 intent → `decide_next`
(loop for multi-step, e.g. `file_intake → add_receipt → await_confirm`) → `end`. Persist run state so a half-built
draft survives app close (the Postgres checkpointer + the `AgentRun` row, §12.8) — and the draft itself persists
independently in its own table (§4).

### 8.1 Conversation history AND resumable state — keep BOTH, in separate stores

There are two different things to persist; do not conflate them:

1. **Chat transcript (history).** The human-readable conversation, stored as `Chat` + `ChatMessage` rows exactly
   like the existing `routs/chat.py` does with `add_message(...)`. You **must** reuse this:
   - On message arrival, save the user's message (`ChatRole.user`).
   - At the end of the run, save the assistant's reply (`ChatRole.assistant`) with its `citations` and
     `retrieved_chunks`/retrieved items, just as `routs/chat.py` already does.
   - If the turn produced a draft, store the `draft_id` on (or alongside) the assistant message so the frontend
     can re-render the draft card from history.
   - A weaker model will forget this — it is mandatory. Without it, chat history and title generation break.
2. **Resumable agent state.** The LangGraph **Postgres checkpointer** + the `AgentRun` row. This holds the graph
   state (current step, plan, pending draft, slots) so an interrupted or half-finished run can resume from any
   device. This is machinery — the frontend does **not** render it.

Keep them distinct: the checkpointer can be pruned/expired without losing the visible transcript, and the
transcript stays clean even though the agent ran many internal steps. The `Draft` persists independently in its
own table (§4), referenced from the message that produced it.

**Returning history to the frontend.** The system already exposes `GET /{chat_id}/history`
(`ChatHistoryResponse`) in `routs/chat.py` — the frontend shows past conversation by calling it. Make sure the
assistant flow keeps writing `ChatMessage` rows so this endpoint returns the full transcript (messages, roles,
citations, retrieved items, and any draft reference). Do not invent a second history endpoint; reuse this one
(extend its response only if you must surface the draft reference).

### 8.2 Streaming the reply (SSE) — required

The reply must stream token-by-token. **The repo already supports streaming** — copy the proven pattern; do not
invent a new transport:
- `backend/tag_management/routes/ask.py` — `StreamingResponse(event_generator(), media_type="text/event-stream")`
  with an async `event_generator` that `yield`s SSE events (`_sse_event("delta", {"text": ...})`, plus
  `references`, `error`, `done`). Reuse this exact shape.
- `backend/core/semantic_ask.py` — streams deltas from the model via the OpenAI client with `stream=True`
  (`async for ... yield text`). The LLM client (`components/llm.py`) is OpenAI-compatible, so use the same
  approach (`stream=True` on the async client, or LangChain `.astream`).

Note the **current chat endpoint does NOT stream** — `routs/chat.py` uses `graph.ainvoke` and returns one full
`ChatResponse`. So you are *adding* streaming to the assistant endpoint, using the SSE pattern above.

Stream event contract for `POST /assistant/chat` (Server-Sent Events):
- `status` — lightweight step signals during multi-step runs (e.g. "searching receipts…", "building draft…").
- `delta` — incremental answer text tokens.
- `draft` — the complete `Draft` payload (sent once, as a whole object — never reconstructed from tokens).
- `references` / `retrieved` — search hits, summary tables, citations (sent as complete objects).
- `error` — a catalogued error code (stream-safe; never a raw stack trace).
- `done` — final event: the full answer text, citations, retrieved items, `chat_id`, and any `draft_id`.

Rules:
- **Streaming is transport only.** It changes nothing about RBAC, drafts, persistence, or the error catalog. A
  stream that fails mid-flight must leave the `AgentRun` resumable (§8.1) and the draft intact.
- **Structured payloads are delivered whole**, not as tokens: a `Draft`, search hits, and summaries are emitted
  as complete objects (`draft` / `references` / `done` events). The frontend renders the draft/confirm UI from
  the complete object, never from partial tokens.
- **Persist after streaming.** Save the assistant `ChatMessage` (§8.1) once the stream completes (or on the
  `done` event), with the final answer + citations + retrieved items — so history matches what was streamed.
- The confirm/cancel and draft endpoints stay plain JSON (no streaming); only the chat reply streams.

---

## 9. Errors, limits, observability

- Add `ASSISTANT_*` codes to `core/exceptions/error_codes.py` and raise only those (plus existing catalogued
  codes). `INTERNAL_SERVER_ERROR` is the only uncatalogued case.
- Add a simple per-user / per-company rate or token guard; exceeding it returns `ASSISTANT_RATE_LIMITED`.
- Trace each run (tool calls, latency, tokens, outcome) to Langfuse (the repo already has
  `docker-compose-langfuse.yml`); tracing must be fire-and-forget and never block the user path.

---

## 10. Tests (mandatory — CI runs `pytest` + `alembic check`)

Ship all of:
1. **Unit tests with the LLM mocked** for each handler: `search_receipts`, `summarize_finance`, `ask_finance`,
   `build_*_draft`, `commit_*_draft`. Deterministic.
2. **Route integration tests** for every new endpoint: success, RBAC (`403 → PERMISSION_DENIED`), validation, and
   that only catalogued error codes are returned.
3. **Agent end-to-end tests** (stubbed model): intent routing per branch, `draft → confirm`, `draft → cancel`,
   resume-after-restart, **and a VLM vs non-VLM test** asserting image blocks are sent only when
   `supports_vision` is true and text-only otherwise.
4. A test that an instruction embedded in an uploaded file does **not** cause an auto-commit (guardrail §12.19).
5. A test that **chat text never commits**: sending "yes, accept it" / "confirm" / "do it" to `POST /assistant/chat`
   leaves the draft `pending` and writes nothing — only `POST /assistant/drafts/{id}/confirm` commits.
6. A test of **confirm-with-edited-payload**: posting a changed `payload` to the confirm endpoint commits the
   user's edited values (not the original draft values), after re-validation and RBAC re-check.
7. **History persistence**: after a chat turn, both the user and assistant `ChatMessage` rows exist and
   `GET /{chat_id}/history` returns them with citations/retrieved items (and the `draft_id` when a draft was made).
8. **Streaming**: `POST /assistant/chat` returns `text/event-stream`, emits `delta` events for answer tokens and
   a single complete `draft`/`done` object; a mid-stream failure leaves the `AgentRun` resumable and the draft intact.
9. **RBAC-filtered router**: a user lacking `financial_management:receipts:create` never gets `add_receipt` in the
   router's intent set (assert it is absent from the built prompt/registry for that user), and a message that would
   map to it falls back to `clarify`/`general` — the restricted task is never named back to the user.

---

## 11. Deliverables checklist

- [ ] `financial_management/assistant_tools.py` — the `ModuleToolSet` (search/summarize/ask/build_draft/commit_draft)
      wrapping existing services; registered into the assistant tool registry.
- [ ] Generic draft machinery (`Draft`, `AgentRun`) + endpoints, registered in `Models/__init__.py`, with Alembic migration.
- [ ] Router/intent node with the §3 taxonomy and per-intent descriptions.
- [ ] Conversation history wired (§8.1): user + assistant `ChatMessage` rows saved (with citations, retrieved
      items, and any `draft_id`); history served via the existing `GET /{chat_id}/history`. Resumable agent state
      (checkpointer + `AgentRun`) kept as a separate store.
- [ ] Streaming chat reply over SSE (§8.2) reusing the `tag_management/routes/ask.py` pattern; structured payloads
      (drafts/search/summary) emitted as complete objects; assistant message persisted after the stream completes.
- [ ] Refactors that move route-handler business logic into `financial_management/services.py` (no duplication).
- [ ] File-intake helper using `StorageManager`; VLM-vs-text branching per §7; `supports_vision` on `ChatAIModels`.
- [ ] `assistant:chat` / `assistant:draft` / `assistant:files` permissions seeded + migration.
- [ ] `ASSISTANT_*` error codes; rate limit; Langfuse tracing.
- [ ] Full test suite from §10, all green.

---

## 12. Build order (do it in this sequence)

1. Refactor the needed financial route logic into service functions; add `summarize_receipts`,
   `create_receipt_service`, `update_receipt_service`, etc. Keep existing routes passing.
2. Build the generic `Draft`/`AgentRun` models + migration + endpoints (no intelligence yet).
3. Build `financial_management/assistant_tools.py` (the `ModuleToolSet`) calling those services, RBAC-checked.
4. Build the router/intent node (§3) and wire the LangGraph flow (§8) reusing the seed agent's shape.
5. Add file intake (§6) + the VLM/text branch (§7) + `supports_vision`.
6. Add error codes, rate limit, Langfuse.
7. Write all tests (§10). Run `pytest` + `alembic check`. Fix until green.

When unsure about a service signature or a permission string, **grep the financial_management module** rather than
guessing — the answer is in the code you were told to read in §1.
