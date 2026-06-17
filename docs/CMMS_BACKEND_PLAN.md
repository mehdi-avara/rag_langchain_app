# CMMS Backend Plan — Backend Developer Track
> Working plan for the **backend developer**.
> Read alongside:
> - `CMMS_MASTER_PLAN.md` — the **shared architecture contract** (full detail lives there; this plan points to its sections).
> - `KEEP_IN_MIND.md` — the "don't get burned" gotchas (schema, migrations, RBAC, AI seam).
> - `CMMS_AI_PLAN.md` — the **AI developer's** track. You don't build that; you hand off to it.

---

## 1. Your scope vs. the AI developer's

| You own (backend dev) | AI dev owns |
|---|---|
| All domain modules (models, migrations, schemas, **services**, routes, `search/`, `permissions.py`, `/ask`, `/summary`) | The whole `backend/assistant/` package (agent graph, router, drafts framework, checkpointer, intake, tool registry) |
| Cross-cutting backend infra: **error catalog** (`core/exceptions`), **structured logging** (§4.5), **audit log**, **currency**, **tag metadata** (`tag_management` extension, §12.10) | Per-module `{module}/assistant_tools.py` adapters (thin wrappers over **your** service functions) |
| Clean, AI-consumable **service functions** per module — this is your seam | Slash `//` tools, group chat (Phase 5), prompt-injection guardrails, LLM usage limits, Langfuse tracing, streaming |
| Phase 4 backend: notification engine, manager dashboard API, module refactor, route versioning | The "AI Manager Agent" (Prompt 20) = mature Assistant Core |

**The seam between you two is the Module Tool Contract (Master Plan §12.4).** You expose documented service functions; the AI dev wraps them in `assistant_tools.py`. Agree the function signatures with the AI dev *before* you implement a module so they don't churn later. You do **not** need to know LangGraph.

---

## 2. Non-negotiable shared rules (full text in the Master Plan)

These apply to **every** module you build. Don't reinvent — follow the referenced section.

- **Modular monolith rules 1–12** — Master Plan § "ARCHITECTURAL GOAL". No cross-module model imports; cross-module writes via Celery; shared types in `backend/shared/`; each module owns its migrations; heavy ops (>200ms) → Celery `202 + task_id` (Rules 8 & 10).
- **Standard search pattern** — §2.1. Every searchable module gets a `search/` subfolder (keyword ILIKE + pgvector semantic + hybrid) and an `embedding Vector(1024)` column.
- **RBAC: declare → seed → protect** — §6. `{module}/permissions.py`, seed in migration, every route behind `require_permission(...)`. No unprotected routes, including reads.
- **Multi-currency 4-field money pattern** — §4. Every money field = `amount`, `currency_id`, `amount_base`, `exchange_rate_used`. New modules use `currency_id` FKs, never free-text.
- **Error catalog** — §12.9. Raise only **catalogued** `AppException` codes (never bare `HTTPException` with ad-hoc text). `INTERNAL_SERVER_ERROR` is the only uncatalogued case.
- **Structured logging** — §4.5. Central JSON logger, `request_id` propagated across web + Celery, no secrets/PII.
- **Naming conventions** — §10.
- **KEEP_IN_MIND golden rules** — Alembic owns the schema (no `create_all`); **register every model in `backend/Models/__init__.py`** or autogenerate skips the table; declare each index/constraint once; cross-module references stay plain integer columns.

---

## 3. Definition of Done — every module

A module is **not done** until all of these exist:

1. **Models** with a pgvector `embedding` column where searchable; **registered in `backend/Models/__init__.py`**.
2. **Alembic migration** — hand-reviewed for FK order, circular FKs, duplicate indexes, pgvector import; seeds the module's permissions.
3. **Pydantic schemas** (`...Create`, `...Read`).
4. **Service layer** — *all* business logic lives here, not in route handlers. (This is what the AI adapter calls — keep functions pure: take `db` + `user`, no `Request` objects.)
5. **Routes** — every endpoint behind `require_permission(...)`.
6. **`search/` subfolder** — `repository.py` + `service.py` + `routes.py` (§2.1).
7. **`permissions.py`** declared + seeded in the migration.
8. **`/ask`** (grounded NL answer + sources) and **`/summary`** (totals/KPIs in base currency) endpoints.
9. **AI-ready service functions** documented for the seam: `search_*`, `summarize_*`, `ask_*`, `create_*`, `get_*`, `update_*` — signatures shared with the AI dev (§12.4). *(The AI dev writes the `assistant_tools.py` adapter that calls these; you guarantee the functions are stable and documented.)*
10. **Tests** — unit tests for services + route integration tests covering success, RBAC `403 → PERMISSION_DENIED`, validation, and that only catalogued errors are returned.
11. **Only catalogued errors** raised (§12.9).
12. **"What you could add next"** suggestions list (Rule 9).

---

## 4. Build order

Run the detailed prompt for each item from **Master Plan §8**. Migration dependency order matters where noted.

### Phase 0 — Foundation (do first)
| Order | Item | Notes |
|---|---|---|
| 1 | **0.3 Currency** (`shared/currency/`) | Currency + ExchangeRate tables; everything money depends on it. |
| 2 | **0.2 Purchase Management** | Clean rewrite; deletes `buying_management`. FK to currencies → run after 0.3. |
| 3 | **0.1 Heavy processing → Celery** | STT async, `TaskResult`, `GET /tasks/{id}`. |
| 4 | **0.5 Structured logging** | §4.5 — central JSON logging, `request_id` across web + Celery. |
| — | **Error catalog consolidation** | §12.9 — make `error_codes.py` the single source of truth + auto-export `errors.json` + `GET /errors/catalog`. Do this early; the AI dep needs it. |
| — | 0.4 Frontend spec | Hand to frontend. |

### Phase 1 — Commerce & Warehouse (Prompts 1–7)
Supplier → Material Master → Requisition → RFQ → Goods Receipt → Warehouse → Phase 1 KPIs.
Includes the **tag metadata** extension (§12.10): `TagMetadataField` (admin-defined per company) + `Tag.metadata` JSONB + validation + admin endpoints — register the new model.

### Phase 2 — Maintenance (Prompts 8–13)
Asset → Work Order → PM Planning → Inspection → Phase 2 KPIs.

### Phase 3 — HR & Communication (Prompts 14–18)
HR (employees/leave/training) → Communication/Letters → HSE → Phase 3 KPIs.

### Phase 4 — Platform (your part: Prompts 19, 21, 22, 23)
Notification & Workflow engine (19) → Manager Dashboard API (21) → Module Refactor (22) → Route Versioning (23).
**Prompt 20 (AI Manager Agent) is the AI dev's**, not yours.

> After every phase, deliver its **KPI/reporting sprint** (`GET /reports/...`, `GET /kpi/...`) — Master Plan "KPI & Reporting Phases".

---

## 5. Handoff checklist to the AI developer (per module)

When a module is done, give the AI dev:
- The list of service functions + signatures (search / summarize / ask / create / get / update).
- The permission strings each action requires.
- What fields make sense to embed / search / summarize.
- Any Celery side-effects the module emits (so the agent knows about async outcomes).

That's all they need to write the `assistant_tools.py` adapter and wire your module into the chat.
