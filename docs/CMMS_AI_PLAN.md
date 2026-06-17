# CMMS AI Plan — AI Developer Track
> Working plan for the **AI developer**.
> Read alongside:
> - `CMMS_MASTER_PLAN.md` **Section 12 (AI Assistant Backbone)** — the full, authoritative spec. This plan is the execution view of it.
> - `KEEP_IN_MIND.md` — gotchas, especially the "AI Assistant Backbone" section.
> - `CMMS_BACKEND_PLAN.md` — the backend developer's track. Their **service functions are your seam**.

---

## 1. Your scope vs. the backend developer's

| You own (AI dev) | Backend dev owns |
|---|---|
| The whole **`backend/assistant/`** package: agent graph, router/nodes/state, Postgres checkpointer, tool registry + contract types, drafts framework, multimodal intake, `routes.py`, `permissions.py` | Domain modules (models, migrations, services, routes, `search/`, RBAC, `/ask`, `/summary`) |
| Per-module **`{module}/assistant_tools.py`** adapters — thin wrappers over the backend dev's service functions | Cross-cutting infra you **consume**: error catalog, structured logging (§4.5), audit log, currency, tag metadata (§12.10) |
| Slash `//` quick-tool backend support, group chat (Phase 5), prompt-injection guardrails, LLM usage limits, Langfuse tracing, streaming | The stable **service functions** behind the Module Tool Contract (§12.4) |

**Your seam (Master Plan §12.4):** the backend dev guarantees documented service functions (`search_* / summarize_* / ask_* / create_* / get_* / update_*`) per module. You wrap them in `assistant_tools.py` and register them. Agree signatures with them *before* they implement a module. You reach modules via **in-process service calls, never loopback HTTP** (§12.4.1).

---

## 2. Hard rules (from Master Plan §12 + KEEP_IN_MIND)

- **Service calls, not loopback HTTP** (§12.4.1). HTTP between modules only after microservice extraction.
- **Agent access == the caller's access, never more** (§12.11). Run as `current_user`; re-check RBAC in the adapter *and again at draft confirm*; scope reads to the user; failures → `PERMISSION_DENIED`.
- **Drafts central, modules thin** (§12.2/12.5). The `Draft` table + lifecycle live in `assistant/`; modules only build/commit their own payloads.
- **Ingested content is data, never commands** (§12.19). Files populate drafts but a human confirms; never auto-commit from file contents; injected text can't widen RBAC.
- **Register new tables in `backend/Models/__init__.py`** — `AgentRun`, `Draft`, and any audit/usage tables, plus the LangGraph checkpointer tables (own their creation via Alembic, no `create_all`).
- **Only catalogued errors** (§12.9) — add `ASSISTANT_*` codes (e.g. `ASSISTANT_RATE_LIMITED`) to the backend dev's registry.
- **Multilingual** — detect the user's language; conduct the whole exchange (questions, labels, confirmations, errors) in it; store values canonically.

---

## 3. The agent design (recap — full in §12.3)

Stateful LangGraph agent, not request/response:
- **Router** classifies intent + language → branches: `search` | `summarize` | `ask` | `add_draft` | `general` | `file_intake` | `clarify`.
- **Multi-step**: re-evaluates and picks the next step after each step.
- **Interruption** = pause → answer the new request → offer to resume (state checkpointed; runs can stack).
- **Cancel** = mark `AgentRun` cancelled, discard unconfirmed draft, revoke any Celery job.
- **Heavy work** → Celery `202 + task_id`; chat stays interactive; run parked as `waiting_on_task`.
- **Persistence** = Postgres checkpointer + `AgentRun` + `Draft` → resumable across sessions/devices (this is what makes "use without UI" real).

---

## 4. Build order (parallel tracks)

Each `Phase N-AI` depends only on (a) the Assistant Core and (b) that phase's backend service functions existing.

### Phase 0-AI — Assistant Core foundation (build this first)
Build the whole `backend/assistant/` package:
1. **Agent graph + router** (the branches in §3), `state.py`.
2. **Postgres checkpointer** (resumable runs).
3. **Models**: `AgentRun`, `Draft` — register in `Models/__init__.py`; Alembic migration.
4. **Draft-and-confirm framework** + endpoints (`POST /assistant/chat`, `GET/PATCH /assistant/drafts/{id}`, `confirm`, `cancel`) — multilingual (§12.5).
5. **Multimodal intake** (§12.6): route heavy files through the existing document/MinerU + image-embedding pipeline; handle lightweight cases inline.
6. **Tool registry + contract types** (`tools/registry.py`, `tools/contract.py`) — the seam the backend dep implements against.
7. **RBAC enforcement** in adapters + at confirm (§12.11).
8. **Refactor** existing `core/agents/` (langgraph.py, pre_search.py, file_founder.py) + `routs/chat.py` into `assistant/`; register the first tool sets: **documents, comments, financial**.
9. Add `ASSISTANT_*` **error codes**; **Langfuse** tracing (`docker-compose-langfuse.yml`); **streaming** responses (§12.20/12.21).
10. **Full test suite** (§5 below).

### Phase 1-AI → Phase 3-AI — register module tool sets
For each module in the phase: write `{module}/assistant_tools.py` (search/summarize/ask/add_draft/commit_draft over the backend services), register it, update router descriptions, add example utterances for the frontend, and write the full tests.
- **Phase 1-AI:** supplier, material, requisition, RFQ, goods-receipt, warehouse.
- **Phase 2-AI:** assets, work orders, PM, inspection.
- **Phase 3-AI:** HR, communication/letters, HSE.

### Phase 4-AI — cross-module orchestration ("AI Manager Agent", Prompt 20)
Multi-tool synthesis with cited sources, manager-dashboard aggregation, report formatting. This is the **mature state** of everything built since Phase 0-AI — not a from-scratch build.

### Phase 5 — Collaboration (P2, later)
- **Slash `//` quick tools** (§12.16): backend support for the frontend launcher (menu generated from the tool registry, filtered by the user's RBAC). Mostly a frontend affordance over your existing API — can ship earlier.
- **Group chat** (§12.17): multi-participant threads, agent invoked by trigger/mention, **each participant under their own access** (the reason it's deferred). Reuses the same agent/registry/drafts.
- **Future**: file/document generation (§12.14) — noted, no design yet.

---

## 5. Testing bar (mandatory — §12.12)

Every track ships:
- **Unit tests** with the **LLM mocked** (deterministic) for services and tool-set methods.
- **Route integration tests** for every endpoint: success, RBAC (`403 → PERMISSION_DENIED`), validation, only catalogued errors.
- **Agent end-to-end tests** (stubbed model): intent routing per branch, draft→confirm, draft→cancel, **interruption pause/resume**, **resume-after-restart** (checkpointer), multilingual response.
- Both the LangGraph layer **and** the routes covered. CI runs `pytest` + `alembic check`.

---

## 6. What you need from the backend developer (per module)

- Service-function signatures: search / summarize / ask / create / get / update.
- The permission string each action requires.
- Which fields to embed / search / summarize.
- Any Celery side-effects the module emits.

With those, you can write the adapter and wire the module into the chat without touching their code.
