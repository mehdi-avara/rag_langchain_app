# CMMS Master Plan — Petroleum Industry Platform
> Last updated: 2026-06-17
> Base system: RAG / Knowledge Management (FastAPI + PostgreSQL + Celery)
> Database: **PostgreSQL + pgvector extension** (semantic search via pgvector is already in use — Elasticsearch / ChromaDB not needed)
>
> **This is the shared architecture contract.** Two role-specific working plans derive from it and reference it for shared rules:
> - `CMMS_BACKEND_PLAN.md` — the **backend developer's** track (domain modules + cross-cutting infra).
> - `CMMS_AI_PLAN.md` — the **AI developer's** track (the `assistant/` package + per-phase AI tracks).
>
> The seam between the two is the **Module Tool Contract (Section 12.4)**: the backend dev exposes service functions; the AI dev wraps them. Keep this file as the single source of truth for shared rules so the two plans don't drift.

---

## 0. Glossary — Canonical Domain Terms (read before using any term below)

These terms are **overloaded** and have caused real design errors (e.g. treating `model_management` as
ML/AI config). Each term has exactly ONE meaning in this project. Any spec that contradicts a definition
here is a bug — fix the spec, not the glossary. When a spec makes a *negative* claim ("X is wrong because
Y is …"), it must cite the glossary term it relies on.

| Term | Canonical meaning | What it is NOT |
|---|---|---|
| **model** (`model_management.ManagedModel`) | An **equipment-model type**: manufacturer/company + model name + spec data/docs (e.g. a Siemens pump model). The catalog of equipment *types*. | NOT an ML/AI model, NOT stock, NOT a physical installed unit. |
| **item** (`material_management.Item`) | A **stockable thing**: material, spare, consumable, tool, chemical, PPE. The universal warehouse/PO line entity. Identified by `item_code`. May optionally reference a model via `item.model_id` (NULL for generic materials like glue). | NOT a model; NOT a physical position in the plant. |
| **tag** (`tag_management` / `system_tags`) | A **functional position in the process** (P&ID tag). `tag → model` means "equipment of this model is used at this process point." | NOT a free-text label only; NOT the equipment unit itself. |
| **asset** (Phase 2 `asset_management.Asset`) | A **physical installed unit** at a position, with serial number and lifecycle/history. References its model via `asset.model_id`. | NOT a model type; NOT a stock row. |
| **stock** (`StockItem`) | The **on-hand quantity of an `item` at a storage location**. Always points at `item_id`, never directly at a model. | NOT the item definition; NOT a model. |

**Module charters (one line each — what the module owns and is NOT):**
- `model_management` — owns equipment-model *types* and their docs/links; it is **not** an item/stock store and **not** ML config.
- `material_management` — owns the `Item` catalog (materials/spares/consumables); the universal stock & PO line entity.
- `tag_management` — owns functional positions and their links (tag↔model, tag↔doc); not stock, not assets.
- `property_management` / Warehouse — owns warehouses, locations, `StockItem`, and movements; anchors stock to `Item`.

---

## 0.5 Data Separation Architecture — Canonical Standard for Every Module

> **Read this before adding ANY new module or any cross-module reference.** We run **one shared PostgreSQL
> database** and we **keep foreign keys as the default**. Divisibility comes from clean **code seams**, not from
> removing FKs. A module is split into its own database only as a deliberate, last-resort step — and there is a
> documented recipe for doing it when (if ever) that day comes. Follow the seam rules once and new modules are
> correct by construction; you never have to pre-emptively denormalize or drop FKs "just in case."

**Chosen model: schema-per-module on one shared Postgres, FK-as-default, split-ready by clean seams.**
Each module owns exactly one Postgres **schema** (`model_management`, `material_management`, `warehouse`,
`purchase`, …) for organization. Shared identity/reference data lives in one **`platform`** schema that every
module references but none owns. **Foreign keys and JOINs across module schemas in this shared DB are allowed and
preferred** — we want DB-enforced referential integrity (no manual "does this id exist?" checks, safe cascades,
no orphan rows). Because it is one database, any schema *could* be promoted to its own database later, but that is
an explicit migration, not the default posture.

**Why FK-as-default (not soft-ref-everywhere):**
- The database enforces integrity for us: an `item_id` that points at a non-existent item simply cannot be written.
- No hand-rolled existence checks on every write, and no periodic "orphan reconciliation" jobs to maintain.
- Safe, declarative cascade/restrict behavior instead of application code trying to emulate it.
- No pre-emptive denormalized snapshot columns to keep in sync — you JOIN when you need a label.

**Divisibility comes from clean code seams, NOT from removing FKs. The seam rules (always):**

1. **Schema-per-module for organization.** Every table a module owns lives in that module's schema. FKs may cross
   schemas inside this one shared DB.

2. **A module is only ever touched through its service-layer functions.** To read or use another module's data,
   call that module's **service function** (today an in-process call; after a hypothetical split, the identical
   call behind an HTTP client). Routes are not the service API — call the service layer.

3. **No cross-module imports of another module's internals.** Never import another module's SQLAlchemy **models**,
   **route functions**, or **Pydantic schemas**. The FK in the database is fine; the *Python coupling* is what we
   forbid. You may declare a `ForeignKey("other_schema.table.id")` column, but you resolve/display that row by
   calling the owning module's service — not by importing its model or `relationship()`-ing into it.

4. **Cross-module writes go through Celery events.** When module A must cause a write in module B (e.g. a GRN
   creates a StockMovement), A publishes a Celery event; B's handler performs the write. Never reach synchronously
   into another module to mutate its rows.

5. **Shared types live in `backend/shared/`.** Enums, constants, money helpers, common exceptions that several
   modules need live in `backend/shared/` — never in one module imported by another.

**Soft references are NOT the default.** A **soft reference** (plain `INTEGER` column, no `ForeignKey(...)`, no
`relationship()`, existence validated in application code) is introduced **only at a seam we have deliberately
decided to split out** to its own physical database. Until a seam is designated for extraction, it stays a normal
FK. Denormalized snapshot fields are likewise **not** added pre-emptively — they are added **only at extraction
time**, for the specific fields that can no longer be reached by JOIN once the seam is cut.

**Scaling order for large deployments (cheapest, most reversible first):**
1. **Index / query tuning** — the right indexes and query shapes solve the vast majority of load problems.
2. **Read replicas** — offload reporting/read traffic.
3. **Partitioning** — partition the hot, large tables (e.g. `stock_movements`, audit logs) by time/tenant.
4. **Caching / connection pooling** — short-TTL caches on hot reads, PgBouncer for connection pressure.
5. **(Last resort) Physically extract one hot module to its own database** — convert *only that seam's* crossing
   FKs to soft refs at that point, following the recipe below.

**How to extract a module later (the recipe — only when step 5 above is actually reached):**
1. **Point the module's engine at a new database.** Give the module its own connection string / engine; its
   schema and tables move to the new DB unchanged.
2. **Move its schema** to the new database (dump/restore the module's schema; nothing else moves).
3. **Convert only the FKs that cross the cut** to soft references — for each FK that now points across the new
   physical boundary, drop the `ForeignKey(...)`/`relationship()` and make it a plain `INTEGER`. FKs that stay
   within the extracted module (or within what remains) are untouched.
4. **Add service-side existence checks + events** at that one seam — the writing side validates the soft ref via
   the owning module's service (catalogued error on miss); cross-boundary writes that were already events stay
   events; add a reconciliation job only for the newly soft seam.
5. **Add denormalized snapshot fields** only for the columns the cut now prevents you from JOINing to (e.g. a
   label you used to render via JOIN), kept read-only and refreshed via the owning module's change events.
6. **Swap in-process service calls for an HTTP client** at that seam — same function signature, now behind a
   transport. Because every module was only ever reached through its service layer, this is a client swap, not a
   rewrite.
7. **No business-logic change.** The module's internal logic, its tables, and its tests do not change — only the
   boundary's transport and the one seam's FK→soft-ref conversion do.

**Shared platform schema (`platform`):** owns `users`, `companies`, roles/permissions, `currencies`, `fx_rates`.
Every module references `user_id` / `company_id` / `currency_id` as **real FKs → `platform`** in the shared DB
(resolved via the platform service in code — no model import). The 4-column money rule (§4) still holds:
`amount`, `currency_id` (FK → `platform.currencies`), `amount_base`, `exchange_rate_used`.

**Search & the AI assistant:** each module owns its search (keyword + pgvector) via the existing `search/`
subfolder pattern. Cross-module and agent search = fan-out to each module's search service and merge in the app.
This keeps the seam clean regardless of FKs, so global semantic search works identically before and after any
hypothetical module split.

**Migrations:** each module's Alembic revisions are scoped to its own tables; never mix two modules in one
revision (see `KEEP_IN_MIND.md`). A cross-schema FK is created in the revision of the module that *owns the
referencing table*.

**Definition of done for every NEW module:**
- [ ] All the module's tables live in its own schema; no table outside it.
- [ ] Cross-module data is reached **only** through the other module's service functions — no import of its
      models, routes, or Pydantic schemas.
- [ ] Cross-module references are **real FKs in the shared DB** (resolve the other module's row via its service);
      a soft ref appears only at a seam explicitly designated for extraction.
- [ ] Cross-module writes go through **Celery events**, never a synchronous reach into another schema.
- [ ] Shared types live in `backend/shared/`.
- [ ] Own `search/` subfolder over its own tables; cross-module search via fan-out + merge.
- [ ] Own Alembic revisions, scoped to its tables.

**The payoff:** because nothing ever crosses a module boundary *in code* except through a service function, the
day a module genuinely needs its own database is a mechanical, well-scoped change (the recipe above) — not a
rewrite. We pay for that option with clean seams, not with degraded integrity today.

---

## 1. What Already Exists (Foundation)

The existing codebase is a production-ready RAG system. Every new module builds **on top of** this — it is not replaced.

| Existing Module | What it has |
|---|---|
| `document_management` | Upload, version, chunk, embed documents |
| `tag_management` | Tag any entity; tag-based search |
| `model_management` | **Equipment-model catalog** (manufacturer + model name + spec data/docs); tag↔model linking; document linking; ask/chat. NOT ML/AI model config — see Glossary §0. |
| `buying_management` | **Deleted in Phase 0.2** — replaced by `purchase_management` (clean rewrite) |
| `financial_management` | Financial receipts, cards, customers |
| `property_management` | Properties catalog, warehouse skeleton (partial) |
| `routs/` | Auth, users, company, RBAC, chat, assets, STT |
| `core/` | Chunking, embedding, AI ask/search, agents skeleton |
| `db/` | SQLAlchemy + Alembic migrations |
| `Models/` | User, Company, RBAC, Document, Chunk, Chat, FileAsset |

**Database: PostgreSQL + pgvector.**
The system already uses pgvector for semantic/vector search (see `financial_management` and `retrieval/vector/postgres_store.py`).
Embeddings are generated by `JinaAPIEmbeddings` and stored as `Vector(1024)` columns directly in PostgreSQL.
Keyword search uses `ILIKE` pattern matching. No Elasticsearch or ChromaDB is needed.

---

## ARCHITECTURAL GOAL: Modular Monolith → Future Microservices

**This project is built as a modular monolith with the explicit goal of being extractable into microservices later.**

A modular monolith means: one deployable process, one database, but with strict boundaries between modules so that any module can be pulled out into its own service in the future without rewriting business logic.

### Rules that MUST be followed in every new module (non-negotiable):

**Rule 1 — No cross-module model imports.**
A module must never import another module's SQLAlchemy model class.
If module A needs data from module B, it calls a service function that module B exposes — not its models directly.
```python
# ❌ WRONG
from warehouse_management.models import StockItem
item = db.query(StockItem).get(id)

# ✅ CORRECT
from warehouse_management.services import get_stock_item
item = get_stock_item(db, id)
```

**Rule 2 — No calling another module's route functions.**
Routes are HTTP handlers, not a service API. Never import and call a route function from another module.
If you need the logic, that logic belongs in a service function, not a route.

**Rule 3 — Cross-module writes use events (Celery tasks), not direct calls.**
When module A needs to trigger a write in module B (e.g. GRN creates a StockMovement), it publishes a Celery task — it does not call module B's service function synchronously.
This mirrors how microservices communicate via message queues. Today it runs in the same process; tomorrow it can run in a separate worker.
```python
# ✅ GRN finalized → publish event
from celery_app import app
app.send_task("warehouse_management.tasks.on_grn_posted", args=[grn_id])
```

**Rule 4 — Shared types live in `shared/`, nowhere else.**
Enums, constants, base money types, common exceptions that multiple modules need go into `backend/shared/`.
No module imports a shared type from another module's folder.

**Rule 5 — Each module owns its migrations.**
Alembic revisions for a module's tables are named clearly (`buying_management_`, `warehouse_`, etc.).
No single migration touches tables from two different modules.

**Rule 6 — `Models/__init__.py` is not used for cross-module access.**
This file exists for Alembic discovery only. No business code should import from it.

### What this buys you:
- Today: clean, testable, understandable code where each module can be owned by one developer
- Future: to extract `warehouse_management` into its own microservice, you replace the Celery task calls with message queue publishes and the service function calls with HTTP calls — the business logic inside each module does not change

### Existing violations (to be fixed in Phase 4):
The existing code has cross-module **imports** that violate the seam rules — `tag_management` and
`model_management` import `financial_management` routes/schemas and `model_management` models;
`property_management` imports `model_management` models and `financial_management.models`;
`embedding_service` and `core/agents/langgraph.py` pull from modules; `Models/__init__.py` is imported by
business code (`buying_management` is deleted in Phase 0). These are the *code seams* to clean — **not** the
FKs, which stay (§0.5). They are tracked and refactored in **Phase 4.7 — Modular Monolith Refactor** (the single
merged refactor spec). All NEW modules must be clean from day one (`purchase_management` is the reference pattern).

**Rule 7 — Backward compatibility is mandatory.**
Adding a new module or feature must never break existing API routes or DB schema.
Any change that is NOT backward compatible (route rename, field removal, behavior change) is a
**breaking change** and must be explicitly flagged to the user before implementation.
The user must approve the breaking change before any code is written.
New fields on existing tables must be nullable or have a default so migrations do not fail on existing data.

**Rule 8 — Heavy processing goes through Celery, never in the request/response cycle.**
Any operation that takes more than ~200ms (embedding generation, PDF processing, image analysis,
STT transcription, report generation, bulk imports) must be offloaded to a Celery task.
The route returns immediately with `202 Accepted` + a `task_id`.
The caller polls `GET /tasks/{task_id}/status` to check progress.
Route signatures do not change when moving work to Celery — the response shape stays the same,
only the status code changes from 200 to 202 and a `task_id` is added.

**Rule 9 — The system suggests what to add next.**
At the end of each implemented module, the system produces a "What you could add next" list —
features that would naturally extend what was just built. This is surfaced to the user so they
can decide what to prioritize without needing to ask.

**Rule 10 — Celery Task Standards (every task must follow this).**
All Celery tasks must be written to the following standard without exception:
```python
@app.task(
    bind=True,
    max_retries=3,
    default_retry_delay=60,   # seconds between retries
    acks_late=True,           # task is only acknowledged after it completes (prevents silent loss)
    reject_on_worker_lost=True
)
def my_task(self, ...):
    try:
        # ... work ...
        TaskResult.mark_done(task_id, result)
    except (TransientError, ConnectionError) as exc:
        raise self.retry(exc=exc)   # retries up to max_retries
    except Exception as exc:
        TaskResult.mark_failed(task_id, str(exc))
        raise                        # do not swallow permanent failures
```
- `TaskResult` row must be written (status: done | failed) before the task exits — always.
- Routes that dispatch a task must also write the initial `TaskResult` row (status: queued) atomically with the dispatch, so the polling endpoint never returns 404.
- A Celery Beat job runs daily to delete `TaskResult` rows older than 30 days (prevents unbounded table growth).
- Cross-module Celery tasks (e.g. `notify_warehouse_of_receipt`) run as system — no `current_user` permission check inside the task. Authorization is verified by the route that dispatches the task, before dispatching.

**Rule 11 — API Versioning.**
Routes have no `/api/` prefix — they start directly with the module name (e.g., `/purchase/orders`, `/warehouse/items`).
No version prefix is applied in Phases 0–3.
Versioning will be introduced in Phase 4 when microservice extraction begins,
at which point service boundaries are locked and breaking changes require a version bump.
Until then, breaking changes in Phase 0–3 are handled by explicit user approval + same-release frontend update.

**Rule 12 — Every module owns its RBAC permissions (non-negotiable).**
Access control is a first-class concern, not an afterthought. Rules:
- Every module declares its permissions in `{module}/permissions.py`
- Every route is protected by a `require_permission("{module}:{action}")` FastAPI dependency
- Permissions are seeded into the DB in the module's Alembic migration
- No route is ever left unprotected — even read-only endpoints require `{module}:read`
- Cross-module Celery tasks run as system (no user permission check inside the task);
  the dispatching route is responsible for verifying the user's permission before dispatching
- The shared RBAC system (already in `routs/`) provides `has_permission()` and `require_permission()`
- The full RBAC permission naming convention and complete permission list for all modules is defined in Section 6 (RBAC and Access Control)
- Convention: `{module}:{sub-resource}:{action}` (three parts) or `{module}:{action}` (two parts) — matches existing `financial_management:receipts:read` pattern in `db/seed_rbac.py`

---

**Key architectural rule (keep forever):**
Each feature area lives in its **own app folder** (`buying_management/`, `warehouse_management/`, etc.).
Apps talk to each other **only through service functions and Celery events** — no cross-module model imports, no cross-module route calls.
This keeps each module independently extractable into a microservice when needed.

---

## 2. Overall Architecture Principles

```
┌─────────────────────────────────────────────────────────┐
│                    SINGLE FASTAPI PROCESS                │
│   (all apps registered as APIRouter on main app)        │
│                                                          │
│  ┌──────────┐ ┌──────────┐ ┌──────────┐ ┌──────────┐  │
│  │warehouse │ │procure   │ │asset_mgmt│ │work_order│  │
│  │_mgmt     │ │_mgmt     │ │          │ │_mgmt     │  │
│  └────┬─────┘ └────┬─────┘ └────┬─────┘ └────┬─────┘  │
│       │             │             │             │         │
│  ┌────▼─────────────▼─────────────▼─────────────▼─────┐ │
│  │              SHARED SERVICES LAYER                  │ │
│  │  • RBAC (permission checks)                        │ │
│  │  • Document Intelligence (attach docs to anything) │ │
│  │  • Tag System (tag anything)                       │ │
│  │  • Notification Engine (events → notifications)   │ │
│  │  • Search (keyword + semantic + hybrid per module) │ │
│  │  • Audit Log (every write is recorded)            │ │
│  └─────────────────────────────────────────────────────┘ │
│                                                          │
│  ┌──────────────────────────────────────────────────┐   │
│  │    STORAGE: PostgreSQL + pgvector extension      │   │
│  │  (keyword: ILIKE  |  semantic: <=> vector ops)  │   │
│  └──────────────────────────────────────────────────┘   │
└─────────────────────────────────────────────────────────┘
```

**AI-Friendliness Rules (apply to every module):**
1. Every module has a `search/` subfolder with keyword + semantic + hybrid search (see Section 2.1 below).
2. Every module's main list endpoint supports `?q=` as a quick keyword shortcut.
3. Every module exposes a `/ask` endpoint so the AI agent can query it in natural language.
4. Documents can be attached to any entity (work orders, purchase orders, assets, etc.).
5. Tags can be applied to any entity.
6. Every module registers an **Assistant Tool set** (`search`, `summarize`, `ask`, `add_draft`) into the Assistant Core so the chat agent can drive that module without the UI. See **Section 12 — AI Assistant Backbone**.
7. Every delivery phase has a **parallel AI sub-phase** (a separate developer track) that wires that phase's modules into the Assistant Core. See Section 12.13.

> **The chat page is the primary interface of the whole system.** Everything a user can do through the UI must also be doable by talking to the assistant on the chat page — searching across modules, adding data (via draft-and-confirm), getting summaries/KPIs, uploading PDFs/photos, and asking general questions. The complete specification for this lives in **Section 12**. Every module plan must satisfy Section 12's Module Tool Contract.

---

## 2.1 — Standard Search Pattern (Required for Every Module)

This is the most important implementation standard. Every module must follow this exact pattern,
modelled on the existing `financial_management/search/` implementation.

### How Search Works in This System

Search runs entirely inside **PostgreSQL** using two mechanisms:

- **Keyword search**: `ILIKE '%query%'` across all meaningful text columns. Fast, no setup needed.
- **Semantic search**: `pgvector` extension — each entity has an `embedding` column (Vector type).
  Embeddings are generated via `JinaAPIEmbeddings` and stored in PostgreSQL.
  Similarity is calculated with the `<=>` cosine distance operator.
- **Hybrid search**: Both are run, results are merged and deduplicated by entity ID.

The caller chooses the mode at query time: `"keyword"` | `"semantic"` | `"hybrid"`.
If semantic is requested but no embedding exists yet, the system auto-generates it, then falls back
to keyword if embedding generation fails — so search never errors, it degrades gracefully.

### Folder Structure (every module must have this)

```
{module_name}/
  search/
    __init__.py
    repository.py   ← raw SQL: keyword query + vector similarity query
    service.py      ← orchestration: mode routing, merge logic, hit building, embedding trigger
    routes.py       ← HTTP endpoints: POST /search (main), deprecated filter/semantic-search aliases
```

### The Search Request Schema (standard across all modules)

```python
class {Entity}SearchRequest(BaseModel):
    query: str
    ids: List[int] = []           # optional scope — only search within these IDs
    mode: str = "hybrid"          # "keyword" | "semantic" | "hybrid"
    limit: int = 20

class {Entity}SearchHit(BaseModel):
    # all fields of the entity needed by the frontend list view
    # plus:
    match_source: str             # "text" | "semantic" | "text_fallback"
```

### The Search Endpoint (standard across all modules)

```
POST /{module}/search
Body: {Entity}SearchRequest
Response: List[{Entity}SearchHit]
Permission: {module}:search
```

### The `repository.py` pattern

```python
# keyword function — ILIKE on all searchable text columns
def search_{entity}_keyword(db, query_text, company_id, ids, limit) -> List[{Model}]:
    pattern = f"%{query_text}%"
    q = db.query({Model}).filter({Model}.company_id == company_id)
    if ids:
        q = q.filter({Model}.id.in_(ids))
    q = q.filter(or_(
        {Model}.field1.ilike(pattern),
        {Model}.field2.ilike(pattern),
        # ... all text fields worth searching
    ))
    return q.limit(limit).all()

# semantic function — pgvector cosine similarity on embedding column
def search_{entity}_semantic(db, query_text, company_id, ids, limit) -> List[dict]:
    embedding = JinaAPIEmbeddings().embed_query(query_text)
    embedding_str = "[" + ",".join(map(str, embedding)) + "]"
    # raw SQL with <=> operator, returns rows with similarity score
    sql = text("""
        SELECT e.*, (1 - (e.embedding <=> (:vec)::vector)) AS similarity
        FROM {table} e
        WHERE e.company_id = :company_id AND e.embedding IS NOT NULL
        ORDER BY similarity DESC LIMIT :limit
    """)
    return db.execute(sql, {...}).fetchall()
```

### The `service.py` pattern (mode routing — same logic as financial_management)

```python
def search_{entity}_hits(db, current_user, query_text, mode, ids, limit):
    if mode == "semantic": mode = "vector"   # normalize alias

    semantic_hits, text_hits = [], []
    semantic_available = False

    if mode in {"vector", "hybrid"}:
        ensure_{entity}_embeddings(db, current_user, ids)  # generate missing embeddings
        try:
            rows = search_{entity}_semantic(db, query_text, company_id, ids, limit)
            semantic_hits = [build_semantic_hit(row) for row in rows]
            semantic_available = True
        except Exception:
            pass  # graceful degradation

    needs_text = mode in {"keyword", "hybrid"} or (mode == "vector" and not semantic_available)
    if needs_text:
        rows = search_{entity}_keyword(db, query_text, company_id, ids, limit)
        text_hits = [build_text_hit(row) for row in rows]

    if mode == "keyword":  return text_hits[:limit]
    if mode == "vector":   return semantic_hits[:limit] if semantic_available else text_hits[:limit]
    return merge_hits(semantic_hits, text_hits, limit)  # hybrid: merge + deduplicate by id
```

### What each entity model needs

Every entity that supports semantic search must have this column added in its Alembic migration:

```python
from pgvector.sqlalchemy import Vector

class MyEntity(Base):
    # ... other columns ...
    embedding = Column(Vector(1024), nullable=True)  # 1024 = Jina embedding dimension
```

And a service function `ensure_{entity}_embeddings(db, user, ids)` that generates embeddings
for any entities that don't have one yet, before a semantic or hybrid search is executed.

The text to embed is a concatenation of the entity's most meaningful fields:
```python
def build_searchable_text(entity) -> str:
    parts = [entity.name or "", entity.description or "", entity.code or ""]
    return " ".join(p for p in parts if p).strip()
```

### Which fields to include in keyword search (decide per entity)

| Entity type | Suggested keyword fields |
|---|---|
| Items / materials | code, name, description, category, barcode |
| Suppliers | name, code, country, city, tax_id |
| Work Orders | wo_number, title, description, asset tag |
| Assets | tag_number, name, description, manufacturer, model_number |
| Employees | name, employee_number, position, department |
| Letters | letter_number, subject, body |
| Incidents | incident_number, description, location |

### Summary: what to add to EVERY new module's implementation plan

1. `embedding` column on the primary entity model (pgvector Vector(1024))
2. `search/` subfolder with `repository.py`, `service.py`, `routes.py`
3. `ensure_{entity}_embeddings()` service function
4. `build_searchable_text()` function defining what gets embedded
5. `POST /{module}/search` endpoint accepting `mode`: keyword/semantic/hybrid
6. Permission: `{module}:search`
7. Alembic migration includes the embedding column

---

## 3. Delivery Phases

---

### Phase 0 — Foundation Fixes & Purchase Management (Do First, Before Any New Module)
> Target: Make the existing system stable, correct, and ready for the frontend team to start work.
> Phase 0.1 (Celery) has no breaking changes. Phase 0.2 (purchase_management) is a **clean rewrite** —
> buying_management is deleted and replaced entirely. No backward compatibility required: no other team
> has begun implementation against it. Phase 0.3 (currency) is a new shared module, purely additive.

**Prompt execution order (migration dependency): run Prompt 0.3 → 0.2 → 0.1**
Prompt 0.3 creates the `currencies` table. Prompt 0.2 (purchase_management) has FK to it — it must exist first.
Prompt 0.1 (Celery) is independent and can run any time, but do it last to keep Phase 0 coherent.

| # | Prompt | Task | Type | Priority |
|---|---|---|---|---|
| 0.3 | `Prompt 0.3` | **Multi-currency foundation** — new shared module | New module (additive) | P0 |
| 0.2 | `Prompt 0.2` | **purchase_management** — clean replacement of buying_management | **Clean rewrite (breaking)** | P0 |
| 0.1 | `Prompt 0.1` | **Heavy processing → Celery** (STT, image embedding) | Refactor, no route change | P0 |
| 0.5 | — | **Structured logging & observability** — central JSON logging, request-id correlation across web + Celery (Section 4.5) | New foundation (additive) | P0 |
| 0.4 | — | **Frontend spec for Phase 0** | Spec | P0 |

---

#### Phase 0.1 — Heavy Processing → Celery (No Route Changes)

**What is heavy today:**
- `routs/stt.py`: STT transcription calls an external API synchronously inside the request cycle.
  If the audio is long, the HTTP request hangs. This is the most urgent fix.
- Embedding generation on new entities (financial receipts, comments) happens synchronously
  during the write request in some paths.

**The fix pattern (same for every heavy operation):**
```
BEFORE: POST /stt/transcribe → [blocks for 10-30 seconds] → returns transcript
AFTER:  POST /stt/transcribe → dispatches Celery task → returns 202 + {task_id, status: "queued"}
        GET  /tasks/{task_id} → returns {status: "processing"|"done"|"failed", result: ...}
```

**Rules:**
- Route URL does not change
- Request body schema does not change
- Response schema gains `task_id` and `status` fields alongside the existing fields
  (when done, result is in the response; when queued/processing, result is null)
- The `GET /tasks/{task_id}` endpoint is a new shared endpoint — it does not belong to any one module
- Existing clients that call the route and wait for the response will still work because when
  processing is fast (cached or short audio) the task may already be done by the time they check

**What to implement:**
1. `core/celery/tasks.py` — add `transcribe_audio_task(asset_id, user_id)` Celery task
2. `routs/stt.py` — change upload handler to dispatch task instead of awaiting directly
   (route signature stays identical)
3. `routs/tasks.py` — new shared endpoint `GET /tasks/{task_id}` for polling any Celery task status
4. `Models/task_result.py` — `TaskResult` model: task_id, status, result_json, error, created_at

**Breaking change check: NONE** — existing routes unchanged, new polling endpoint is additive.

---

#### Phase 0.2 — Purchase Management (Clean Rewrite — buying_management deleted)

**Decision: buying_management is completely removed and replaced with purchase_management.**
No other team has implemented against it. There is no transition period and no aliases.
The old module folder, tables, and routes are deleted. The new module is built from scratch, clean.

**What was wrong with buying_management (do NOT carry forward):**
- `BuyingProcessItem` links **stock/PO lines directly** to `model_management.ManagedModel`. The link itself
  is valid (ManagedModel is the equipment-model catalog, not an AI model catalog — see Glossary §0), but a
  PO/stock line is an `Item` (material / spare / consumable). Lines must resolve through the **`Item` catalog**,
  and `Item.model_id` (→ managed_models) is **optional** — set for equipment and model-specific spares, NULL
  for generic materials (glue, grease, bolts). Mandatory model on every line is the bug, not the FK itself.
- `affects_warehouse` Boolean flag on `BuyingProcess` — couples purchase to warehouse logic directly.
  In a modular monolith, the correct pattern is: purchase emits a Celery event; warehouse module listens.
- Route prefix `/buying/` — replaced by `/purchase/`.
- `BuyingProcess` model name — replaced by `PurchaseOrder`.
- Free-text `currency`/`base_currency` string fields — replaced by proper currency_id FKs
  (using the `Currency` table built in Phase 0.3 which runs first).

**New module: `backend/purchase_management/`**

Data model (clean, no legacy carryover):
```
PurchaseOrder
  ├── reference_number (auto: PO-2026-0001)
  ├── supplier_id FK → suppliers.id  (NULL until Phase 1 Supplier module; use supplier_name as fallback)
  ├── supplier_name (VARCHAR, kept for Phase 0 before Supplier module exists)
  ├── currency_id FK → currencies.id
  ├── base_currency_id FK → currencies.id
  ├── exchange_rate_used (Numeric 28,10)
  ├── status: draft | ordered | shipped | received | closed | cancelled
  ├── approval_status: draft | pending | approved | rejected
  ├── description, description_embedding (Vector 1024 — for semantic search)
  ├── created_by_user_id, approved_by_user_id
  └── created_at, updated_at

PurchasePhase  (one PO has 1..N phases — each phase = one physical delivery batch)
  DEFINITION: A phase represents a physical shipment arriving at the facility.
  One PO can have multiple phases when goods arrive in separate deliveries.
  Approval gates belong on PurchaseOrder (approval_status), NOT on phases.
  Phases do not represent milestones, contract stages, or document checkpoints.
  ├── purchase_order_id FK → purchase_orders.id
  ├── phase_number (1, 2, 3...)
  ├── title, description
  ├── status: draft | ordered | shipped | received | closed
  ├── currency_id FK → currencies.id (inherits from PO if null)
  ├── exchange_rate_used
  └── created_at, updated_at

PurchasePhaseItem  (items inside a phase — Item rows: material/spare/consumable; equipment items optionally carry model_id)
  ├── phase_id FK → purchase_phases.id
  ├── item_id (free-text item_name in Phase 0; in Phase 1 becomes item_id FK → material_management.items
  │            (shared DB) — resolve via material_management service, do not import its model; §0.5)
  ├── item_code (optional SKU/part number)
  ├── quantity (Numeric), unit (str: "pcs", "kg", "m", etc.)
  ├── unit_price (Numeric), currency_id FK
  ├── unit_price_base (Numeric), base_currency_id FK
  ├── exchange_rate_used (Numeric)
  ├── line_total (Numeric), line_total_base (Numeric)
  └── notes

PurchaseOrderCost  (additional costs: freight, customs, tax, insurance)
  ├── purchase_order_id FK → purchase_orders.id
  ├── cost_type: freight | customs | tax | insurance | other
  ├── description, amount (Numeric), currency_id FK
  ├── amount_base (Numeric), base_currency_id FK
  ├── exchange_rate_used
  └── allocation_method: per_item | per_value | manual

PurchaseOrderReceiptLink  (links payment receipts from financial_management)
  ├── purchase_order_id FK → purchase_orders.id
  ├── financial_receipt_id FK → financial_management.financial_receipts.id (shared DB) — resolve via the
  │            financial_management service, do not import its model; §0.5
  └── linked_at, linked_by_user_id
```

**Route prefix: `/purchase/`** (not `/buying/`)

New endpoints:
- `POST   /purchase/orders` — create PO
- `GET    /purchase/orders` — list with filters (status, date range, supplier)
- `GET    /purchase/orders/{id}` — detail with phases
- `PATCH  /purchase/orders/{id}` — update
- `DELETE /purchase/orders/{id}` — soft delete (status → cancelled)
- `PATCH  /purchase/orders/{id}/approval` — submit/approve/reject
- `POST   /purchase/orders/{id}/phases` — add phase
- `GET    /purchase/orders/{id}/phases` — list phases
- `PATCH  /purchase/orders/{id}/phases/{phase_id}` — update phase
- `POST   /purchase/orders/{id}/phases/{phase_id}/items` — add item to phase
- `PATCH  /purchase/orders/{id}/phases/{phase_id}/items/{item_id}` — update item
- `POST   /purchase/orders/{id}/costs` — add additional cost
- `POST   /purchase/orders/{id}/receipt-links` — link payment receipt
- `POST   /purchase/orders/search` — search (keyword | semantic | hybrid)
- `GET    /purchase/orders/{id}/summary` — totals by currency + base currency

**Cross-module communication (warehouse):**
When a phase reaches status `received`, `purchase_management` dispatches a Celery task:
`notify_warehouse_of_purchase_receipt.delay(phase_id)`.
The warehouse module's Celery task reads the phase items and creates warehouse intake records.
No direct model imports between modules.

**Search subfolder: `purchase_management/search/`**
- Keyword: ILIKE on `reference_number`, `supplier_name`, `description`
- Semantic: pgvector on `description_embedding`
- Hybrid: merge by purchase_order_id

**Permissions:** `purchase:read`, `purchase:write`, `purchase:approve`, `purchase:delete`

**Alembic migration:**
- Drop `buying_processes`, `buying_process_items`, `buying_process_costs`, `buying_process_receipt_links` tables
- Create `purchase_orders`, `purchase_phases`, `purchase_phase_items`, `purchase_order_costs`, `purchase_order_receipt_links` tables
- **Note**: run Phase 0.3 migration first so `currencies.id` FK is available

---

#### Phase 0.3 — Multi-Currency Foundation (New Shared Module — Run Before Phase 0.2)

> **Run this migration before Phase 0.2.** purchase_management uses currency_id FKs from day one.

**What is missing today:**
- No `Currency` master table (currencies are free-text strings in financial_management)
- No `ExchangeRate` table (rates entered manually per-transaction)
- No `base_currency_id` on `Company`

**What to build: `backend/shared/currency/` — new shared module**

1. `Currency` table — pre-populate with all currencies currently in use:
   IRT, IRR, USD, AED, IQD, CNY (from `FinancialCurrency` enum) + common additions (EUR, GBP, TRY)
2. `ExchangeRate` table — from/to currency, rate (Numeric 28,10), effective_date, source (manual/api)
3. `Company` model — add nullable `base_currency_id FK → currencies.id`
4. `shared/currency/services.py` — `get_rate(db, from_code, to_code, on_date)`, `convert(db, amount, ...)`
5. `shared/currency/routes.py` — register under `/currencies/`
6. Existing free-text `currency` / `base_currency` string fields on `financial_receipts` are **not** changed.
   These old tables stay as-is. Only new modules (starting with purchase_management) use currency_id FKs.

**Endpoints:**
- `GET  /currencies` — list active currencies
- `POST /currencies` — create currency (admin only)
- `GET  /currencies/exchange-rates` — list rates (filter by from/to/date range)
- `POST /currencies/exchange-rates` — add a rate (finance_manager permission)

**Breaking change check: NONE** — new module, new tables, nullable FK on companies only.

---

#### Phase 0.4 — Frontend Spec for Phase 0

```
SCREENS TO BUILD:

1. Purchase Order List (/purchases)
   - List all purchase orders with status badges
   - Columns: PO number, supplier name, date, currency, total, status, phase count
   - Filter by status, approval status
   - Search bar (calls POST /purchase/orders/search with mode selector: keyword/semantic/hybrid)
   - "New Purchase" button

2. Purchase Order Detail (/purchases/:id)
   - Header: PO number, supplier, dates, status, approval status
   - Tabs: Phases | Costs | Payments | Summary
   - Phases tab: list of phases, each expandable to show items
   - Add Phase button (calls POST /purchase/orders/:id/phases)
   - Items within phase: item name, item code, qty, unit, unit price, currency, line total in base currency

3. New/Edit Purchase Order (modal or page)
   - Fields: reference_number (auto-generated), supplier name (free text in Phase 0, FK in Phase 1),
     date, currency dropdown (from GET /currencies), exchange rate, description
   - On submit: POST /purchase/orders

4. Task Status Poller (shared component)
   - Polls GET /tasks/:task_id every 2 seconds
   - Shows spinner while processing, result when done, error if failed
   - Used by: STT transcription, bulk import, heavy report generation

5. STT page update
   - After uploading audio: show task_id + "Processing..." status
   - Use Task Status Poller to show result when ready
   - No route change needed — just frontend polling logic

API CALLS NEEDED:
  GET  /buying/processes          → purchase list
  POST /buying/processes          → create purchase
  GET  /buying/processes/:id      → purchase detail
  POST /buying/processes/search   → search (new in Phase 0)
  POST /buying/processes/:id/phases → add phase (new)
  GET  /currencies                → currency list (new)
  GET  /tasks/:task_id            → task polling (new)
```

---

### Phase 1 — Commerce & Warehouse (First Delivery)
> Target users: Procurement team, Warehouse keepers, Storekeepers
> **Build order: Buying/Procurement fully complete first, then Warehouse**

| # | Module | Order | Priority |
|---|---|---|---|
| 1.1 | **Currency & Exchange Rate** (shared foundation) | First | P0 |
| 1.2 | **Supplier Management** (vendor registry) | Second | P0 |
| 1.3 | **Material Master** (items catalog, units, categories) | Third | P0 |
| 1.4 | **Procurement** (MR → RFQ → PO → GRN) — complete buying_management | Fourth | P0 |
| 1.5 | **Warehouse Management** (locations, stock, movements) | Fifth — after procurement | P0 |
| 1.6 | **Inventory Reports & Full-text Search** | Sixth | P1 |

> **Why this order:** Procurement defines what gets bought and from whom.
> Warehouse receives the result of procurement (GRN → StockMovement IN).
> So procurement must be fully working before warehouse receiving makes sense.
> Also: buying_management already exists and needs completion before building warehouse on top of it.

### Phase 2 — Maintenance & Admin (Second Delivery)
> Target users: Maintenance engineers, Planners, Admins

| # | Module | Priority |
|---|---|---|
| 2.1 | **Asset Management** (equipment registry, hierarchy) | P0 |
| 2.2 | **Work Order Management** (CM + PM work orders) | P0 |
| 2.3 | **Maintenance Planning** (PM schedules, checklists) | P0 |
| 2.4 | **Notification & Workflow Engine** | P1 |
| 2.5 | **Defect / Fault Reporting** (flag that a tag has a problem; link the failed asset) | P0 |
| 2.6 | **Maintenance KPI Dashboard** (KPIs + charts + Excel/PDF export) | P1 |

> **Note on permits & access control:** reporting a fault lives here in Phase 2. The **work-permit and access-grant workflow** that follows a fault (technician requests access → **HSE team + Manager team** dual approval before work can start) is built in **Phase 4 — HSE module (4.2)** as an extension of Permit-to-Work, and gates Work Orders there. Phase 2 raises the fault and links the work order; Phase 4 governs who may act on it.

### Phase 3 — Human Resources (Third Delivery)
> Target users: HR managers, Department heads

| # | Module | Priority |
|---|---|---|
| 3.1 | **Employee Management** (master data, org chart) | P0 |
| 3.2 | **Leave Management** | P0 |
| 3.3 | **Training & Certification Tracking** | P0 |
| 3.4 | **Personnel Documents** | P1 |
| 3.5 | **Payroll basics** | P2 |

### Phase 4 — Full Platform (Final Delivery)
> Target users: Everyone in the petroleum facility

| # | Module | Priority |
|---|---|---|
| 4.1 | **Internal Communication** (letters, memos, announcements) | P0 |
| 4.2 | **HSE Module** (incidents, permits, risk assessments) | P0 |
| 4.3 | **Project Management** | P1 |
| 4.4 | **AI Manager Agent** (natural language → reports) | P0 |
| 4.5 | **Advanced Reporting & Dashboards** | P1 |
| 4.6 | **Contractor Management** | P2 |
| 4.7 | **Modular Monolith Refactor** (fix existing cross-module violations) | P1 |

#### Phase 4.7 — Modular Monolith Refactor (existing code cleanup) — the single seam-cleanup spec

> **This is the one canonical refactor spec.** It merges the three previously-overlapping descriptions —
> Phase 4.7 here, the summary-table row **"Prompt 22 — Module Refactor"**, and the summary-table row
> **"Prompt 23 — Route Versioning / service boundary lock"**. They all describe the same job: make the
> *code seams* clean. Use the framing below; do not maintain three separate lists.

**Goal: clean code seams, per §0.5.** We keep foreign keys as the default in the one shared database — the
refactor does **not** rip out FKs. What it removes is the **Python coupling** that crosses module boundaries:
imports of another module's SQLAlchemy **models**, **route functions**, or **Pydantic schemas**. After this,
every cross-module interaction goes through a **service-layer function** (reads) or a **Celery event** (writes),
shared types live in `backend/shared/`, and each route carries a version prefix so a module can later be lifted
out behind an HTTP client with no business-logic change (the §0.5 extraction recipe). This is deferred to Phase 4
so it does not block feature delivery; **all NEW modules must already be clean** (`purchase_management` is the
reference pattern — it links a financial receipt by id and a comment, with **no** import from
`financial_management.models`).

**The seam standard to enforce everywhere (from §0.5):**
- No cross-module import of another module's models, routes, or Pydantic schemas.
- Reads from another module go through its **service function** (in-process today; HTTP client after extraction).
- Cross-module **writes** go through **Celery events**.
- Shared types live in `backend/shared/`.
- A real FK in the shared DB is fine and preferred — it is the *code import* that is forbidden, not the FK.

**Current cross-module coupling to remove (confirmed by grep on the existing code):**

1. **Create / finish `backend/shared/`** — move `FinancialCurrency` enum (used by `company.py`) into
   `shared/currency.py`; move common exceptions, base money types, and money helpers into `shared/`.

2. **`tag_management` → `model_management` (models)** —
   `tag_management/services.py` imports `ManagedModel, ModelDocumentLink` from `model_management.models`, and
   `tag_management/routes/models.py` imports `ManagedModel`. **Fix:** call a `model_management` **service**
   function (e.g. `get_model`, `list_models_for_tag`) instead of importing the model. The FK stays; the import goes.

3. **`tag_management` → `financial_management` (routes + schemas)** —
   `tag_management/routes/receipts.py` imports route functions (`create_receipt`, `get_receipt`,
   `get_receipts_by_ids`), `financial_management.search.routes.search_receipts`, and schemas
   (`FinancialReceiptBatchRequest`, `FinancialReceiptSearchRequest`); `tag_management/schemas.py` imports
   `FinancialReceiptCreate, FinancialReceiptOut`. **Fix:** call `financial_management` **service** functions, not
   route functions; define local schemas or move shared ones into `backend/shared/`.

4. **`model_management` → `financial_management` (routes + schemas)** —
   `model_management/routes/receipts.py` imports route functions + schemas, and `model_management/routes/models.py`
   imports `get_receipt`; `model_management/schemas.py` imports `FinancialReceiptCreate, FinancialReceiptOut`.
   **Fix:** replace route imports with `financial_management` **service** calls; relocate shared schemas to `shared/`.

5. **`property_management` → `model_management` + `financial_management` (models + services)** —
   `property_management/services.py` imports `FinancialDirection, FinancialReceipt` from
   `financial_management.models` and `get_model_or_404, require_company` from `model_management.services`;
   `property_management/routes/warehouse.py` imports `ManagedModel`. **Fix:** stop importing
   `financial_management.models` (call its service); the `model_management.services` calls are already the right
   shape (service-layer) — only the `ManagedModel` model import must be removed in favour of a service call.
   (Note: warehouse here is superseded by the Phase 1 `warehouse` module; the migration repoints stock to
   `item_id` per §0.5 / Prompt 3.)

6. **`components/embedding_service.py`** — stop importing models from `financial_management` and
   `model_management`. Invert the dependency: modules **push** text to the embedding service; it does not pull
   from modules.

7. **`Models/__init__.py`** — strip to Alembic discovery only; no business code imports from it.

8. **`core/agents/langgraph.py`** — stop importing `financial_management.search.repository` directly;
   `financial_management` exposes a registered agent tool (Module Tool Contract §12.4) instead.

9. **Delete the dead `buying_management/` folder** — replaced by `purchase_management` in Phase 0; its remnants
   confuse greps and autogenerate.

10. **Route versioning / service-boundary lock** (the old "Prompt 23" item) — add a version prefix to routes
    (e.g. `/api/v1/...`) and lock the boundary so each module is reached only through its service layer. This is
    microservice-extraction prep: with versioned routes + a clean service seam, swapping an in-process service
    call for an HTTP client at one seam is the only change needed to split a module (§0.5 recipe). No
    business-logic change.

**Estimated effort: ~1 week.** **Risk: Low** — these are import-level + routing changes; FKs and business logic
are untouched.

---

### Phase 5 — Collaboration & Group Chat (Later — not urgent)
> Target users: Teams that want to work with the assistant together.
> Priority: P2. Built only after the Assistant Core (Phase 0-AI) and the per-phase tool tracks are mature.

| # | Module | Priority |
|---|---|---|
| 5.1 | **Group Chat** — multi-participant conversations where the agent is a participant, invoked with a trigger (e.g. `//` or `@assistant`) | P2 |
| 5.2 | **Slash-command quick tools** — the frontend `//` launcher that lets a user start an add-draft / tag-data / search action inline (single-user; can ship earlier as part of the Assistant UX) | P1 |

See **Section 12.16 (slash `//` quick tools)** and **Section 12.17 (group chat)** for the full specification. Group chat is explicitly low-priority for now; the `//` quick-tool launcher is more useful sooner and may ship alongside the Assistant Core UX rather than waiting for Phase 5.

---

### KPI & Reporting Phases (End of Every Phase)

After each delivery phase is complete, a **KPI & Reporting sub-phase** is added before handing off
to the next phase. This gives managers visibility into what was just built without waiting until the end.

| After Phase | Reporting Sprint | What managers can see (summary page + charts + export) |
|---|---|---|
| Phase 0 | Phase 0-R | **Financial summary dashboard** (see below), purchase order summary, spend by currency, open POs |
| Phase 1 | Phase 1-R | Inventory levels, low stock alerts, procurement cycle time, spend by supplier |
| Phase 2 | Phase 2-R | Work order backlog, MTTR, asset failure rates, PM compliance %, **critical tags with open faults**, maintenance cost |
| Phase 3 | Phase 3-R | Headcount by department, leave utilization, expiring certifications |
| Phase 4 | Phase 4-R | Cross-module executive dashboard, HSE/permit KPIs, full AI manager agent |

**Each reporting sprint delivers (all built on the shared conventions in 4.6 / 4.7):**
1. A set of `GET /reports/{module}/{name}` endpoints that aggregate data and return the **chart-ready shape** from 4.7 (`chart_type`, `x`, `series`, `unit`) — each with a recommended chart type.
2. A `GET /kpi/{module}` endpoint returning the top 5-8 KPIs as `{ key, label, value, unit, trend }` cards (for dashboard widgets).
3. A **summary page** for the module: KPI cards on top, charts below, a filter bar (period + relevant dimensions), and an **Export button** (xlsx / csv / pdf) wired to the Export Engine (4.6) so any view on screen can be downloaded.
4. **Per-module export endpoints** (`POST /{module}/{entity}/export`) on every list/report from 4.6 — Excel is the default and primary format.
5. A `/ask` endpoint on each module so the AI agent can answer natural-language questions and trigger an export from chat.
6. Frontend spec: which KPI cards, which charts (with recommended type), and where the export/period controls sit.

**Example KPIs for Phase 0-R (Purchase Management):**
- Total open POs and their combined value (in base currency) — *KPI card*
- Average time from PO creation to received status — *KPI card, trend vs last month*
- Spend by currency this month vs last month — *grouped/stacked bar*
- POs by status breakdown (draft / pending approval / ordered / received) — *donut*
- Top 5 suppliers by spend (from supplier_name, upgrades to supplier FK in Phase 1) — *horizontal bar*
- Export: open-POs list and spend breakdown to xlsx/pdf

#### Phase 0-R — Financial Summary & Charts Dashboard (the financial "summary page")

The existing `financial_management` module (receipts, cards, customers) gets a first-class **summary page with financial diagrams** — the "page for showing summary and these kinds of things, and financial data diagrams" requirement. It ships in Phase 0-R because the data already exists; it does not wait for later phases.

**Endpoints (chart-data shape from 4.7, all accept `?from=&to=&group_by=&currency_id=`):**
- `GET /kpi/financial` — KPI cards: total income, total expense, net cash position, receivables outstanding, this-month vs last-month deltas, all in **base currency** (Section 4 multi-currency rules apply).
- `GET /reports/financial/cashflow` — income vs expense over time → **line** (two series).
- `GET /reports/financial/by-category` — spend/income composition → **donut**.
- `GET /reports/financial/by-currency` — exposure per currency (original + base) → **stacked bar**.
- `GET /reports/financial/top-customers` — top customers/counterparties by value → **horizontal bar**.
- `GET /reports/financial/receivables-aging` — outstanding by age bucket (0–30/31–60/61–90/90+) → **bar**.

**Summary page layout (frontend spec):**
- Row of KPI cards (income, expense, net, receivables) with up/down trend chips.
- Cashflow line chart (default period = last 12 months, `group_by=month`).
- Two side-by-side: category donut + currency stacked bar.
- Receivables aging bar + top-customers bar.
- Filter bar (date range, currency) + **Export to Excel / PDF** button (whole dashboard or per-chart data).

**RBAC:** `financial:read` to view, `financial:export` to download; sensitive figures stay role-gated.

---

## 4. Multi-Currency Support (Authoritative Spec — see Prompt 0.3 for implementation)

> **This section is the authoritative reference for multi-currency.** Prompt 0.3 implements it.
> All other sections that mention currency defer to this spec.

Multi-currency must be built **from the very beginning** because retrofitting it later is very expensive.
It applies to: Procurement (PO, GRN), Financial Management, Supplier invoices, Inventory valuation.

### Where the Currency module lives

`backend/shared/currency/` — a shared module, not owned by any single domain module.

> **Future microservice note:** `shared/currency/` is imported by every module. When extracting
> modules to microservices in Phase 4, `shared/currency/` becomes either (a) a shared library
> packaged alongside every service, or (b) a dedicated Currency service that others call via HTTP.
> Decide at Phase 4. Until then, treat it as an importable library — it has no external dependencies.

### Data Model

```
Currency (table: currencies)
  - code: ISO 4217 VARCHAR(10), unique (USD, EUR, IRR, IRT, AED, IQD, CNY, GBP, TRY, ...)
  - name, symbol
  - decimal_places (INT — USD=2, IRR=0)
  - is_active (Boolean)
  Pre-populated: IRT, IRR, USD, AED, IQD, CNY (from existing FinancialCurrency enum)

ExchangeRate (table: exchange_rates)
  - from_currency_id FK → currencies.id
  - to_currency_id FK → currencies.id
  - rate: Numeric(28, 10) — high precision, never loses rounding at any scale
  - effective_date (DATE) — rate is valid from this date; use closest rate ≤ transaction date
  - source: 'manual' | 'api'
  - created_by_user_id, created_at
```

### Rules that apply to every money field in every module:

1. **Every monetary amount uses four fields** (never store money as a single bare Numeric):
   - `amount` — value in the transaction currency
   - `currency_id FK → currencies.id` — which currency
   - `amount_base` — equivalent in the company's base currency (for reporting + aggregation)
   - `exchange_rate_used` — rate applied at transaction time, stored permanently (never recalculated)

2. **Company base currency** is set once on the `Company` model (`base_currency_id FK → currencies.id`).
   All reports and dashboards aggregate in base currency.

3. **Exchange rates** are entered manually (or fetched via API in future). When a PO is created in a
   foreign currency, the system applies the closest rate ≤ today and stores it on the record permanently.

4. **Rounding** follows `currency.decimal_places` (USD = 2, IRR = 0, IRT = 0, etc.)

5. **Old tables** (`financial_receipts`) keep their free-text currency strings — do not retrofit.
   New modules (Phase 0.2 onward) always use `currency_id` FKs — never free-text currency strings.

### Where multi-currency applies:
- `PurchaseOrder` / `PurchasePhase` / `PurchasePhaseItem` — built in Phase 0.2 (uses currency_id FKs from day one)
- `GoodsReceiptNote` — Phase 1 (landed cost in transaction currency)
- `SupplierEvaluation` — price comparison normalised to base currency
- `financial_management` receipts — existing free-text fields stay; currency_id FKs added in Phase 4 refactor
- Inventory valuation (FIFO/weighted average cost) — Phase 1 (always stored with currency)

---

## 5. Cross-Cutting Modules (Build Once, Used by All)

These are not phase-specific — they are shared infrastructure that every phase uses.
Build them progressively starting from Phase 1.

### 4.1 Notification Engine
- Internal bell notifications (already have user model)
- Email notifications (async via Celery)
- Rules: "when X happens in module Y, notify user Z"
- Every module publishes events; the engine routes them

### 4.2 Approval Workflow Engine
- Generic configurable workflow: Draft → Submitted → Approved/Rejected → Executed
- Applies to: Purchase Orders, Work Orders, Leave Requests, Permits, etc.
- Each workflow step has: approver role, deadline, escalation

### 4.3 Audit Log
- Every write (create/update/delete) on every entity is logged
- Who, what, when, old value → new value
- Searchable by AI agent

### 4.4 AI Manager Agent (evolves over phases)
- Phase 1: Can answer "what is current stock of item X?" or "show pending POs"
- Phase 2: Can answer "what work orders are overdue?" or "which assets need PM?"
- Phase 3: Can answer "who is on leave this week?"
- Phase 4: Full cross-module natural language reporting

### 4.5 Structured Logging & Observability (build early — Phase 0)

A first-class application logging system for the whole backend. **This is technical logging — distinct from the business Audit Log (4.3).** Audit Log answers "who changed this record"; logging answers "what did the system do and why is it slow/broken".

- **Structured JSON logs** with consistent levels (DEBUG/INFO/WARNING/ERROR/CRITICAL), emitted by a single configured logger — no scattered `print()`.
- **Request correlation:** every request gets a `request_id` (already present in the error shape) propagated through logs and into Celery tasks, so one operation is traceable end to end across web + worker.
- **Context on every line:** `request_id`, `user_id`, `company_id`, route, latency, and outcome where available.
- **Errors:** every catalogued error (Section 12.9) and every 500 logs with stack trace + `request_id`; the `request_id` is returned to the client so a user-reported problem can be found instantly.
- **Celery tasks** log start/finish/retry/failure with the originating `request_id` and `TaskResult` id (Rule 10).
- **Configurable sinks/levels** per environment (stdout JSON in prod for shipping to a log store; pretty logs in dev). Log level driven by env, not code.
- **No secrets/PII in logs** — redact tokens, passwords, national IDs.
- Replaces ad-hoc use of the existing `logs/` directory with a proper, central configuration.
- **Where it's built:** Phase 0 foundation (it underpins every other module). The AI-specific tracing/usage in Section 12.20 sits on top of this and ships with the Assistant Core.

### 4.6 Export Engine (build once — used by every list, report, and dashboard)

A single shared export service so **every module gets xlsx / csv / pdf export for free** instead of re-implementing it. This is the "export to Excel and other great things" requirement, made reusable.

- **Where it lives:** `backend/shared/export/` — a shared module (Section 2 rules: shared code lives in `shared/`, never in one module imported by another).
- **Three formats, one contract:**
  - **xlsx** — styled spreadsheet (headers, frozen header row, column widths, number/currency formatting, one sheet per dataset). Generated with `openpyxl`.
  - **csv** — raw UTF-8 (BOM) data for analysts pulling into other tools.
  - **pdf** — printable report/summary (title block, company logo, filters applied, table or KPI sheet). Generated with a server-side HTML→PDF renderer.
- **Standard endpoint pattern (every module adds this next to its list/search endpoints):**
  ```
  POST /{module}/{entity}/export   body: { format: "xlsx"|"csv"|"pdf", filters: {...}, columns: [...] }
  → 202 + { task_id }      (export runs in Celery — Rule 5: heavy work is async)
  GET  /tasks/{task_id}    → { status, download_url }   (reuses the Phase 0.1 task poller)
  ```
  Small exports (< ~1k rows) may return the file inline; anything larger goes through Celery and the `download_url` points at a short-lived `FileAsset`.
- **Reuses existing infrastructure:** filters/columns mirror each module's `search` request schema (Section 2.1), so export === "run this search, then serialize". The result file is stored as a `FileAsset` and is itself attachable/searchable.
- **RBAC:** export requires the same read permission as the underlying list (`{module}:read`); a separate `{module}:export` permission is seeded so admins can withhold bulk export from roles that may view single records (KEEP_IN_MIND: every endpoint is permission-protected and seeded).
- **AI/assistant:** export is exposed as a module tool (Section 12.4) so "export this month's open work orders to Excel" works from chat as a draft-and-confirm action (Section 12.5). Ties into §12.14 (future document generation) — templates can reuse the same dataset layer.
- **Audit:** every export logs who exported what (entity, filters, format) via the Audit Log (4.3) — bulk data leaving the system is a security-relevant event.

### 4.7 Dashboard & Chart-Data Convention (build once — used by every KPI page)

The reporting sprints (Section "KPI & Reporting Phases") and the financial/maintenance/HSE dashboards all consume the **same chart-data shape**, so the frontend builds one set of chart components and points them at any module.

- **Two endpoint kinds per module:**
  - `GET /kpi/{module}` — the top 5–8 KPIs as `{ key, label, value, unit, trend }` cards (single numbers + up/down vs previous period).
  - `GET /reports/{module}/{name}` — a chart-ready series: `{ chart_type, x: [...], series: [{ name, data: [...] }], unit }`.
- **`chart_type` is recommended by the backend** (per the decision to specify *data endpoints + recommended chart types*, leaving the library to the frontend): `line` (trend over time), `bar`/`stacked_bar` (breakdown/compare), `pie`/`donut` (composition), `gauge` (single value vs target), `table` (raw rows). The frontend may override.
- **Period + filter params** are standard on every report endpoint: `?from=&to=&group_by=day|week|month&currency_id=` (currency only where money is involved — Section 4).
- **Every dashboard has an Export button** wired to the Export Engine (4.6): the same filters produce an xlsx/pdf of what's on screen.
- **Caching:** aggregation endpoints are read-heavy; cache per (company, params) with short TTL and invalidate on the relevant module event.

---

## 5. Detailed Feature Breakdown Per Phase

---

### PHASE 1 — Commerce & Warehouse

#### Module 1.1 — Warehouse Management

**What it does:**
Manages physical storage locations and tracks where stock is.

**Entities:**
- `Warehouse` (main warehouse, secondary warehouses)
- `Zone` (area within warehouse: A, B, C)
- `Shelf` / `Bin` (specific location within zone)
- `StockItem` (what material is stored where, how much)
- `StockMovement` (every in/out/transfer is recorded permanently)
- `StockCount` (periodic physical count records)

**Key features:**
- Multi-warehouse support
- Location tree: Warehouse → Zone → Shelf → Bin
- Minimum/maximum stock level alerts
- Stock movement history (never deleted, only appended)
- AI search: "find all bins with item X" or "which items are below minimum"
- Attach documents to any item (datasheets, safety sheets)
- Barcode/QR code field on items

**Integration points:**
- Receives stock from Procurement (GRN creates StockMovement IN)
- Issues stock to Maintenance (Work Order material consumption creates StockMovement OUT)
- Reports to Financial (stock valuation)

**AI touchpoints:**
- `/warehouse/ask` — natural language queries on stock
- Stock items indexed in semantic search (description, category, specs)
- Alert summaries can be consumed by Manager Agent

---

#### Module 1.2 — Material Master (Items Catalog)

**What it does:**
Central registry of all materials, spare parts, and consumables.

**Entities:**
- `ItemCategory` (Electrical, Mechanical, Instrumentation, Chemical, PPE, Office, etc.)
- `Unit` (KG, Liter, Piece, Meter, Box, etc.)
- `Item` (master item: code, name, description, category, unit, specs)
- `ItemAlternative` (alternate item codes / vendor codes)
- `ItemDocument` (linked manuals, datasheets, safety data sheets)

**Key features:**
- Unique item code per company
- Duplicate detection on create
- Specs stored as JSON (flexible per category)
- AI search on item description + specs
- Import from Excel (bulk upload)
- Tag items (critical spare, fast-moving, slow-moving, etc.)

---

#### Module 1.3 — Procurement

**What it does:**
Full procurement lifecycle from need to delivery.

**Workflow:**
```
Material Requisition (MR)
        ↓
Request for Quotation (RFQ)  [optional]
        ↓
Purchase Order (PO)
        ↓
Goods Receipt Note (GRN)
        ↓
Stock Movement IN (automatic)
```

**Entities:**
- `MaterialRequisition` (who needs what, how much, when, why)
- `MRItem` (line items on MR)
- `RequestForQuotation` (sent to suppliers)
- `QuotationResponse` (supplier response)
- `PurchaseOrder` (approved order to supplier)
- `POItem` (line items on PO)
- `GoodsReceiptNote` (what actually arrived)
- `GRNItem` (what was received per line)

**Approval workflow:**
- MR: requester → department head → procurement → approved
- PO: procurement → finance → GM (above threshold) → approved

**AI touchpoints:**
- "What are all pending POs for supplier X?"
- "How long does procurement take on average?"
- "Which items have been ordered most this year?"

**Integration:**
- GRN auto-creates StockMovement IN in Warehouse module
- PO links to Supplier in Supplier Management
- MR can be created from Work Order (maintenance requests parts)

---

#### Module 1.4 — Supplier Management

**What it does:**
Central registry of all vendors and their performance.

**Entities:**
- `Supplier` (company name, code, contact, country, type)
- `SupplierContact` (multiple contacts per supplier)
- `SupplierCategory` (what they supply)
- `SupplierDocument` (contracts, certifications, licenses)
- `SupplierEvaluation` (periodic scoring: delivery, quality, price)

**Key features:**
- Supplier approval status (pending → approved → blacklisted)
- Attach procurement documents (contract, NDA, catalog)
- Performance score from PO history (on-time delivery %, quality issues)
- AI search across supplier name, category, products they supply

---

### PHASE 2 — Maintenance & Admin

#### Module 2.1 — Asset Management

**What it does:**
Equipment and asset registry for the petroleum facility.

**Hierarchy:**
```
Plant
  └── Unit / System
        └── Equipment
              └── Component / Sub-component
```

**Entities:**
- `Plant` (refinery, pipeline, offshore platform)
- `AssetSystem` (process unit, utility system)
- `Asset` (individual equipment: pump, compressor, valve, instrument)
- `AssetSpecification` (technical specs as structured JSON per asset type)
- `AssetDocument` (manuals, P&IDs, drawings, certificates)
- `AssetHistory` (lifecycle events: installed, modified, replaced, decommissioned)

**Key features:**
- Unique tag number per asset (e.g., P-1001 for pump)
- Asset types: Rotating, Static, Electrical, Instrument, Civil
- Criticality rating (A/B/C) — drives PM frequency
- Link to spare parts in Item Master (which items are used for this asset)
- Attach P&ID drawings, datasheets, vendor manuals
- AI: "show me all criticality-A pumps in Unit 2"

---

#### Module 2.2 — Work Order Management

**What it does:**
Core of CMMS — managing all maintenance jobs.

**Work Order Types:**
- **CM** (Corrective Maintenance): reactive, something broke
- **PM** (Preventive Maintenance): scheduled, time/meter-based
- **PdM** (Predictive): based on condition monitoring
- **Inspection**: periodic inspection
- **Modification/Project**: small engineering change

**Lifecycle:**
```
Draft → Submitted → Approved → Planned → In Progress → Completed → Closed
         (with option to Reject or Put On Hold at any step)
```

**Entities:**
- `WorkOrder` (header: type, asset, description, priority, dates)
- `WorkOrderTask` (checklist steps / job tasks)
- `WorkOrderLabor` (who worked, how many hours)
- `WorkOrderMaterial` (which items consumed from warehouse)
- `WorkOrderFailure` (for CM: failure code, cause, action taken)
- `WorkOrderAttachment` (photos, reports)

**Key features:**
- Priority: Critical / High / Medium / Low
- Failure coding (ISO 14224 standard for petroleum)
- Material reservation from warehouse before work starts
- Labor tracking (technician, hours, craft type)
- Print job card as PDF
- AI: "how many CM work orders has asset P-1001 had in the last year?"

---

#### Module 2.3 — Maintenance Planning

**What it does:**
Preventive maintenance schedules so nothing breaks unexpectedly.

**Entities:**
- `MaintenancePlan` (plan for an asset or group: what to do, how often)
- `MaintenanceTask` (individual task within a plan: lubricate, inspect, replace)
- `TaskFrequency` (every X days / every X hours / every X cycles)
- `PMSchedule` (generated calendar of upcoming PM due dates)
- `InspectionChecklist` (step-by-step checklist for inspections)
- `ChecklistItem` (individual check: Pass/Fail/Measure)

**Key features:**
- Auto-generate Work Orders from due PM schedules (via Celery)
- Meter-based triggering (run hours, km, cycles)
- Route maintenance (multiple assets same route, one work order)
- Calendar view of upcoming maintenance
- AI: "what PM is due next week for Unit 3?"

---

#### Module 2.4 — Notification & Workflow Engine

Covered in section 4 above. Implement from Phase 2 onward.

---

#### Module 2.5 — Defect / Fault Reporting

**What it does:**
Lets anyone with access report that **a tag has a problem** — and pinpoint that a specific asset under that tag (e.g., the pump used in that tag) has failed. This is the entry point of the maintenance loop: a fault is raised, becomes visible on the KPI dashboard, and can be turned into a Work Order. (Per the domain decision, "tag" here means a **`tag_management` tag** — the central object users interact with — optionally linked to an Asset.)

**Entities:**
- `DefectReport`
  - `defect_number` (auto: DEF-2026-0001)
  - `tag_id` FK → `tag_management` tag (shared DB) — resolve via that module's service, never a model import (§0.5)
  - `asset_id` (optional) FK → `asset_management.assets` (shared DB) → the specific failed equipment under the tag
    (the "pump that is used in that tag is failed") — resolve via the asset_management service, no model import
  - `severity`: Low / Medium / High / Critical
  - `status`: Open / Acknowledged / In Progress / Resolved / Closed / Rejected
  - `description`, `description_embedding` (Vector 1024 — semantic search, Section 2.1)
  - `reported_by`, `reported_at`
  - `work_order_id` (optional) FK → `work_order` (shared DB) — set when a WO is raised to fix it; resolve via the
    work_order service, no model import
  - `photos` (FileAsset attachments)
- `DefectComment` (follow-up notes / status changes, audit-logged)

**Key features:**
- **Criticality lives on the tag** (admin-defined tag metadata, Section 12.10 JSONB) — so "critical tags with an open fault" is computable by joining open `DefectReport`s to tags flagged critical.
- Raising a Work Order from a defect links them (`work_order_id`); closing the WO can auto-resolve the defect (Celery event, not a direct write).
- Search: keyword ILIKE on `defect_number`, description, tag name, asset tag + semantic on `description_embedding`.
- Export (4.6): defect register to xlsx/csv/pdf, filtered by status/severity/tag.
- **The fault does NOT start work by itself** — actual work is gated by the permit/access workflow in HSE (Phase 4.2). A defect can sit "Open" until a permit is granted.
- AI: "show all open critical faults" / "which tags have unresolved problems this week?"

**Endpoints:** `POST /defects`, `GET /defects` (filter by tag/asset/status/severity), `GET /defects/{id}`, `PATCH /defects/{id}` (status), `POST /defects/{id}/comments`, `POST /defects/search`, `POST /defects/export`.
**Permissions:** `defect:read`, `defect:write`, `defect:resolve`, `defect:export` (all seeded in `seed_rbac.py`).

---

#### Module 2.6 — Maintenance KPI Dashboard

**What it does:**
The maintenance "get a view of the product at a glance" page — KPI cards + charts + Excel/PDF export, built on the shared conventions (4.7 chart data, 4.6 export).

**KPI cards (`GET /kpi/maintenance`):**
- **Number of critical tags with an open fault** (the headline maintenance KPI) — *KPI card, trend vs last week*
- Open work-order backlog (by priority) — *KPI card*
- MTTR (mean time to repair) and MTBF — *KPI cards with trend*
- PM compliance % (PMs done on time ÷ PMs due) — *gauge vs target*
- Overdue work orders — *KPI card*

**Charts (`GET /reports/maintenance/...`, chart-data shape 4.7):**
- `/reports/maintenance/backlog-trend` — open WOs over time → **line**
- `/reports/maintenance/wo-by-status` — WO status breakdown → **donut**
- `/reports/maintenance/faults-by-criticality` — open defects by tag criticality (A/B/C) → **stacked bar**
- `/reports/maintenance/top-failing-tags` — tags/assets with most faults this period → **horizontal bar**
- `/reports/maintenance/pm-compliance` — compliance % over time → **line with target band**
- `/reports/maintenance/maintenance-cost` — labor + material cost over time, base currency → **bar**

**Summary page:** KPI cards row (critical-tags-with-faults first), backlog line + status donut, faults-by-criticality + top-failing-tags, PM-compliance line, cost bar. Filter bar (period, unit/plant, criticality) + **Export to Excel / PDF**.
**Permissions:** `maintenance:read`, `maintenance:export`.

---

### PHASE 3 — Human Resources

#### Module 3.1 — Employee Management

**Entities:**
- `Department` (organizational units)
- `Position` (job title/role within org)
- `Employee` (master record: personal info, position, department, hire date)
- `OrgChart` (derived from Employee.department + Employee.reports_to)
- `EmployeeDocument` (contracts, ID copies, qualifications)

**Key features:**
- Org chart visualization data
- Employee linked to User account (or standalone if they don't use the system)
- Position-based access control (integrates with existing RBAC)
- AI: "who is the maintenance manager?" or "list all engineers in Instrument department"

---

#### Module 3.2 — Leave Management

**Entities:**
- `LeaveType` (Annual, Sick, Emergency, etc.)
- `LeaveBalance` (per employee per year)
- `LeaveRequest` (employee requests leave)
- `LeaveApproval` (manager approves/rejects)
- `LeaveCalendar` (view team availability)

---

#### Module 3.3 — Training & Certification

**Entities:**
- `Training` (course name, provider, duration)
- `Certification` (certifications required for certain jobs: H2S, BOSIET, etc.)
- `EmployeeTraining` (employee completed a training on a date, expiry date)
- `EmployeeCertification` (employee holds a cert, expiry alert)
- `TrainingPlan` (annual training plan per department)

**AI touchpoint:** "which employees have expired H2S certification?"

---

### PHASE 4 — Full Platform

#### Module 4.1 — Internal Communication

**Entities:**
- `Letter` (formal internal letter / memo with reference number)
- `LetterRecipient` (to whom, CC)
- `LetterAttachment`
- `Announcement` (broadcast to roles/departments)
- `InternalMessage` (thread-based messaging between users)

**Key features:**
- Auto-numbering for formal letters (e.g., MAINT-2026-001)
- Letter status: Draft → Sent → Acknowledged
- Full-text search on all letters
- AI: "find all letters about pump P-1001 in the last 6 months"

---

#### Module 4.2 — HSE Module

**Entities:**
- `Incident` (near miss, first aid, LTI, fatality, environmental)
- `IncidentInvestigation` (root cause analysis)
- `PermitToWork` (hot work, confined space, electrical isolation, height)
- `PTWStep` (steps completed on permit)
- `WorkAccessRequest` — **the "I want to fix this" request** (see workflow below)
- `WorkAccessApproval` — one per required approver group (HSE, Manager)
- `RiskAssessment` (job safety analysis)
- `SafetyObservation` (positive or negative safety behavior observed)
- `HSEStatistic` (weekly/monthly KPIs: TRIR, LTI days, etc.)

**Key features:**
- Permit to Work is a critical safety gate before maintenance work begins
- **People who hold the permit-issuer role can create/issue permits** (RBAC-gated)
- PTW can be linked to a Work Order (WO cannot start without valid PTW)
- Incident reports are confidential (role-restricted access)
- AI: "what is our TRIR for Q1?" or "show all open hot work permits"

**Work-permit & access-grant workflow (the maintenance "request access to fix it" flow):**
This is the back half of the loop that starts with a Phase 2 Defect Report (Module 2.5). A fault is open on a tag; someone wants to fix the failed asset; they must be granted access by **both the HSE team and the Manager team** before work can begin.

```
DefectReport (Phase 2: "tag X has a problem, pump under it failed")
        │
        ▼
WorkAccessRequest  (technician/supervisor: "I want to fix this")
   ├── defect_id (optional link to the Phase 2 fault)
   ├── work_order_id (optional)
   ├── tag_id, asset_id
   ├── requested_by, requested_at, reason / scope of work
   ├── required_permit_types (hot work, confined space, ...)
   └── status: Requested → (HSE + Manager approve) → Granted → Active → Closed
                       └→ Rejected (by either group, with reason)
        │
        ▼  dual approval — BOTH groups required, order-independent
   WorkAccessApproval(group = HSE,      approver, decision, decided_at, note)
   WorkAccessApproval(group = MANAGER,  approver, decision, decided_at, note)
        │
        ▼  only when both = Approved
   PermitToWork issued + linked  →  Work Order may go to In Progress
```

- **Dual approval via the Approval Workflow Engine (4.2):** the workflow has two parallel approver groups — `hse_team` and `manager_team`. The request is `Granted` only when **both** approve; **either** can reject (with a reason), which blocks the work.
- **Gate on Work Orders:** a WO tied to this access request cannot transition to `In Progress` until status = `Granted` and a valid `PermitToWork` exists (extends the existing "WO cannot start without valid PTW" rule).
- **Notifications (4.1):** request raised → notify HSE + Manager queues; each decision → notify requester; granted → notify maintenance.
- **RBAC:** `hse:permit_approve` (HSE team), `maintenance:access_approve` (Manager team), `maintenance:access_request` (anyone who may request). All seeded; the agent inherits exactly the caller's rights (§12.11) — it can *draft* a request but only an authorized human approves.
- **Audit (4.3):** who requested, who approved/rejected each group, and when — fully logged.
- AI: "request access to fix the failed pump on tag X" (draft-and-confirm) / "what access requests are waiting on HSE approval?"

---

#### Module 4.3 — AI Manager Agent

**What it does:**
A conversational agent that a manager can ask questions and get cross-module answers.

**How it works (technical):**
- Agent receives a natural language question
- Agent determines which modules are relevant (tool selection)
- Agent calls each relevant module's `/ask` endpoint
- Agent synthesizes results into a coherent answer with sources
- Optionally generates a structured report

**Example queries:**
- "What is the current state of the maintenance backlog?"
- "Which assets have had the most failures this year?"
- "What materials are below minimum stock level?"
- "How many employees are on leave this week?"
- "Show me all overdue work orders for the compressor train"

**Technical approach:**
- Uses existing `core/agents/` skeleton
- Each module registers itself as an "agent tool"
- LangChain tool-use or function-calling pattern
- Results include source references (which WO, which asset, etc.)

---

## 6. Shared Technical Requirements

### Search (every module must have this — see Section 2.1 for the complete standard)
```
POST /purchase/orders/search    → {query, mode: "keyword"|"semantic"|"hybrid", limit}
POST /warehouse/items/search    → same pattern
POST /work-orders/search        → same pattern
GET  /warehouse/items/?q=...    → quick shortcut, calls keyword search internally
```
Implementation standard (as established in Section 2.1 and implemented in `financial_management/search/`):
- **Keyword**: `ILIKE '%query%'` across meaningful text columns — fast, no index required to start.
  Add a `pg_trgm` GIN index on high-traffic tables once query volume warrants it.
- **Semantic**: pgvector `<=>` cosine distance on `embedding` column (Vector 1024, Jina embeddings).
- **Hybrid**: run both, merge and deduplicate by entity ID.
- Do NOT use `tsvector` / `tsquery` — the existing implementation uses ILIKE and that is the project standard.
  If full-text ranking becomes a priority, it can be added as an optional enhancement in Phase 4 without changing the search interface.

### Document Attachment (every module must have this)
Every entity should support: `POST /assets/{entity_type}/{entity_id}/documents`
Uses existing `document_management` + `file_assets` system.

### Tag Support (every module must have this)
Every entity should support: `POST /tags/{entity_type}/{entity_id}`
Uses existing `tag_management` system.

### Audit Trail (every write endpoint)
Log: user_id, action, entity_type, entity_id, old_value, new_value, timestamp

### Pagination + Filtering (every list endpoint)
Standard: `?page=1&size=20&sort=created_at&order=desc&status=active`

### RBAC and Access Control (every module)

Access control is **critically important** and is not an afterthought.

#### What already exists (do not rebuild)

`deps.py` already has:
- `get_current_user()` — JWT decode + user load
- `require_permission(name)` — returns a FastAPI dependency that raises 403 if the user lacks the permission
- `require_permissions(*names)` — same but for multiple required permissions
- `get_user_permissions(user)` — returns the full set of permission names for a user

`Models/rbac.py` already has:
- `Permission(name, resource, action, description)` — one row per permission string
- `Role(name, company_id, is_system, is_active)` — company-scoped or system-wide
- `role_permission` association table
- `user_role` association table

`db/seed_rbac.py` is the pattern for seeding permissions and roles at startup.

#### Permission naming convention — matches existing code exactly

The existing system uses three parts: **`{module}:{sub-resource}:{action}`**

```
name (Permission.name)     resource (Permission.resource)    action (Permission.action)
─────────────────────────  ───────────────────────────────   ──────────────────────────
financial_management:receipts:read   financial_management.receipts   read
financial_management:cards:create    financial_management.cards      create
documents:versions:manage            documents.versions              manage
users:roles:manage                   users.roles                     manage
```

When the module has only one primary entity (no sub-resources needed), use two parts:
```
documents:read      resource=documents      action=read
buying_management:create   resource=buying_management   action=create
```

**Rule: use three parts when different roles need different access to different resource types within the same module.**
Use two parts when all entities in the module share the same access pattern.

Standard actions (use exactly these strings — no invented verbs):
| Action | Meaning |
|---|---|
| `read` | GET list + GET detail |
| `create` | POST (new record) |
| `update` | PATCH / PUT (edit existing) |
| `delete` | DELETE / soft-delete |
| `search` | POST /search (keyword + semantic + hybrid) |
| `ask` | POST /ask (AI natural language query) |
| `approve` | Workflow approval gate (submit / approve / reject) |
| `manage` | Combined create+update+delete on a sub-resource (when splitting is unnecessary) |
| `summary` | GET aggregated totals / KPI dashboard endpoint |
| `use` | Service invocation (e.g. STT — not CRUD) |

#### Every module must: declare → seed → protect

**1. Declare permissions in `{module}/permissions.py`:**
```python
# purchase_management/permissions.py
PERMISSIONS = [
    ("purchase_management:orders:read",    "purchase_management.orders",  "read",    "View purchase orders"),
    ("purchase_management:orders:create",  "purchase_management.orders",  "create",  "Create purchase orders"),
    ("purchase_management:orders:update",  "purchase_management.orders",  "update",  "Edit purchase orders"),
    ("purchase_management:orders:delete",  "purchase_management.orders",  "delete",  "Delete/cancel purchase orders"),
    ("purchase_management:orders:approve", "purchase_management.orders",  "approve", "Approve or reject purchase orders"),
    ("purchase_management:orders:search",  "purchase_management.orders",  "search",  "Search purchase orders"),
    ("purchase_management:orders:ask",     "purchase_management.orders",  "ask",     "Ask AI about purchase orders"),
    ("purchase_management:phases:manage",  "purchase_management.phases",  "manage",  "Create/update delivery phases"),
    ("purchase_management:costs:manage",   "purchase_management.costs",   "manage",  "Add/update additional costs"),
    ("purchase_management:summary",        "purchase_management",         "summary", "View procurement totals"),
]
```

**2. Seed permissions in the module's Alembic migration:**
```python
# In the upgrade() function — runs once when migration is applied
from db.seed_rbac import get_or_create_permission
from sqlalchemy.orm import Session

def upgrade():
    # ... table DDL first ...
    bind = op.get_bind()
    session = Session(bind=bind)
    from purchase_management.permissions import PERMISSIONS
    for name, resource, action, description in PERMISSIONS:
        get_or_create_permission(session, name, resource, action, description)
    session.commit()
```

**3. Protect every route with the existing `require_permission()` dependency:**
```python
from deps import require_permission

@router.post("/purchase/orders")
def create_order(
    ...,
    current_user: User = Depends(require_permission("purchase_management:orders:create"))
):
    ...

@router.patch("/purchase/orders/{id}/approval")
def approve_order(
    ...,
    current_user: User = Depends(require_permission("purchase_management:orders:approve"))
):
    ...
```

No route is left unprotected — even read-only list and GET detail endpoints require `{module}:read`.

**4. Cross-module Celery tasks run as system** — no `require_permission()` inside the task.
The route that dispatches the task already verified the user's permission before dispatching.

---

#### Complete permission list — all CMMS modules

Each module seeds these into `permissions` on migration. Copy the tuple format from `db/seed_rbac.py`.

**Phase 0 — Foundation**

`shared/currency/`:
```
currencies:read          currencies       read     View currencies and exchange rates
currencies:create        currencies       create   Add a currency
currencies:manage        currencies       manage   Manage currencies (admin only)
exchange_rates:create    exchange_rates   create   Enter an exchange rate
exchange_rates:read      exchange_rates   read     View exchange rate history
```

`purchase_management/`:
```
purchase_management:orders:read      purchase_management.orders    read     View purchase orders
purchase_management:orders:create    purchase_management.orders    create   Create purchase orders
purchase_management:orders:update    purchase_management.orders    update   Edit purchase orders
purchase_management:orders:delete    purchase_management.orders    delete   Delete/cancel purchase orders
purchase_management:orders:approve   purchase_management.orders    approve  Approve or reject purchase orders
purchase_management:orders:search    purchase_management.orders    search   Search purchase orders
purchase_management:orders:ask       purchase_management.orders    ask      Ask AI about purchase orders
purchase_management:phases:manage    purchase_management.phases    manage   Create/update delivery phases
purchase_management:costs:manage     purchase_management.costs     manage   Add/update additional costs
purchase_management:summary          purchase_management           summary  View procurement totals
```

---

**Phase 1 — Commerce & Warehouse**

`supplier_management/`:
```
supplier_management:read     supplier_management   read     View suppliers
supplier_management:create   supplier_management   create   Add suppliers
supplier_management:update   supplier_management   update   Edit suppliers
supplier_management:delete   supplier_management   delete   Delete suppliers
supplier_management:search   supplier_management   search   Search suppliers
supplier_management:ask      supplier_management   ask      Ask AI about suppliers
```

`material_management/`:
```
material_management:read     material_management   read     View material master items
material_management:create   material_management   create   Create items
material_management:update   material_management   update   Edit items
material_management:delete   material_management   delete   Delete items
material_management:search   material_management   search   Search items
material_management:ask      material_management   ask      Ask AI about materials
material_management:import   material_management   import   Bulk import items via Excel
```

`requisition_management/`:
```
requisition_management:read      requisition_management   read     View material requisitions
requisition_management:create    requisition_management   create   Create requisitions
requisition_management:update    requisition_management   update   Edit requisitions
requisition_management:delete    requisition_management   delete   Delete/cancel requisitions
requisition_management:approve   requisition_management   approve  Approve or reject requisitions
requisition_management:search    requisition_management   search   Search requisitions
```

`rfq_management/`:
```
rfq_management:read      rfq_management   read     View RFQs and quotation responses
rfq_management:create    rfq_management   create   Create RFQs
rfq_management:update    rfq_management   update   Edit RFQs
rfq_management:delete    rfq_management   delete   Delete RFQs
rfq_management:approve   rfq_management   approve  Select winning quotation
rfq_management:search    rfq_management   search   Search RFQs
```

`goods_receipt_management/`:
```
goods_receipt_management:read     goods_receipt_management   read     View GRNs
goods_receipt_management:create   goods_receipt_management   create   Create GRNs
goods_receipt_management:update   goods_receipt_management   update   Edit GRNs
goods_receipt_management:approve  goods_receipt_management   approve  Confirm GRN receipt
goods_receipt_management:search   goods_receipt_management   search   Search GRNs
```

`warehouse_management/`:
```
warehouse_management:locations:read      warehouse_management.locations   read     View warehouse/zone/shelf/bin
warehouse_management:locations:manage    warehouse_management.locations   manage   Create/edit locations
warehouse_management:stock:read          warehouse_management.stock       read     View stock levels
warehouse_management:stock:manage        warehouse_management.stock       manage   Adjust stock manually
warehouse_management:movements:read      warehouse_management.movements   read     View stock movement history
warehouse_management:movements:create    warehouse_management.movements   create   Record manual stock movement
warehouse_management:search              warehouse_management             search   Search stock/items
warehouse_management:summary             warehouse_management             summary  View stock valuation totals
```

---

**Phase 2 — Maintenance**

`asset_management/`:
```
asset_management:read     asset_management   read     View assets (plant/system/asset hierarchy)
asset_management:create   asset_management   create   Create assets
asset_management:update   asset_management   update   Edit assets
asset_management:delete   asset_management   delete   Delete assets
asset_management:search   asset_management   search   Search assets
asset_management:ask      asset_management   ask      Ask AI about assets
```

`work_order_management/`:
```
work_order_management:read     work_order_management   read     View work orders
work_order_management:create   work_order_management   create   Create work orders
work_order_management:update   work_order_management   update   Edit work orders
work_order_management:delete   work_order_management   delete   Delete work orders
work_order_management:approve  work_order_management   approve  Approve work orders
work_order_management:close    work_order_management   close    Close completed work orders
work_order_management:search   work_order_management   search   Search work orders
work_order_management:ask      work_order_management   ask      Ask AI about work orders
work_order_management:summary  work_order_management   summary  View maintenance KPIs
```

`pm_management/` (Preventive Maintenance):
```
pm_management:read     pm_management   read     View PM plans and schedules
pm_management:create   pm_management   create   Create PM plans
pm_management:update   pm_management   update   Edit PM plans
pm_management:delete   pm_management   delete   Delete PM plans
pm_management:search   pm_management   search   Search PM plans
```

`inspection_management/`:
```
inspection_management:read     inspection_management   read     View inspection checklists and results
inspection_management:create   inspection_management   create   Create checklists
inspection_management:update   inspection_management   update   Edit checklists and record results
inspection_management:delete   inspection_management   delete   Delete checklists
inspection_management:search   inspection_management   search   Search inspection records
```

---

**Phase 3 — HR & Communication**

`hr_management/`:
```
hr_management:employees:read      hr_management.employees   read     View employees
hr_management:employees:create    hr_management.employees   create   Add employees
hr_management:employees:update    hr_management.employees   update   Edit employee records
hr_management:employees:delete    hr_management.employees   delete   Delete employee records
hr_management:employees:search    hr_management.employees   search   Search employees
hr_management:leave:read          hr_management.leave       read     View leave requests
hr_management:leave:create        hr_management.leave       create   Submit leave requests
hr_management:leave:approve       hr_management.leave       approve  Approve/reject leave requests
hr_management:training:read       hr_management.training    read     View training and certifications
hr_management:training:manage     hr_management.training    manage   Create/update training records
hr_management:summary             hr_management             summary  HR dashboards and org chart
```

`communication_management/`:
```
communication_management:letters:read     communication_management.letters   read     Read internal letters
communication_management:letters:create   communication_management.letters   create   Write letters
communication_management:letters:update   communication_management.letters   update   Edit draft letters
communication_management:letters:delete   communication_management.letters   delete   Delete letters
communication_management:letters:search   communication_management.letters   search   Search letters
communication_management:letters:ask      communication_management.letters   ask      Ask AI about letters
communication_management:announcements:read     communication_management.announcements   read     Read announcements
communication_management:announcements:manage   communication_management.announcements   manage   Create/edit announcements
```

`hse_management/`:
```
hse_management:incidents:read      hse_management.incidents   read     View HSE incidents
hse_management:incidents:create    hse_management.incidents   create   Report an incident
hse_management:incidents:update    hse_management.incidents   update   Edit incident records
hse_management:incidents:close     hse_management.incidents   close    Close an investigation
hse_management:incidents:search    hse_management.incidents   search   Search incidents
hse_management:incidents:ask       hse_management.incidents   ask      Ask AI about incidents
hse_management:permits:read        hse_management.permits     read     View permits to work
hse_management:permits:create      hse_management.permits     create   Issue a permit
hse_management:permits:approve     hse_management.permits     approve  Approve/reject/close permits
hse_management:summary             hse_management             summary  HSE statistics dashboard
```

---

#### Record-level (part-specific) access — future phase

In Phases 0–3, permissions are at the **module + sub-resource + action** level.
A user either can or cannot create purchase orders across the whole system.

After Phase 3, **record-level scoping** will be layered on top without changing permission names.
The `require_permission()` dependency in `deps.py` will accept an optional `scope_checker`:

```python
# Future — deps.py extension (backward compatible: scope_checker defaults to None)
def require_permission(permission_name: str, scope_checker=None):
    def checker(request: Request, current_user: User = Depends(get_current_user)) -> User:
        # 1. Check permission name (already works today)
        permissions = get_user_permissions(current_user)
        if permission_name not in permissions:
            raise HTTPException(403, "Permission denied")
        # 2. Check record scope (only when activated)
        if scope_checker is not None:
            scope_checker(request, current_user)   # raises 403 if out of scope
        return current_user
    return checker
```

Examples of scopes that will be added:
- `facility_scope_checker` — user can only access records belonging to their facility/site
- `assignee_scope_checker` — maintenance engineer can only close WOs assigned to them
- `department_scope_checker` — HR officer can only see employees in their department

Until scopes are activated, `scope_checker=None` and no record-level check runs — existing routes are untouched.

---

#### Seeded roles and their default permissions

Roles are company-configurable. These are the system defaults seeded at startup.
Admins can create custom roles and assign any combination of permissions.

| System Role | Default permissions |
|---|---|
| `admin` | All permissions |
| `purchase_manager` | `purchase_management:orders:*`, `purchase_management:phases:manage`, `purchase_management:costs:manage`, `purchase_management:summary`, `supplier_management:read`, `material_management:read`, `currencies:read`, `exchange_rates:read` |
| `warehouse_manager` | `warehouse_management:*`, `goods_receipt_management:*`, `purchase_management:orders:read`, `material_management:read` |
| `maintenance_engineer` | `work_order_management:read`, `work_order_management:create`, `work_order_management:update`, `work_order_management:close`, `asset_management:read`, `pm_management:read`, `inspection_management:*` |
| `maintenance_manager` | `work_order_management:*`, `asset_management:*`, `pm_management:*`, `inspection_management:*`, `work_order_management:summary` |
| `hr_manager` | `hr_management:*` |
| `hse_officer` | `hse_management:*` |
| `viewer` | All `:read` and `:search` permissions across all modules |

---

## 7. Implementation Order — Phase by Phase

Each phase is a self-contained deliverable. Work through the prompts in the listed order within each phase.
Each module follows the same internal structure:

```
[Module Name]
  ├── Models (SQLAlchemy + pgvector embedding column)
  ├── Alembic migration
  ├── Schemas (Pydantic request/response)
  ├── Services (business logic)
  ├── Routes (FastAPI APIRouter)
  ├── search/ subfolder (keyword ILIKE + pgvector semantic + hybrid — Section 2.1)
  ├── RBAC permissions declared in {module}/permissions.py + seeded in migration (Section 6)
  ├── AI /ask endpoint
  └── Frontend spec
```

---

### Phase 0 — Foundation (Do Before Everything Else)

Run prompts in this order (currency must exist before purchase_management):

| Order | Prompt | What gets built |
|---|---|---|
| 1st | Prompt 0.3 | `shared/currency/` — Currency + ExchangeRate tables, `/currencies` endpoints |
| 2nd | Prompt 0.2 | `purchase_management/` — PurchaseOrder + Phases, replaces buying_management entirely |
| 3rd | Prompt 0.1 | Celery refactor — STT async, TaskResult model, `GET /tasks/{task_id}` polling |

> **Phase 0-AI (parallel track — Assistant Core).** Build `backend/assistant/` per **Section 12**: the LangGraph
> stateful agent (intent router, interruption pause/resume, cancel), Postgres checkpointer, `AgentRun` + `Draft`
> models, draft-and-confirm framework (multilingual), multimodal intake (heavy vs inline), general-knowledge
> branch, the Module Tool Contract + registry, error-catalog consolidation/auto-export (Section 12.9), and the
> tag-metadata schema (Section 12.10). Refactor the existing `core/agents/` + `routs/chat.py` into it and register
> the first tool sets (documents, comments, financial). Full test suite per Section 12.12. Done by a separate
> developer in parallel; depends on the Phase 0 module APIs.

---

### Phase 1 — Commerce & Warehouse

| Prompt | Module | Key entities |
|---|---|---|
| Prompt 1 | `supplier_management` | Supplier, Contact, SupplierCategory, SupplierEvaluation |
| Prompt 2 | `material_management` | Item (Material Master), ItemCategory, Unit of Measure, ItemAlternative |
| Prompt 3 | `requisition_management` | MaterialRequisition, RequisitionItem, approval workflow |
| Prompt 4 | `rfq_management` | RequestForQuotation, QuotationResponse (multi-supplier) |
| Prompt 5 | `goods_receipt_management` | GoodsReceiptNote (GRN), GRN Items, links to PurchasePhase |
| Prompt 6 | `warehouse_management` | Warehouse, Zone, Shelf, Bin, StockItem, StockMovement |
| Prompt 7 | Phase 1 KPIs | Procurement dashboards: PO cycle time, GRN vs PO variance, stock value |

> **Phase 1-AI (parallel track).** Register tool sets (search/summarize/ask/add_draft) for supplier,
> material, requisition, RFQ, goods-receipt, and warehouse into the Assistant Core (Section 12.4/12.13). Enables
> chat to e.g. "add this supplier", "how many of item X are in the main warehouse", "find POs for supplier Y".
> Full test suite per Section 12.12.

---

### Phase 2 — Maintenance

| Prompt | Module | Key entities |
|---|---|---|
| Prompt 8 | `asset_management` | Plant, System, Asset (hierarchy), AssetSpare, AssetHistory |
| Prompt 9 | `work_order_management` | WorkOrder (CM), WorkOrderTask, Labor tracking, Material tracking |
| Prompt 10 | `work_order_management` (cont.) | WO approval workflow, WO close, MTTR/downtime KPIs |
| Prompt 11 | `pm_management` | MaintenancePlan, MaintenanceTask, TaskFrequency, PMSchedule (Celery auto-gen) |
| Prompt 12 | `inspection_management` | InspectionChecklist, ChecklistItem (Pass/Fail/Measure), execution records |
| Prompt 14 (§8) | `defect_management` | DefectReport, DefectComment — "a tag has a problem; the pump under it failed" → links to WO |
| Prompt 13 | Phase 2 KPIs | Asset KPIs: MTBF, MTTR, OEE, maintenance backlog, PM compliance, **critical tags with open faults** |
| Prompt 15 (§8) | `shared/export` + dashboards | Excel/CSV/PDF export + KPI/chart-data endpoints (build once, used by the maintenance dashboard and every later module) |

> **Phase 2-AI (parallel track).** Register tool sets for assets, work orders, PM, inspections, and defects into the
> Assistant Core (Section 12.4/12.13) — e.g. "raise a work order for pump P-1001", "what PM is due next week",
> "report a fault on tag X", "export open critical faults to Excel". Full test suite per Section 12.12.
> **Defect/Fault Reporting (Module 2.5)** and the **Export Engine (4.6) + dashboard convention (4.7)** are detailed
> in §8 Prompts 14 and 15. The permit/access-grant approval that follows a fault is in **Phase 4 (HSE, 4.2)**.

---

### Phase 3 — HR & Communication

| Prompt | Module | Key entities |
|---|---|---|
| Prompt 14 | `hr_management` | Department, Position, Employee, org chart |
| Prompt 15 | `hr_management` (cont.) | Leave Management, Training & Certification, Employee documents |
| Prompt 16 | `communication_management` | Internal Letters, Announcements, Message threads |
| Prompt 17 | `hse_management` | HSE Incident, Investigation, Permit to Work, HSE statistics |
| Prompt 18 | Phase 3 KPIs | HR dashboards: headcount, leave utilisation, training compliance, HSE incident rate |

> **Phase 3-AI (parallel track).** Register tool sets for HR, communication/letters, and HSE into the Assistant
> Core (Section 12.4/12.13) — e.g. "who is on leave this week", "find letters about P-1001", "report a near
> miss". Full test suite per Section 12.12.

---

### Phase 4 — Full Platform + AI Agent

| Prompt | Module | What gets built |
|---|---|---|
| Prompt 19 | Notification Engine | Cross-module event → notification routing (bell + email via Celery) |
| Prompt 20 | AI Manager Agent | **Now the mature state of the Assistant Core (Section 12)** — cross-module orchestration over the per-phase tool registry, manager dashboard synthesis, report formatting. Not a from-scratch build. |
| Prompt 21 | Manager Dashboard API | Unified KPI aggregation endpoint consumed by the frontend dashboard (built on 4.7 chart-data + 4.6 export) |
| Prompt 22 | Module Refactor | **Merged into the single Phase 4.7 spec** — clean the code seams: remove cross-module model/route/schema imports (tag_management, model_management, property_management; delete buying_management remnants; strip Models/__init__.py to discovery). Reads → service functions, writes → events. FKs stay (§0.5). |
| Prompt 23 | Route Versioning / service-boundary lock | **Merged into the single Phase 4.7 spec** — add a route version prefix and lock each module to its service-layer seam (microservice-extraction prep). No business-logic change (§0.5 extraction recipe). |

> **HSE permit & access-grant workflow (Phase 4.2).** The HSE module (see §8 Prompt 12) adds the
> `WorkAccessRequest` + dual-approval (`WorkAccessApproval`: HSE team **and** Manager team) flow that follows a
> Phase 2 DefectReport. A Work Order cannot start until a valid PTW exists **and** the access request is Granted
> by both groups. HSE also ships KPI/chart + Excel/PDF export per 4.6/4.7.

> **Phase 4-AI (parallel track).** Finalize cross-module orchestration in the Assistant Core: multi-tool
> synthesis with cited sources, the manager dashboard aggregation, and (when designed) the future
> file/document-generation service (Section 12.14). The "AI Manager Agent" (Prompt 20) is the culmination of the
> Assistant Core built since Phase 0-AI, per **Section 12**. Full test suite per Section 12.12.

---

## 8. Prompts for Each Implementable Module

Use prompts in the order defined in Section 7. Each prompt is self-contained — copy it into a new chat session with full project context so the implementation can be planned and coded in detail.

**Every prompt already includes the modular monolith rules. The implementation must follow them:**
- No cross-module SQLAlchemy model imports
- No calling another module's route functions
- Cross-module writes via Celery tasks only (not direct service calls)
- Shared types in `backend/shared/` only
- Each module owns its migrations independently
- Heavy operations (>200ms) go to Celery; route returns 202 + task_id (see Rule 10)
- Every module includes a `search/` subfolder (keyword ILIKE + pgvector semantic + hybrid — Section 2.1)
- Every module declares its RBAC permissions (see RBAC Architecture below)
- At the end of each module plan: include a "What you could add next" suggestions list

---

### Prompt 0.1 — Phase 0: Heavy Processing → Celery (Run Third)

```
PROJECT CONTEXT:
We are building a CMMS for the petroleum industry on top of an existing RAG/KMS system.
Backend: FastAPI + PostgreSQL + pgvector + SQLAlchemy + Alembic + Celery.
Architecture: modular monolith targeting future microservice extraction. Each module is its own folder.
Apps communicate via service functions and Celery events only — no cross-module model imports.
Database: PostgreSQL + pgvector. Search: keyword (ILIKE) + semantic (pgvector) + hybrid.
Existing Celery setup: core/celery/celery_app.py + core/celery/tasks.py (mineru_process_pdf already there).
STT route: routs/stt.py — currently calls external STT API synchronously inside the request cycle.
Document processing: routs/documents.py → complete_document_upload already dispatches mineru_process_pdf.delay ✓

RULE: Route URL and request body schema do not change. Only the internal execution path changes.
RULE: Response schema changes — callers that expected a synchronous result must be updated to poll.
      This is acceptable: the frontend has not shipped yet and can be updated in the same release.

TODAY'S TASK: Move heavy processing to Celery without changing any routes.

WHAT NEEDS TO CHANGE:
1. routs/stt.py — the upload-and-transcribe path calls `await _send_audio_to_stt()` synchronously.
   Move the actual transcription to a Celery task. Route returns 202 + {task_id, status: "queued"}.
   The response schema should include all existing fields as nullable + task_id + status.
2. TaskResult model (new, in Models/task_result.py):
   task_id (UUID), celery_task_id, task_type (str), status (queued/processing/done/failed),
   result_json (JSONB), error_message, created_by (user_id), created_at, updated_at
3. GET /tasks/{task_id} — new shared polling endpoint in routs/tasks.py
   Returns: {task_id, status, result, error, created_at, updated_at}
   Checks Celery task state + TaskResult row.
4. core/celery/tasks.py — add transcribe_audio_task(asset_id, user_id, language) Celery task
   that calls the STT service and writes result to TaskResult.

CHANGE IMPACT:
- STT route URL: unchanged ✓
- STT request body: unchanged ✓
- STT response schema: CHANGES — was synchronous result, now returns {task_id, status: "queued"}.
  Frontend must be updated to poll GET /tasks/{task_id} for the result. This is expected.
- New /tasks/ endpoint: purely additive ✓
- TaskResult table: new table, no existing data affected ✓

Please provide:
A) TaskResult model with all fields
B) Updated STT route handler (show before/after diff in approach)
C) transcribe_audio_task Celery task implementation
D) GET /tasks/{task_id} endpoint
E) Alembic migration for task_results table
F) What you could add next (suggestions list)
```

---

### Prompt 0.2 — Phase 0: Purchase Management (Clean Rewrite — Run Second)

```
PROJECT CONTEXT:
We are building a CMMS for the petroleum industry on top of an existing RAG/KMS system.
Backend: FastAPI + PostgreSQL + pgvector + SQLAlchemy + Alembic + Celery.
Architecture: modular monolith targeting future microservice extraction.
Rules: no cross-module model imports; Celery for cross-module writes; each module owns its migrations.
Database: PostgreSQL + pgvector. Search: keyword (ILIKE) + semantic (pgvector <=> operator) + hybrid.
Existing relevant modules: financial_management (financial_receipts table + /financial/receipts routes),
property_management (warehouse), shared/currency/ (Currency + ExchangeRate tables — built in Phase 0.3).

TODAY'S TASK: Delete buying_management entirely and build purchase_management as a clean new module.
No backward compatibility with buying_management — no other team has implemented against it.
The old folder, tables, and routes are gone. Build fresh.

WHAT WAS WRONG WITH buying_management (do NOT replicate):
- BuyingProcessItem linked stock/PO lines directly to model_management.ManagedModel (the equipment-model
  catalog — see Glossary §0). PO lines must resolve through the Item catalog (Item.model_id is optional). Items in a PO
  are materials/spare parts/consumables. This FK is semantically wrong.
- affects_warehouse Boolean flag on BuyingProcess — wrong pattern. Warehouse interaction must go
  through a Celery event, not a flag on the purchase model.
- Route prefix /buying/. Replace with /purchase/.

NEW MODULE: backend/purchase_management/

MODELS (all new — no legacy):
1. PurchaseOrder (table: purchase_orders)
   - id, reference_number (auto: PO-2026-0001), title, description
   - supplier_id (nullable; plain INTEGER in Phase 0 because the Supplier module does not exist yet — becomes a
     real FK → supplier_management.suppliers.id in the shared DB once Phase 1 ships, resolved via the
     supplier_management service, no model import; §0.5)
   - supplier_name (VARCHAR — free-text fallback for Phase 0 before the Supplier module exists)
   - currency_id FK → currencies.id, base_currency_id FK → currencies.id
   - exchange_rate_used (Numeric 28,10)
   - status: draft | ordered | shipped | received | closed | cancelled
   - approval_status: draft | pending | approved | rejected
   - description_embedding (Vector 1024 — nullable, for semantic search)
   - created_by_user_id, approved_by_user_id, created_at, updated_at

2. PurchasePhase (table: purchase_phases)
   - id, purchase_order_id FK → purchase_orders.id
   - phase_number (1, 2, 3...), title, description
   - status: draft | ordered | shipped | received | closed
   - currency_id FK → currencies.id (inherits from PO if null)
   - exchange_rate_used (Numeric 28,10)
   - expected_delivery_date, actual_delivery_date
   - created_at, updated_at

3. PurchasePhaseItem (table: purchase_phase_items)
   - id, phase_id FK → purchase_phases.id
   - item_name (VARCHAR — free text in Phase 0; in Phase 1 add item_id FK → material_management.items in the
     shared DB, resolved via the material_management service — do not import its model; §0.5)
   - item_code (VARCHAR nullable — SKU / part number)
   - quantity (Numeric), unit (VARCHAR: "pcs", "kg", "m", "L", etc.)
   - unit_price (Numeric), currency_id FK → currencies.id
   - unit_price_base (Numeric), base_currency_id FK → currencies.id
   - exchange_rate_used (Numeric 28,10)
   - line_total (Numeric), line_total_base (Numeric)
   - notes (Text nullable)

4. PurchaseOrderCost (table: purchase_order_costs)
   - id, purchase_order_id FK → purchase_orders.id
   - cost_type: freight | customs | tax | insurance | other
   - description, amount (Numeric), currency_id FK → currencies.id
   - amount_base (Numeric), base_currency_id FK → currencies.id
   - exchange_rate_used, allocation_method: per_item | per_value | manual

5. PurchaseOrderReceiptLink (table: purchase_order_receipt_links)
   - id, purchase_order_id FK → purchase_orders.id
   - financial_receipt_id FK → financial_management.financial_receipts.id (shared DB) — resolve the receipt via
     the financial_management service, never import its model; §0.5. (Real FK for integrity; clean code seam.)
   - linked_at, linked_by_user_id

ROUTES (prefix: /purchase/):
- POST   /purchase/orders                           — create PO
- GET    /purchase/orders                           — list (filter: status, approval_status, date range)
- GET    /purchase/orders/{id}                      — detail with phases
- PATCH  /purchase/orders/{id}                      — update
- DELETE /purchase/orders/{id}                      — soft delete (status → cancelled)
- PATCH  /purchase/orders/{id}/approval             — submit/approve/reject
- POST   /purchase/orders/{id}/phases               — add phase
- GET    /purchase/orders/{id}/phases               — list phases
- PATCH  /purchase/orders/{id}/phases/{phase_id}    — update phase status/dates
- POST   /purchase/orders/{id}/phases/{phase_id}/items          — add item
- PATCH  /purchase/orders/{id}/phases/{phase_id}/items/{item_id} — update item
- POST   /purchase/orders/{id}/costs                — add additional cost
- POST   /purchase/orders/{id}/receipt-links        — link payment receipt
- GET    /purchase/orders/{id}/summary              — totals by currency + base currency
- POST   /purchase/orders/search                    — keyword | semantic | hybrid search

CROSS-MODULE (warehouse notification via Celery — no direct model import):
When a PurchasePhase status changes to "received":
  notify_warehouse_of_receipt.delay(phase_id=phase.id)
The warehouse Celery task reads phase items via a DB query and creates intake records.
purchase_management never imports from property_management.

PERMISSIONS (declare in purchase_management/permissions.py, seed in Alembic migration):
  purchase:read, purchase:write, purchase:approve, purchase:delete, purchase:search
Every route must use: Depends(require_permission("purchase:write")) etc.
No route is left unprotected — including read-only list and detail endpoints.

SEARCH (purchase_management/search/ subfolder — follow financial_management/search/ pattern):
- repository.py: keyword ILIKE on reference_number, supplier_name, title, description
               semantic pgvector <=> on description_embedding
- service.py: mode routing (keyword | semantic | hybrid), merge by purchase_order_id
- routes.py: POST /purchase/orders/search — accepts {query, ids, mode, limit}

ALEMBIC MIGRATION ORDER:
PRECONDITION: Prompt 0.3 migration (currencies table) must already be applied before running this.
1. Drop old tables in order: buying_process_receipt_links, buying_process_costs,
   buying_process_items, buying_processes
2. Create new tables in order: purchase_orders, purchase_phases, purchase_phase_items,
   purchase_order_costs, purchase_order_receipt_links

ADDITIONAL CLEANUP (do alongside migration — server will not start without this):
- Remove `buying_management` import from `backend/Models/__init__.py`
  (this file imports all models for Alembic discovery; the old table is gone so the import breaks)
- Remove `buying_management/` folder entirely after migration is confirmed applied
- Update any reference to /buying/ prefix in api.py router registration → /purchase/

Please provide:
A) All 5 models with complete field definitions
B) Full Alembic migration (drop old tables, create new)
C) Routes file structure (router, all endpoints, schemas)
D) purchase_management/search/ — repository.py, service.py, routes.py
E) Celery task stub for notify_warehouse_of_receipt
F) Permissions list to register in RBAC
G) What you could add next (suggestions list)
```

---

### Prompt 0.3 — Phase 0: Multi-Currency Foundation (Run First)

```
PROJECT CONTEXT:
We are building a CMMS for the petroleum industry on top of an existing RAG/KMS system.
Backend: FastAPI + PostgreSQL + pgvector + SQLAlchemy + Alembic + Celery.
Existing currency situation: financial_management stores currency as free-text strings
(currency="USD", base_currency="IRT", exchange_rate_to_base=Numeric).
The FinancialCurrency enum in financial_management/models.py has: IRT, IRR, USD, AED, IQD, CNY.
NOTE: The old buying_management module has been deleted (Phase 0.2 clean rewrite).
Free-text currency strings on financial_receipts stay as-is — do not retrofit old tables.
purchase_management (built in Phase 0.2) uses currency_id FKs from day one and depends on this module.

TODAY'S TASK: Add Currency master table and ExchangeRate table as a new shared foundation.
Place in backend/shared/currency/ (shared module, not owned by any one domain module).

REQUIREMENTS:
1. Currency model (shared/currency/models.py):
   - code: VARCHAR(10), unique (USD, EUR, IRR, IRT, AED, IQD, CNY, GBP, ...)
   - name, symbol, decimal_places (INT), is_active (Boolean)
   - Pre-populate migration with all currencies already used in the system
2. ExchangeRate model (shared/currency/models.py):
   - from_currency_id, to_currency_id (FK to currencies)
   - rate: Numeric(28, 10) — high precision
   - effective_date (DATE) — rate valid from this date
   - source: 'manual' | 'api'
   - created_by_user_id, created_at
3. Company model: add nullable base_currency_id FK (companies.base_currency_id → currencies.id)
   Backward compatible: nullable, existing rows get NULL.
4. shared/currency/services.py:
   - get_rate(db, from_code, to_code, on_date) → Decimal (finds closest rate ≤ on_date)
   - convert(db, amount, from_code, to_code, on_date) → Decimal
5. New endpoints in shared/currency/routes.py:
   - GET  /currencies — list active currencies
   - POST /currencies — create currency (admin only)
   - GET  /currencies/exchange-rates — list rates (filterable by from/to/date range)
   - POST /currencies/exchange-rates — add a rate (finance_manager permission)
6. Register shared routes in api.py (additive only)

IMPACT:
- No existing tables changed except companies (nullable FK added — safe) ✓
- No existing endpoints changed ✓
- Free-text currency strings on financial_receipts stay as-is ✓
- purchase_management (Phase 0.2) uses currency_id FKs from day one — depends on this running first ✓
- All future new modules (Phase 1+) use currency_id FKs — never free-text strings again

Please provide:
A) All models with fields
B) services.py function signatures and logic
C) All endpoints
D) Alembic migration (new tables + nullable company FK + seed data)
E) Frontend spec: currency settings page, exchange rate entry
F) What you could add next
```

---

### PROMPT 0 — Currency & Exchange Rate (Day 1 — must come first)

```
PROJECT CONTEXT:
We are building a CMMS for the petroleum industry on top of an existing RAG/KMS system.
Backend: FastAPI + PostgreSQL (only) + SQLAlchemy + Alembic + Celery.
Architecture: each feature area is its own app folder. Apps communicate via REST API only.
Existing: document_management, tag_management, model_management (equipment-model catalog — see Glossary §0), buying_management (partial),
financial_management (partial), property_management (partial), RBAC, user/company, file assets, AI chat.
Database: PostgreSQL + pgvector extension. No Elasticsearch or ChromaDB needed.
Search stack: keyword (ILIKE on text columns) + semantic (pgvector <=> cosine similarity, Jina embeddings) + hybrid.
Every new module MUST implement a search/ subfolder following the financial_management/search/ pattern exactly:
- repository.py: keyword SQL (ILIKE) + semantic SQL (pgvector <=>)
- service.py: mode routing (keyword | semantic | hybrid), merge logic, graceful degradation
- routes.py: POST /{module}/search accepting {query, ids, mode, limit}
- embedding column: Vector(1024) on each searchable entity model
- ensure_{entity}_embeddings() function to auto-generate missing embeddings before search

ARCHITECTURAL GOAL — MODULAR MONOLITH → FUTURE MICROSERVICES:
This project is built as a modular monolith. Every module must be independently extractable into a
microservice in the future. To achieve this, ALL new code must follow these rules without exception:
1. NEVER import another module's SQLAlchemy model. Use that module's service functions instead.
2. NEVER call another module's route functions. Routes are HTTP handlers, not a service API.
3. Cross-module writes happen via Celery tasks (async event) — not synchronous service calls.
   Example: GRN finalized → publish Celery task → warehouse module handles it independently.
4. Types/enums shared between modules live in backend/shared/ only.
5. Each module has its own independent Alembic migrations — never mix two modules in one revision.
6. Models/__init__.py is for Alembic discovery only — no business code imports from it.
Note: The existing code (buying_management, tag_management, etc.) has violations of these rules.
Those will be fixed in Phase 4. All NEW modules must be clean from day one.

TODAY'S TASK: Currency & Exchange Rate module (shared foundation for all money in the system)
This must be built before anything that involves money (procurement, financial, warehouse valuation).

REQUIREMENTS:
1. Currency model: code (ISO 4217: USD/EUR/IRR/AED), name, symbol, decimal_places, is_active
2. ExchangeRate model:
   - from_currency_id, to_currency_id
   - rate (Numeric high precision, e.g. 28 digits, 10 decimal places)
   - effective_date (date the rate is valid from)
   - source: Manual / API_FETCHED
   - created_by (user)
3. Company base currency: add base_currency_id to existing Company model
4. Service function: get_rate(from_currency, to_currency, on_date) → returns closest rate on or before that date
5. Service function: convert(amount, from_currency, to_currency, on_date) → Decimal
6. RBAC: finance_manager can create/edit rates; all authenticated users can read
7. Admin can set which currency is the company's base currency

Money field convention (document this — every future module follows it):
  - amount: Decimal (the value in the transaction currency)
  - currency_id: FK to Currency
  - amount_base: Decimal (equivalent in company base currency at time of transaction)
  - exchange_rate_used: Decimal (rate applied — frozen at transaction time, never recalculated)

Please:
A) All models with fields, types, constraints
B) All API endpoints
C) The get_rate() and convert() service function signatures and logic
D) Alembic migration notes (including adding base_currency_id to companies table)
E) Frontend specification: currency list screen, exchange rate entry screen, rate history view
```

---

### PROMPT 1 — Supplier Management (Day 2)

```
PROJECT CONTEXT:
We are building a CMMS for the petroleum industry on top of an existing RAG/KMS system.
Backend: FastAPI + PostgreSQL (only) + SQLAlchemy + Alembic + Celery.
Architecture: each feature area is its own app folder. Apps communicate via REST API only.
Existing: document_management, tag_management, RBAC, user/company, file assets, AI chat.
Database: PostgreSQL + pgvector (semantic search already in use via JinaAPIEmbeddings + Vector(1024) columns). Keyword search: ILIKE on text columns (project standard — do NOT use tsvector). Semantic search: pgvector <=> cosine distance. Hybrid: merge both by entity ID. See Section 2.1 of master plan for the complete search pattern.

ARCHITECTURAL GOAL — MODULAR MONOLITH → FUTURE MICROSERVICES:
This project is built as a modular monolith. Every module must be independently extractable into a
microservice in the future. ALL new code must follow these rules without exception:
1. NEVER import another module's SQLAlchemy model. Use that module's service functions instead.
2. NEVER call another module's route functions. Routes are HTTP handlers, not a service API.
3. Cross-module writes happen via Celery tasks (async event) — not synchronous service calls.
4. Shared types/enums live in backend/shared/ only — never in one module imported by another.
5. Each module has its own independent Alembic migrations — never mix two modules in one revision.
6. Models/__init__.py is for Alembic discovery only — no business code imports from it.
Already built in this phase: Currency + ExchangeRate model.

TODAY'S TASK: Supplier Management module

REQUIREMENTS:
1. Supplier model: code (auto: SUP-001), name, type (Local/International/Manufacturer/Distributor),
   country, city, address, tax_id, website, status (Pending/Approved/Blacklisted), notes
2. SupplierContact: supplier_id, name, email, phone, position, is_primary
3. SupplierCategory: supplier_id, category_name (what product types they supply, many-to-many)
4. SupplierDocument: links to existing file_asset; document_type (Contract/NDA/Catalog/Certificate/License)
5. SupplierEvaluation: supplier_id, evaluated_by, date, delivery_score (0-10), quality_score (0-10),
   price_score (0-10), total_score (calculated average), notes
6. SupplierPerformance view (derived from PO history once procurement exists):
   - total_orders, on_time_delivery_rate, rejection_rate — start as nullable, populated later
7. Search: keyword ILIKE on supplier name, country, category names + semantic pgvector on description_embedding (see Section 2.1 search pattern — do NOT use tsvector)
8. Tag suppliers (use existing tag_management)
9. Attach documents via existing file_asset
10. RBAC: procurement_officer can create/edit; others view only

Please:
A) All models with complete fields, types, constraints, indexes
B) All API endpoints (include ?q= shortcut + ?status= filter on list)
C) search/ subfolder (repository.py ILIKE keyword + pgvector semantic + service.py hybrid — follow Section 2.1)
D) Alembic migration notes
E) Frontend specification: supplier list, supplier detail/profile, evaluation form, document tab
```

---

### PROMPT 2 — Material Master (Items Catalog) (Day 3)

```
PROJECT CONTEXT:
We are building a CMMS for the petroleum industry on top of an existing RAG/KMS system.
Backend: FastAPI + PostgreSQL (only) + SQLAlchemy + Alembic + Celery.
Architecture: each feature area is its own app folder. Apps communicate via REST API only.
Existing: document_management, tag_management, RBAC, user/company, file assets, AI chat.
Database: PostgreSQL + pgvector. Search: keyword (ILIKE) + semantic (pgvector, Jina embeddings) + hybrid.
Every module needs search/ subfolder matching financial_management/search/ pattern (repository/service/routes).
Search endpoint: POST /{module}/search with mode: keyword | semantic | hybrid.

ARCHITECTURAL GOAL — MODULAR MONOLITH → FUTURE MICROSERVICES:
This project is built as a modular monolith. Every module must be independently extractable into a
microservice in the future. ALL new code must follow these rules without exception:
1. NEVER import another module's SQLAlchemy model. Use that module's service functions instead.
2. NEVER call another module's route functions. Routes are HTTP handlers, not a service API.
3. Cross-module writes happen via Celery tasks (async event) — not synchronous service calls.
4. Shared types/enums live in backend/shared/ only — never in one module imported by another.
5. Each module has its own independent Alembic migrations — never mix two modules in one revision.
6. Models/__init__.py is for Alembic discovery only — no business code imports from it.
Already built: Currency + ExchangeRate, Supplier Management.
IMPORTANT: backend/buying_management/ already has partial item/cost/receipt models — review these first and extend rather than rewrite.

TODAY'S TASK: Complete the Material Master module (central item/material catalog)

REQUIREMENTS:
1. ItemCategory model: tree structure (parent_id self-referential), code, name, description
2. Unit model: code (KG, L, PCS, M, BOX, etc.), name, unit_type (Mass/Volume/Length/Count/Area)
3. Item model:
   - item_code (auto-generated or manual, unique per company)
   - name, description (both indexed for full-text search)
   - category_id, unit_id
   - specs: JSONB (flexible key-value per category, e.g. pump: {flow_rate: "100 m3/h"})
   - barcode, qr_code (optional, for scanning)
   - item_type: Material / Spare Part / Consumable / Tool / Chemical / PPE
   - is_active, is_critical (critical spare flag)
   - lead_time_days (typical procurement lead time)
   - model_id FK → model_management.managed_models.id (shared DB), NULLABLE — resolve via the model_management
     service, do not import its model (§0.5): set for equipment and model-specific spares, NULL for generic
     materials such as glue, grease, bolts. `Item` is the universal stock entity; `ManagedModel` is the
     equipment-model catalog it optionally references (Glossary §0), NOT a parallel stock store.
   - manufacturer / model_name for display/search come from the model — reach them by asking the
     model_management service for the model row (JOIN allowed in the shared DB). Do NOT add pre-emptive
     denormalized snapshot columns; denormalization happens only at extraction time (§0.5 recipe).
4. ItemAlternative: item_id (FK → items, same module), alt_code, alt_name, supplier_id FK →
   supplier_management.suppliers.id (shared DB — resolve via the supplier_management service, no model import;
   §0.5; vendor's code for this item)
5. Search: keyword ILIKE on item_code, name, description, specs + semantic pgvector on description_embedding (Section 2.1 pattern)
6. Attach documents to items (datasheets, safety data sheets) via file_asset
7. Tag items (critical spare, fast-moving, slow-moving, hazardous, etc.) via tag_management
8. RBAC: warehouse_manager + procurement_officer can create/edit; others view
9. Import from Excel (Celery task): accept uploaded Excel, parse rows, create items in bulk

Please:
A) All models (check buying_management/ first for what already exists)
B) All API endpoints with pagination + ?q= shortcut + ?category= + ?item_type= filters
C) search/ subfolder (ILIKE keyword + pgvector semantic — Section 2.1 pattern)
D) Excel import Celery task approach
E) Alembic migration notes
F) Frontend specification: item list (with filters), item detail, category tree, bulk import screen
```

---

### PROMPT 3 — Warehouse Locations & Stock (Day 9-10, after procurement is complete)

```
PROJECT CONTEXT:
We are building a CMMS for the petroleum industry on top of an existing RAG/KMS system.
Backend: FastAPI + PostgreSQL (only) + SQLAlchemy + Alembic + Celery.
Architecture: each feature area is its own app folder. Apps communicate via REST API only.
Existing: document_management, tag_management, RBAC, user/company, file assets, AI chat.
Database: PostgreSQL + pgvector. Search: keyword (ILIKE) + semantic (pgvector, Jina embeddings) + hybrid.
Every module needs search/ subfolder matching financial_management/search/ pattern (repository/service/routes).
Search endpoint: POST /{module}/search with mode: keyword | semantic | hybrid.

ARCHITECTURAL GOAL — MODULAR MONOLITH → FUTURE MICROSERVICES:
This project is built as a modular monolith. Every module must be independently extractable into a
microservice in the future. ALL new code must follow these rules without exception:
1. NEVER import another module's SQLAlchemy model. Use that module's service functions instead.
2. NEVER call another module's route functions. Routes are HTTP handlers, not a service API.
3. Cross-module writes happen via Celery tasks (async event) — not synchronous service calls.
4. Shared types/enums live in backend/shared/ only — never in one module imported by another.
5. Each module has its own independent Alembic migrations — never mix two modules in one revision.
6. Models/__init__.py is for Alembic discovery only — no business code imports from it.
IMPORTANT: backend/property_management/ has a partial warehouse model — review it first.
Already built: Currency, Supplier Management, Material Master, Procurement (MR→RFQ→PO→GRN).

TODAY'S TASK: Warehouse Management module
Built AFTER procurement so that GRN → StockMovement integration is immediately available.

REQUIREMENTS:
1. Warehouse model: code, name, type (Main/Secondary/Field/Transit), location/address, manager_id
2. Zone model: warehouse_id, code, name, description
3. StorageLocation model (shelf/bin): zone_id, code, name, capacity_unit, capacity_value, is_active
4. StockItem model (current state — one row per item per location):
   - item_id FK → material_management.items.id (shared DB) — resolve via the material_management service, do not
     import its model (§0.5); storage_location_id FK → warehouse.storage_locations (same module)
   - item_code / item_name for display/search come from the item — reach them by asking the material_management
     service (JOIN allowed in the shared DB). Stock anchors to `item_id`, NEVER directly to a model; equipment
     make/model is reached by asking material_management for the item, which carries the optional model
     (Glossary §0). Do NOT add pre-emptive denormalized snapshot columns; denormalize only at extraction time.
     MIGRATION: existing `property_management.WarehouseItem.model_id` (NOT NULL → managed_models) is migrated —
     create an `Item` per warehouse row carrying its model into `Item.model_id`, repoint stock to `item_id`
     (real FK → items), and drop the old direct stock→model link and the `relationship("ManagedModel")` so stock
     reaches the model only through the item. The `color`-based uniqueness key is dropped in favour of item +
     storage location (+ lot/batch where needed).
   - quantity_on_hand (Decimal — derived from movements but stored for performance)
   - quantity_reserved (reserved for work orders not yet consumed)
   - quantity_available (computed: on_hand - reserved)
   - min_level, max_level, reorder_point
   - unit_cost (Decimal), unit_cost_currency_id (latest weighted average cost)
   - unit_cost_base (in company base currency)
5. StockMovement model (append-only — never update or delete):
   - movement_number (auto: MOV-2026-00001)
   - movement_type: RECEIPT / ISSUE / TRANSFER_OUT / TRANSFER_IN / ADJUSTMENT / RETURN / COUNT_ADJUSTMENT
   - item_id FK → material_management.items.id (shared DB; resolve via material_management service — no model
     import), from_location_id (nullable), to_location_id (nullable) — both FK → warehouse.storage_locations
   - quantity (always positive)
   - unit_cost, currency_id, unit_cost_base, exchange_rate_used (multi-currency)
   - reference_type: GRN / WORK_ORDER / MANUAL / STOCK_COUNT
   - reference_id (ID of the GRN or Work Order that caused this)
   - performed_by (user), movement_date, notes
6. StockCount model (physical inventory sessions):
   - count_number (auto), warehouse_id, status: Open/In Progress/Posted, performed_by
7. StockCountLine: count_id (FK → stock_counts), item_id FK → material_management.items.id (shared DB — resolve
   via the material_management service, no model import; §0.5), location_id FK → warehouse.storage_locations.id,
   system_quantity, counted_quantity, variance
   - On post: auto-create COUNT_ADJUSTMENT StockMovements for variances
8. Business logic:
   - When GRN is posted in procurement: procurement emits a Celery event; this warehouse module handles it and
     creates the RECEIPT StockMovements (cross-module write = event, §0.5 — not a synchronous call from procurement)
   - Prevent ISSUE if quantity_available < requested (raise HTTP 422 with clear message)
   - After each movement: update StockItem.quantity_on_hand
   - Celery daily task: check all items where quantity_on_hand <= reorder_point → create notification
9. Full-text search on: item name, item code, location code, warehouse name
10. RBAC: storekeeper can RECEIPT/ISSUE; warehouse_manager can ADJUSTMENT; both can TRANSFER

Please provide:
A) All models with complete fields, types, constraints, indexes
B) All API endpoints including: stock by location, movements history, low-stock list
C) How a GRN-posted Celery event (emitted by procurement) is handled here to create the StockMovement RECEIPT
   (cross-module write = event, §0.5 — the warehouse handler reads accepted items via the procurement service)
D) Weighted average cost recalculation logic on each RECEIPT
E) Celery low-stock alert task
F) Alembic migration notes
G) Frontend specification: warehouse map/tree, item stock view, movement history, stock count screen
```

---

### PROMPT 4 — Procurement: MR + RFQ (Days 4-5)

```
PROJECT CONTEXT:
We are building a CMMS for the petroleum industry on top of an existing RAG/KMS system.
Backend: FastAPI + PostgreSQL (only) + SQLAlchemy + Alembic + Celery.
Architecture: each feature area is its own app folder. Apps communicate via REST API only.
Database: PostgreSQL + pgvector. Search: keyword (ILIKE) + semantic (pgvector, Jina embeddings) + hybrid.
Every module needs search/ subfolder matching financial_management/search/ pattern (repository/service/routes).
Search endpoint: POST /{module}/search with mode: keyword | semantic | hybrid.

ARCHITECTURAL GOAL — MODULAR MONOLITH → FUTURE MICROSERVICES:
This project is built as a modular monolith. Every module must be independently extractable into a
microservice in the future. ALL new code must follow these rules without exception:
1. NEVER import another module's SQLAlchemy model. Use that module's service functions instead.
2. NEVER call another module's route functions. Routes are HTTP handlers, not a service API.
3. Cross-module writes happen via Celery tasks (async event) — not synchronous service calls.
4. Shared types/enums live in backend/shared/ only — never in one module imported by another.
5. Each module has its own independent Alembic migrations — never mix two modules in one revision.
6. Models/__init__.py is for Alembic discovery only — no business code imports from it.
Already built: Currency + ExchangeRate, Supplier Management, Material Master.
IMPORTANT: backend/buying_management/ has partial purchase models — review and extend, do not rewrite.
Multi-currency: every amount field follows the 4-field pattern (amount, currency_id, amount_base, exchange_rate_used).

TODAY'S TASK: First half of Procurement — Material Requisition and RFQ

WORKFLOW (full):
MaterialRequisition (MR) → RequestForQuotation (RFQ) → QuotationResponse → PurchaseOrder → GoodsReceiptNote → StockMovement IN
This prompt covers: MR + RFQ + QuotationResponse.

REQUIREMENTS:
1. MaterialRequisition (MR):
   - mr_number (auto: MR-2026-0001)
   - requested_by (user), department_id
   - needed_by_date, reason, priority: Normal/Urgent/Critical
   - status: Draft / Submitted / Under Review / Approved / Rejected / Ordered / Closed
   - notes
2. MRItem: mr_id (FK → material_requisitions), item_id FK → material_management.items.id (shared DB — resolve
   via the material_management service, no model import; §0.5), quantity, unit_id, estimated_unit_cost
   (optional), currency_id, notes
3. MR Approval workflow (state machine):
   - Draft → Submitted (by requester)
   - Submitted → Approved or Rejected (by dept_head or procurement_officer)
   - Approved → Ordered (when PO is created from this MR)
4. RequestForQuotation (RFQ):
   - rfq_number (auto: RFQ-2026-0001)
   - mr_id (optional — RFQ can exist without MR for blanket quotes)
   - title, description, deadline_date, status: Draft / Sent / Closed / Cancelled
5. RFQSupplier: rfq_id × supplier_id (sent to multiple suppliers), sent_at, response_status
   (supplier_id FK → supplier_management.suppliers.id, shared DB — resolve via the supplier_management service,
   no model import; §0.5)
6. RFQItem: rfq_id, item_id FK → material_management.items.id (shared DB — resolve via the material_management
   service, no model import; §0.5), quantity, unit_id, specifications (text)
7. QuotationResponse: rfq_id, supplier_id FK → supplier_management.suppliers.id (shared DB — resolve via the
   supplier_management service, no model import; §0.5), received_at, valid_until, payment_terms, delivery_days, notes
8. QuotationResponseItem: response_id, rfq_item_id, unit_price, currency_id, lead_time_days, notes
   (also store: unit_price_base, exchange_rate_used)
9. RFQ comparison: endpoint that returns all supplier responses side-by-side for one RFQ
10. Full-text search on: MR number, reason, item names; RFQ number, title

Please provide:
A) All models with complete fields
B) All API endpoints (MR CRUD + state transitions + RFQ CRUD + quotation comparison)
C) State machine implementation approach for MR approval
D) How RFQ links back to MR (one MR can generate one RFQ)
E) Alembic migration notes
F) Frontend specification: MR form, MR approval inbox, RFQ form, supplier quotation comparison table
```

---

### PROMPT 5 — Procurement: PO + GRN (Days 6-7)

```
PROJECT CONTEXT:
We are building a CMMS for the petroleum industry on top of an existing RAG/KMS system.
Backend: FastAPI + PostgreSQL (only) + SQLAlchemy + Alembic + Celery.
Architecture: each feature area is its own app folder. Apps communicate via REST API only.
Database: PostgreSQL + pgvector (semantic search already in use via JinaAPIEmbeddings + Vector(1024) columns).

ARCHITECTURAL GOAL — MODULAR MONOLITH → FUTURE MICROSERVICES:
This project is built as a modular monolith. Every module must be independently extractable into a
microservice in the future. ALL new code must follow these rules without exception:
1. NEVER import another module's SQLAlchemy model. Use that module's service functions instead.
2. NEVER call another module's route functions. Routes are HTTP handlers, not a service API.
3. Cross-module writes happen via Celery tasks (async event) — not synchronous service calls.
4. Shared types/enums live in backend/shared/ only — never in one module imported by another.
5. Each module has its own independent Alembic migrations — never mix two modules in one revision.
6. Models/__init__.py is for Alembic discovery only — no business code imports from it.
Already built: Currency, Supplier, Material Master, MR, RFQ, QuotationResponse.
Multi-currency: every amount follows the 4-field pattern.
IMPORTANT: backend/buying_management/ has partial receipt/process models — review before writing.

TODAY'S TASK: Second half of Procurement — Purchase Order and Goods Receipt Note

WORKFLOW:
(MR → RFQ → QuotationResponse) → PurchaseOrder → GoodsReceiptNote → [triggers StockMovement IN]

REQUIREMENTS:
1. PurchaseOrder (PO):
   - po_number (auto: PO-2026-0001)
   - mr_id (optional, FK → requisition_management.material_requisitions), rfq_id (optional, FK → rfqs)
   - supplier_id FK → supplier_management.suppliers.id (shared DB) — resolve via the supplier_management
     service, no model import (§0.5)
   - order_date, expected_delivery_date
   - payment_terms (text), incoterms (EXW/FOB/CIF/DDP/etc.)
   - currency_id FK → currencies.id, exchange_rate_used, amount_base (computed sum)
   - status: Draft / Submitted / Approved / Sent to Supplier / Partially Received / Fully Received / Cancelled / Closed
   - shipping_address, notes
2. POItem: po_id (FK → purchase_orders), item_id FK → material_management.items.id (shared DB — resolve via the
   material_management service, no model import; §0.5), quantity, unit_id, unit_price, currency_id,
   unit_price_base, exchange_rate_used, discount_pct, tax_pct, line_total, line_total_base,
   received_quantity (updated as GRNs come in)
3. PO Approval workflow:
   - Draft → Submitted → Approved (by finance_manager) → [if total_base > threshold] GM approval → Sent
   - Approval threshold configurable per company (e.g., if PO base value > X → needs GM sign-off)
4. GoodsReceiptNote (GRN):
   - grn_number (auto: GRN-2026-0001)
   - po_id FK → purchase_orders.id (same module). NOTE: in Phase 0 the equivalent link is GRN/receipt →
     PurchasePhase (FK → purchase_phases.id, shared DB, resolve via purchase service); §0.5
   - received_by (user), receipt_date
   - delivery_note_number (supplier's delivery doc number)
   - status: Draft / Posted (posted = finalised, creates movements)
   - warehouse_id FK → warehouse.warehouses.id (shared DB — resolve via the warehouse service, no model import)
   - notes
5. GRNItem: grn_id (FK → goods_receipt_notes), po_item_id (FK → po_items), item_id FK → material_management.items.id
   (shared DB — resolve via the material_management service, no model import; §0.5), received_quantity,
   accepted_quantity, rejected_quantity, rejection_reason, storage_location_id FK → warehouse.storage_locations.id
   (shared DB — resolve via the warehouse service)
6. On GRN POST (status → Posted): emit a Celery event that the warehouse module handles by creating a
   StockMovement RECEIPT for each accepted GRNItem (cross-module write = event, §0.5 — not a synchronous reach
   into the warehouse module). Event payload carries the GRN id; the warehouse handler reads the accepted items
   via the procurement service and writes its own movements.
7. Partial delivery: one PO can have multiple GRNs. POItem.received_quantity updates on each GRN post.
   PO status auto-updates: Partially Received vs Fully Received.
8. Print PO as PDF: endpoint returns PDF-ready structured data (frontend renders or server generates)
9. Full-text search on: PO number, supplier name, item names

Please provide:
A) All models
B) All endpoints (PO CRUD + state transitions + GRN CRUD + post action)
C) PO approval threshold logic
D) The GRN-posted Celery event contract (event name + payload) and the warehouse-side handler that creates the
   RECEIPT movements — cross-module write goes through the event, not a synchronous warehouse call (§0.5)
E) How POItem.received_quantity and PO status stay in sync across multiple GRNs
F) Alembic migration notes
G) Frontend specification: PO form, PO approval screen, GRN entry screen, receiving dashboard
```

---

### PROMPT 6 — Asset Management

```
PROJECT CONTEXT:
We are building a CMMS for the petroleum industry on top of an existing RAG/KMS system.
Backend: FastAPI + PostgreSQL (only) + SQLAlchemy + Alembic + Celery.
Architecture: each feature area is its own app folder. Apps communicate via REST API only.
Database: PostgreSQL + pgvector. Search: keyword (ILIKE) + semantic (pgvector, Jina embeddings) + hybrid.
Every module needs search/ subfolder matching financial_management/search/ pattern (repository/service/routes).
Search endpoint: POST /{module}/search with mode: keyword | semantic | hybrid.

ARCHITECTURAL GOAL — MODULAR MONOLITH → FUTURE MICROSERVICES:
This project is built as a modular monolith. Every module must be independently extractable into a
microservice in the future. ALL new code must follow these rules without exception:
1. NEVER import another module's SQLAlchemy model. Use that module's service functions instead.
2. NEVER call another module's route functions. Routes are HTTP handlers, not a service API.
3. Cross-module writes happen via Celery tasks (async event) — not synchronous service calls.
4. Shared types/enums live in backend/shared/ only — never in one module imported by another.
5. Each module has its own independent Alembic migrations — never mix two modules in one revision.
6. Models/__init__.py is for Alembic discovery only — no business code imports from it.
Already built: Currency, Supplier, Material Master, Procurement (MR/RFQ/PO/GRN), Warehouse/Stock.

TODAY'S TASK: Asset Management module
Build the complete equipment registry for the petroleum facility.

REQUIREMENTS:
1. Plant model (top level: Refinery, Platform, Pipeline)
2. AssetSystem model (functional system: Process, Utility, Fire & Gas, Instrument)
   - belongs to Plant
3. Asset model (individual equipment):
   - tag_number (unique, e.g., P-1001 for pump, V-2003 for vessel)
   - name, description
   - asset_type: Rotating / Static / Electrical / Instrument / Civil / Piping
   - criticality: A (critical) / B (important) / C (general)
   - status: Active / Standby / Under Maintenance / Decommissioned
   - model_id FK → model_management.managed_models.id (shared DB), nullable — resolve via the model_management
     service, do not import its model (§0.5) — the equipment-model type (manufacturer + model live there,
     Glossary §0); prefer this over re-typing make/model as free text. manufacturer/model_number are reached by
     asking the model_management service for the model (JOIN allowed in the shared DB), with a free-text fallback
     only when no ManagedModel record exists yet. Do NOT add pre-emptive denormalized snapshot columns;
     denormalize only at extraction time (§0.5 recipe).
   - serial_number (identifies the individual physical unit; stays on the asset)
   - installation_date, warranty_expiry
   - parent_asset_id (for sub-components, tree structure)
   - belongs to AssetSystem
4. AssetSpecification (JSON key-value pairs per asset type, e.g., pump: flow_rate, head, power)
5. AssetSpare (links Asset to Items in Material Master — spare parts for this asset):
   - asset_id FK → asset_management.assets.id (same module)
   - item_id FK → material_management.items.id (shared DB) — resolve via the material_management service, do not
     import its model (§0.5)
6. AssetDocument (manuals, P&IDs, drawings — uses existing file_asset)
7. AssetHistory (lifecycle events: installed, modified, repaired, replaced — append-only log)
8. Search: keyword ILIKE on tag_number, name, description, manufacturer + semantic pgvector on description_embedding (Section 2.1 pattern)
9. RBAC: maintenance_engineer can create/edit, others view

Please provide:
A) All models with complete fields
B) All endpoints (including tree/hierarchy endpoint)
C) How AssetSpare links to Material Master
D) search/ subfolder for assets (ILIKE keyword + pgvector semantic — Section 2.1 pattern)
E) Frontend specification: asset tree view, asset detail page, asset history
```

---

### PROMPT 7 — Work Order Management

```
PROJECT CONTEXT:
We are building a CMMS for the petroleum industry on top of an existing RAG/KMS system.
Backend: FastAPI + PostgreSQL (only) + SQLAlchemy + Alembic + Celery.
Architecture: each feature area is its own app folder. Apps communicate via REST API only.
Database: PostgreSQL + pgvector. Search: keyword (ILIKE) + semantic (pgvector, Jina embeddings) + hybrid.
Every module needs search/ subfolder matching financial_management/search/ pattern (repository/service/routes).
Search endpoint: POST /{module}/search with mode: keyword | semantic | hybrid.

ARCHITECTURAL GOAL — MODULAR MONOLITH → FUTURE MICROSERVICES:
This project is built as a modular monolith. Every module must be independently extractable into a
microservice in the future. ALL new code must follow these rules without exception:
1. NEVER import another module's SQLAlchemy model. Use that module's service functions instead.
2. NEVER call another module's route functions. Routes are HTTP handlers, not a service API.
3. Cross-module writes happen via Celery tasks (async event) — not synchronous service calls.
4. Shared types/enums live in backend/shared/ only — never in one module imported by another.
5. Each module has its own independent Alembic migrations — never mix two modules in one revision.
6. Models/__init__.py is for Alembic discovery only — no business code imports from it.
Already built: Currency, Supplier, Material Master, Procurement, Warehouse/Stock, Asset Management.

TODAY'S TASK: Work Order Management module — the core of the CMMS

WORK ORDER TYPES:
- CM (Corrective): something broke, reactive
- PM (Preventive): scheduled, from maintenance plan
- Inspection: periodic inspection
- Modification: engineering change

LIFECYCLE: Draft → Submitted → Approved → Planned → In Progress → Completed → Closed
           (also: Rejected, On Hold from any step after Submitted)

REQUIREMENTS:
1. WorkOrder model:
   - wo_number (auto-generated: WO-2026-0001)
   - type: CM/PM/Inspection/Modification
   - priority: Critical/High/Medium/Low
   - asset_id FK → asset_management.assets.id (shared DB) — resolve via the asset_management service, do not
     import its model (§0.5)
   - title, description
   - requested_by (user), assigned_to (user or team)
   - scheduled_start, scheduled_end, actual_start, actual_end
   - status (state machine)
   - source: Manual / PM Schedule (if auto-generated)
   - parent_pm_schedule_id (if from PM)
2. WorkOrderTask (checklist steps on the work order)
3. WorkOrderLabor (who worked, date, hours, craft_type):
   - employee_id — **Employee is Phase 3**, so for now this is a NULLABLE plain field / free-text fallback
     (same pattern as `supplier_name` in Phase 0); upgrade it to a real FK → hr.employees in Phase 3 once the
     Employee module exists. (May still record the acting `user_id` as a real FK → platform.users.)
4. WorkOrderMaterial (items consumed from warehouse):
   - item_id FK → material_management.items.id (shared DB) — resolve via the material_management service, no
     model import (§0.5); planned_qty, actual_qty
   - On actual_qty save: emit a Celery event that creates the StockMovement OUT in warehouse (cross-module
     write = event, §0.5)
5. WorkOrderFailure (for CM only):
   - failure_code (ISO 14224 taxonomy: mechanical, electrical, instrument, etc.)
   - failure_cause, corrective_action, root_cause
6. WorkOrderAttachment (photos, inspection reports — uses file_asset)
7. Approval: draft → maintenance_supervisor approves → starts
8. Material reservation: before work starts, reserve items in warehouse
9. Auto-calculate: MTTR, downtime hours
10. Search: keyword ILIKE on wo_number, title, description, asset tag, failure codes + semantic pgvector on description_embedding (Section 2.1 pattern)
11. /work-orders/ask endpoint for manager agent (natural language query via existing AI chat system)

Please provide:
A) Complete models with all fields
B) All endpoints including state machine transition endpoints
C) How material consumption triggers StockMovement OUT (service function)
D) Failure coding taxonomy to implement (ISO 14224 for petroleum)
E) Frontend specification: WO list, WO detail, job card print view, KPI widgets
```

---

### PROMPT 8 — Maintenance Planning (PM Schedules)

```
PROJECT CONTEXT:
We are building a CMMS for the petroleum industry on top of an existing RAG/KMS system.
Backend: FastAPI + PostgreSQL (only) + SQLAlchemy + Alembic + Celery.
Architecture: each feature area is its own app folder. Apps communicate via REST API only.
Database: PostgreSQL + pgvector (semantic search already in use via JinaAPIEmbeddings + Vector(1024) columns).

ARCHITECTURAL GOAL — MODULAR MONOLITH → FUTURE MICROSERVICES:
This project is built as a modular monolith. Every module must be independently extractable into a
microservice in the future. ALL new code must follow these rules without exception:
1. NEVER import another module's SQLAlchemy model. Use that module's service functions instead.
2. NEVER call another module's route functions. Routes are HTTP handlers, not a service API.
3. Cross-module writes happen via Celery tasks (async event) — not synchronous service calls.
4. Shared types/enums live in backend/shared/ only — never in one module imported by another.
5. Each module has its own independent Alembic migrations — never mix two modules in one revision.
6. Models/__init__.py is for Alembic discovery only — no business code imports from it.
Already built: Currency, Supplier, Material Master, Procurement, Warehouse/Stock, Asset Management, Work Orders.

TODAY'S TASK: Preventive Maintenance Planning module

REQUIREMENTS:
1. MaintenancePlan model:
   - plan_number (auto: MP-2026-001)
   - name, description
   - asset_id FK → asset_management.assets.id (or asset_system_id FK → asset_management.asset_systems.id for
     grouped) — shared DB, resolve via the asset_management service, no model import (§0.5)
   - is_active
2. MaintenanceTask (task within a plan):
   - task_name, description
   - craft_type (Mechanical / Electrical / Instrument)
   - estimated_hours
   - required_items (list of item_id FK → material_management.items.id, shared DB — resolve via the
     material_management service, no model import; §0.5)
3. TaskTrigger (when to do it):
   - trigger_type: CALENDAR (every N days) or METER (every N hours/km/cycles)
   - frequency_value, frequency_unit
   - last_done_date, last_done_meter_reading
   - next_due_date (calculated)
4. PMSchedule (generated future instances):
   - plan_id, task_id, due_date, status: Pending/Generated/Overdue
   - When status=Pending and due_date approaches: emit a Celery event that the work_order module handles to
     create the WorkOrder (cross-module write = event, §0.5 — not a direct call into work_order)
5. InspectionChecklist (checklist template):
   - belongs to MaintenanceTask
   - checklist_items: step number, description, response_type: OK/NOT_OK / Numeric / Text
6. Celery Beat task: daily check of due PM schedules → auto-create WorkOrders
7. Full-text search on plan name + task description; filter by asset, due date range, status

Please provide:
A) All models
B) All endpoints
C) Celery Beat task implementation approach
D) How auto-generated WOs differ from manual WOs
E) Frontend specification: maintenance calendar, plan editor, checklist editor
```

---

### PROMPT 9 — Notification & Workflow Engine

```
PROJECT CONTEXT:
We are building a CMMS for the petroleum industry on top of an existing RAG/KMS system.
Backend: FastAPI + PostgreSQL (only) + SQLAlchemy + Alembic + Celery.
Architecture: each feature area is its own app folder. Apps communicate via REST API only.
Database: PostgreSQL + pgvector (semantic search already in use via JinaAPIEmbeddings + Vector(1024) columns).

ARCHITECTURAL GOAL — MODULAR MONOLITH → FUTURE MICROSERVICES:
This project is built as a modular monolith. Every module must be independently extractable into a
microservice in the future. ALL new code must follow these rules without exception:
1. NEVER import another module's SQLAlchemy model. Use that module's service functions instead.
2. NEVER call another module's route functions. Routes are HTTP handlers, not a service API.
3. Cross-module writes happen via Celery tasks (async event) — not synchronous service calls.
4. Shared types/enums live in backend/shared/ only — never in one module imported by another.
5. Each module has its own independent Alembic migrations — never mix two modules in one revision.
6. Models/__init__.py is for Alembic discovery only — no business code imports from it.
Already built: All Phase 1 (procurement + warehouse) and Phase 2 (assets + work orders + PM) modules.

TODAY'S TASK: Cross-cutting Notification & Workflow Engine

REQUIREMENTS:
1. NotificationTemplate model:
   - event_type (string: "work_order.approved", "stock.below_minimum", "pm.due_soon")
   - title_template, body_template (Jinja2)
   - channels: in_app / email / both
2. Notification model:
   - recipient_id (user)
   - title, body
   - entity_type, entity_id (what this is about)
   - is_read, read_at
   - created_at
3. ApprovalWorkflow model:
   - entity_type (PurchaseOrder, WorkOrder, LeaveRequest, etc.)
   - steps: ordered list of (approver_role, deadline_hours, escalate_to_role)
4. ApprovalInstance (active workflow for one entity):
   - entity_type, entity_id
   - current_step, status
5. ApprovalAction (log of approve/reject per step)
6. Event publishing: every module calls notify_service.publish(event_type, entity)
7. Celery task: process events → create Notification records → send emails

Please provide:
A) All models
B) Notification endpoints (list my notifications, mark read)
C) Event publishing pattern (how other modules call it)
D) Approval workflow state machine
E) Frontend specification: notification bell, notification list, approval inbox
```

---

### PROMPT 10 — Employee & HR Module

```
PROJECT CONTEXT:
We are building a CMMS for the petroleum industry on top of an existing RAG/KMS system.
Backend: FastAPI + PostgreSQL (only) + SQLAlchemy + Alembic + Celery.
Architecture: each feature area is its own app folder. Apps communicate via REST API only.
Database: PostgreSQL + pgvector. Search: keyword (ILIKE) + semantic (pgvector, Jina embeddings) + hybrid.
Every module needs search/ subfolder matching financial_management/search/ pattern (repository/service/routes).
Search endpoint: POST /{module}/search with mode: keyword | semantic | hybrid.

ARCHITECTURAL GOAL — MODULAR MONOLITH → FUTURE MICROSERVICES:
This project is built as a modular monolith. Every module must be independently extractable into a
microservice in the future. ALL new code must follow these rules without exception:
1. NEVER import another module's SQLAlchemy model. Use that module's service functions instead.
2. NEVER call another module's route functions. Routes are HTTP handlers, not a service API.
3. Cross-module writes happen via Celery tasks (async event) — not synchronous service calls.
4. Shared types/enums live in backend/shared/ only — never in one module imported by another.
5. Each module has its own independent Alembic migrations — never mix two modules in one revision.
6. Models/__init__.py is for Alembic discovery only — no business code imports from it.
Already built: All Phase 1 (procurement + warehouse) and Phase 2 (assets + work orders + PM + notifications).

TODAY'S TASK: Human Resources module

REQUIREMENTS:
1. Department model (name, code, parent_department_id for org tree, head_employee_id)
2. Position model (title, department, grade_level, is_management)
3. Employee model:
   - employee_number (auto: EMP-001)
   - first_name, last_name, national_id (hashed/encrypted)
   - date_of_birth, gender, nationality
   - hire_date, contract_type: Permanent/Contract/Secondment
   - department_id, position_id
   - reports_to (manager employee_id)
   - status: Active/On Leave/Terminated
   - user_id (optional link to system user account)
4. LeaveType (Annual, Sick, Emergency, Maternity, Study)
5. LeaveBalance (employee × leave_type × year → balance_days, used_days)
6. LeaveRequest (employee, type, from_date, to_date, reason, status, approved_by)
7. Training model (course name, provider, duration_hours, category)
8. Certification model (name, issuing_body, validity_period_months)
9. EmployeeTraining (employee × training × completion_date × score × certificate_file)
10. EmployeeCertification (employee × cert × issue_date × expiry_date × is_valid)
11. Celery: alert when certifications expire within 30 days
12. Full-text search on employee name, department, position, certifications
13. RBAC: hr_manager full access, department_head sees own department, employee sees own data

Please provide:
A) All models
B) All endpoints including org chart API
C) Certification expiry alert Celery task
D) Frontend specification: employee list, profile page, org chart, leave calendar, training matrix
```

---

### PROMPT 11 — Internal Communication (Letters & Messaging)

```
PROJECT CONTEXT:
We are building a CMMS for the petroleum industry on top of an existing RAG/KMS system.
Backend: FastAPI + PostgreSQL (only) + SQLAlchemy + Alembic + Celery.
Architecture: each feature area is its own app folder. Apps communicate via REST API only.
Database: PostgreSQL + pgvector. Search: keyword (ILIKE) + semantic (pgvector, Jina embeddings) + hybrid.
Every module needs search/ subfolder matching financial_management/search/ pattern (repository/service/routes).
Search endpoint: POST /{module}/search with mode: keyword | semantic | hybrid.

ARCHITECTURAL GOAL — MODULAR MONOLITH → FUTURE MICROSERVICES:
This project is built as a modular monolith. Every module must be independently extractable into a
microservice in the future. ALL new code must follow these rules without exception:
1. NEVER import another module's SQLAlchemy model. Use that module's service functions instead.
2. NEVER call another module's route functions. Routes are HTTP handlers, not a service API.
3. Cross-module writes happen via Celery tasks (async event) — not synchronous service calls.
4. Shared types/enums live in backend/shared/ only — never in one module imported by another.
5. Each module has its own independent Alembic migrations — never mix two modules in one revision.
6. Models/__init__.py is for Alembic discovery only — no business code imports from it.
Already built: All Phase 1, Phase 2, and Phase 3 (HR) modules.

TODAY'S TASK: Internal Communication module

REQUIREMENTS:
1. Letter model (formal internal correspondence):
   - letter_number (auto per year: MAINT-2026-001, HR-2026-045)
   - letter_type: Memo / Formal Letter / Circular / Report / Request
   - subject, body (rich text)
   - from_department, from_employee
   - to_department, to_employee (can be multiple)
   - cc list
   - priority: Normal / Urgent / Confidential
   - status: Draft / Sent / Acknowledged / Archived
   - sent_at, acknowledged_at
2. LetterAttachment (uses file_asset)
3. LetterComment (reply/note on a letter)
4. Announcement model:
   - title, body
   - target_audience: All / Specific Departments / Specific Roles
   - published_by, published_at, expires_at
   - is_pinned
5. InternalMessage (direct messaging, thread-based):
   - Thread model (participants list)
   - Message model (sender, thread, body, sent_at, is_read)
6. Search: keyword ILIKE on subject, body, sender name, letter_number + semantic pgvector on body_embedding (Section 2.1 pattern)
7. Search filters: by date range, sender, recipient, status, letter type
8. Number series: configurable prefix per letter_type

Please provide:
A) All models
B) All endpoints
C) Letter numbering logic
D) Search and AI indexing
E) Frontend specification: letter inbox, compose letter, announcement board, direct messages
```

---

### PROMPT 12 — HSE Module

```
PROJECT CONTEXT:
We are building a CMMS for the petroleum industry on top of an existing RAG/KMS system.
Backend: FastAPI + PostgreSQL (only) + SQLAlchemy + Alembic + Celery.
Architecture: each feature area is its own app folder. Apps communicate via REST API only.
Database: PostgreSQL + pgvector (semantic search already in use via JinaAPIEmbeddings + Vector(1024) columns).

ARCHITECTURAL GOAL — MODULAR MONOLITH → FUTURE MICROSERVICES:
This project is built as a modular monolith. Every module must be independently extractable into a
microservice in the future. ALL new code must follow these rules without exception:
1. NEVER import another module's SQLAlchemy model. Use that module's service functions instead.
2. NEVER call another module's route functions. Routes are HTTP handlers, not a service API.
3. Cross-module writes happen via Celery tasks (async event) — not synchronous service calls.
4. Shared types/enums live in backend/shared/ only — never in one module imported by another.
5. Each module has its own independent Alembic migrations — never mix two modules in one revision.
6. Models/__init__.py is for Alembic discovery only — no business code imports from it.
Already built: All previous modules (procurement, warehouse, assets, work orders, PM, notifications, HR, letters).

TODAY'S TASK: HSE (Health, Safety, Environment) module

REQUIREMENTS:
1. Incident model:
   - incident_number (auto: INC-2026-001)
   - incident_type: Near Miss / First Aid / Medical Treatment / Lost Time / Fatality / Environmental / Property Damage
   - severity: Low / Medium / High / Critical
   - location, occurred_at, reported_by, reported_at
   - description, immediate_action_taken
   - injured_employee_id (optional)
   - status: Reported / Under Investigation / Closed
2. IncidentInvestigation (root cause analysis):
   - immediate_cause, root_cause, contributing_factors
   - corrective_actions (list)
   - action_owner, action_due_date
3. PermitToWork (PTW):
   - permit_number (auto: PTW-2026-001)
   - permit_type: Hot Work / Confined Space / Electrical Isolation / Working at Height / Cold Work / Excavation
   - work_order_id (optional link: WO cannot start without valid PTW)
   - location, description_of_work
   - valid_from, valid_to
   - issuer (safety officer), receiver (technician supervisor)
   - status: Draft / Pending Approval / Active / Suspended / Closed / Cancelled
   - isolation_points (list of what was isolated)
   - JSA_attached (Job Safety Analysis document)
4. PTWChecklistItem (pre-work checks that must all be completed)
5. WorkAccessRequest (the "I want to fix this" request that follows a Phase 2 DefectReport):
   - defect_id (optional, from Phase 2), work_order_id (optional), tag_id, asset_id
   - requested_by, requested_at, scope_of_work, required_permit_types
   - status: Requested / Granted / Active / Closed / Rejected
6. WorkAccessApproval (DUAL approval — one row per required group):
   - access_request_id
   - approver_group: HSE | MANAGER
   - approver_user_id, decision: Approved | Rejected, decided_at, note
   - Rule: request becomes Granted only when BOTH groups (HSE and MANAGER) have Approved;
           a Rejected from EITHER group blocks it. Use the Approval Workflow Engine (4.2).
7. RiskAssessment:
   - hazard, likelihood (1-5), severity (1-5), risk_score (calculated)
   - control_measures, residual_risk_score
8. SafetyObservation (anyone can report):
   - type: Positive / Unsafe Act / Unsafe Condition
   - location, description, photo
   - reported_by
9. HSEStatistic (auto-calculated weekly/monthly):
   - man_hours_worked, LTI_count, TRIR, LTIR, near_miss_count
10. RBAC: hse_officer manages PTW and incidents; hse_team approves the HSE side of access
    requests (hse:permit_approve); manager_team approves the manager side
    (maintenance:access_approve); maintenance:access_request lets a technician raise one;
    anyone can submit observations. All permissions seeded in seed_rbac.py.
11. PTW + access gate on Work Orders: a WO cannot go to In Progress unless (a) a valid PTW exists
    AND (b) its WorkAccessRequest status = Granted (both HSE and Manager approved)
12. KPI + export: GET /kpi/hse (open permits, pending access requests by group, TRIR, LTIR,
    overdue corrective actions) and GET /reports/hse/... (chart-data shape 4.7); every register
    (incidents, permits, access requests) supports POST /{entity}/export to xlsx/csv/pdf (4.6)
13. Full-text search on: incident description, location, permit number, access-request scope

Please provide:
A) All models with complete fields
B) All endpoints (including access-request create + per-group approve/reject + status transitions)
C) PTW + dual-approval gate on Work Orders (how WO checks for valid PTW AND a Granted access request)
D) TRIR/LTIR calculation logic
E) Dual-approval state machine (HSE + Manager, both required, either can reject) on the Approval Engine
F) KPI/chart-data endpoints and the export endpoints (per 4.6 / 4.7)
G) Frontend specification: incident form, PTW issue screen, access-request + dual-approval inbox,
   safety observation wall, HSE dashboard (KPI cards + charts + Excel/PDF export)
```

---

### PROMPT 13 — AI Manager Agent

```
PROJECT CONTEXT:
We are building a CMMS for the petroleum industry on top of an existing RAG/KMS system.
Backend: FastAPI + PostgreSQL (only) + SQLAlchemy + Alembic + Celery.
Architecture: each feature area is its own app folder. Apps communicate via REST API only.
Database: PostgreSQL + pgvector (semantic search already in use via JinaAPIEmbeddings + Vector(1024) columns).

ARCHITECTURAL GOAL — MODULAR MONOLITH → FUTURE MICROSERVICES:
This project is built as a modular monolith. Every module must be independently extractable into a
microservice in the future. ALL new code must follow these rules without exception:
1. NEVER import another module's SQLAlchemy model. Use that module's service functions instead.
2. NEVER call another module's route functions. Routes are HTTP handlers, not a service API.
3. Cross-module writes happen via Celery tasks (async event) — not synchronous service calls.
4. Shared types/enums live in backend/shared/ only — never in one module imported by another.
5. Each module has its own independent Alembic migrations — never mix two modules in one revision.
6. Models/__init__.py is for Alembic discovery only — no business code imports from it.
ALL modules are implemented: procurement, warehouse, assets, work orders, PM, notifications, HR, letters, HSE.
The existing AI system already has: core/agents/ skeleton, core/semantic_ask.py, per-module /ask endpoints.

TODAY'S TASK: AI Manager Agent — cross-module natural language query system

ARCHITECTURE:
The existing system has: core/agents/ skeleton, core/semantic_ask.py, per-module /ask endpoints.
We now build a unified agent that routes questions to the right modules and synthesizes answers.

REQUIREMENTS:
1. AgentTool registry (each module registers what questions it can answer):
   - tool_name: "warehouse_inventory" / "work_orders" / "assets" / "procurement" / "employees" / etc.
   - description (used by LLM to decide which tool to call)
   - endpoint_path (the module's /ask endpoint)
2. AgentSession model (conversation history for manager):
   - session_id, user_id, messages (JSON array), created_at
3. Agent orchestration (POST /agent/ask):
   - Input: user question + session_id (for context)
   - Step 1: LLM determines which tools to call (function calling)
   - Step 2: Call each relevant module's /ask endpoint
   - Step 3: Synthesize results + cite sources (module + entity IDs)
   - Step 4: Return answer + source list + session updated
4. Manager Dashboard aggregation endpoint (GET /agent/dashboard):
   - Calls all modules for their "current status" summary
   - Returns: open WO count, stock alerts count, pending POs, incidents this month, employees on leave
5. Report generation: agent can format answer as structured report
6. RBAC: only managers and above can use the agent
7. Audit: every agent query is logged (who asked what, what was returned)

Please provide:
A) Agent architecture (how tools are registered and called)
B) All models
C) All endpoints
D) LLM prompt template for tool selection
E) How each module's /ask endpoint should be structured for agent compatibility
F) Frontend specification: manager chat interface, dashboard overview, report generation
```

---

### PROMPT 14 — Defect / Fault Reporting (Phase 2)

```
PROJECT CONTEXT:
We are building a CMMS for the petroleum industry on top of an existing RAG/KMS system.
Backend: FastAPI + PostgreSQL (only) + SQLAlchemy + Alembic + Celery.
Database: PostgreSQL + pgvector (JinaAPIEmbeddings + Vector(1024) columns). Search per Section 2.1.

ARCHITECTURAL GOAL — MODULAR MONOLITH → FUTURE MICROSERVICES (rules 1–6 as in every prompt):
NEVER import another module's model; use its service functions. Cross-module writes via Celery.
Shared types in backend/shared/ only. Independent Alembic migrations. Models/__init__.py = discovery only.
Already built: Asset Management, Work Orders, PM, tag_management (existing). 

TODAY'S TASK: Defect / Fault Reporting — the entry point of the maintenance loop.
"A tag has a problem, and a specific asset under it (e.g. the pump) has failed."
NOTE: "tag" = a tag_management tag (the central user-facing object), optionally linked to an Asset.

REQUIREMENTS:
1. DefectReport model:
   - defect_number (auto: DEF-2026-0001)
   - tag_id FK → tag_management tag (shared DB) — resolve via that module's SERVICE, no model import (§0.5)
   - asset_id (optional) FK → asset_management.assets (shared DB) — the failed equipment under the tag; resolve
     via the asset_management service, no model import
   - severity: Low/Medium/High/Critical
   - status: Open/Acknowledged/In Progress/Resolved/Closed/Rejected
   - description, description_embedding (Vector 1024)
   - reported_by, reported_at
   - work_order_id (optional) FK → work_order (shared DB) — resolve via the work_order service, no model import
   - photos (FileAsset)
2. DefectComment (notes + status changes, audit-logged)
3. Criticality of a tag is admin-defined tag metadata (Section 12.10 JSONB) — read it via the
   tag_management service to compute "critical tags with an open fault".
4. Raising a Work Order from a defect links them; closing the WO auto-resolves the defect
   via a Celery event (no direct cross-module write).
5. The fault does NOT start work — actual work is gated by the HSE permit/access workflow (Phase 4.2).
6. Search (Section 2.1): keyword ILIKE on defect_number, description, tag name, asset tag + semantic.
7. Export (shared Export Engine 4.6): POST /defects/export → xlsx/csv/pdf.
8. /defects/ask endpoint for the manager agent.

Please provide:
A) All models with fields
B) All endpoints (CRUD, status transitions, comments, search, export)
C) How tag criticality is read from tag_management (service contract) for the KPI
D) Defect → Work Order linkage and the auto-resolve Celery event
E) Permissions to seed: defect:read, defect:write, defect:resolve, defect:export
F) Frontend spec: report-a-fault form, defect register (filter by tag/status/severity), defect detail
```

---

### PROMPT 15 — Export Engine + Dashboard/Chart-Data Framework (shared, build once)

```
PROJECT CONTEXT:
We are building a CMMS for the petroleum industry on top of an existing RAG/KMS system.
Backend: FastAPI + PostgreSQL (only) + SQLAlchemy + Alembic + Celery.
This is a SHARED foundation used by every module (see master plan 4.6 Export Engine, 4.7 Dashboard
& Chart-Data Convention, and the "KPI & Reporting Phases" section).

ARCHITECTURAL GOAL — MODULAR MONOLITH (rules 1–6 as in every prompt). This lives in backend/shared/.

TODAY'S TASK: Build the reusable Export Engine and the dashboard/chart-data conventions so every
module gets Excel/CSV/PDF export and standard KPI + chart endpoints for free.

REQUIREMENTS:
1. backend/shared/export/ — one service, three formats:
   - xlsx (openpyxl: header styling, frozen header row, column widths, number/currency formatting)
   - csv (UTF-8 with BOM)
   - pdf (server-side HTML→PDF: title block, company logo, applied filters, table or KPI sheet)
2. Standard export endpoint pattern that any module mounts next to its list/search:
   POST /{module}/{entity}/export  body { format, filters, columns }  → 202 + { task_id }
   Runs in Celery (Rule 5). Reuse the Phase 0.1 GET /tasks/{task_id} poller; result stored as FileAsset
   with a short-lived download_url. Small exports (<~1k rows) may return inline.
   filters/columns reuse the module's existing search request schema (Section 2.1) — export = search + serialize.
3. Dashboard/chart-data convention (4.7):
   - GET /kpi/{module} → [{ key, label, value, unit, trend }]  (5–8 KPI cards)
   - GET /reports/{module}/{name} → { chart_type, x:[...], series:[{name,data:[...]}], unit }
   - chart_type recommended by backend: line | bar | stacked_bar | pie | donut | gauge | table
   - standard params on report endpoints: ?from=&to=&group_by=day|week|month&currency_id=
   - short-TTL caching per (company, params), invalidated on the module's events.
4. RBAC: export requires {module}:read; seed a separate {module}:export permission so bulk export
   can be withheld. Every export is audit-logged (who exported what, filters, format).
5. Assistant integration: expose export as a module tool (12.4) usable via draft-and-confirm (12.5),
   e.g. "export this month's open work orders to Excel".

Please provide:
A) shared/export/ design (service interface, format adapters, FileAsset storage, Celery task)
B) The reusable endpoint mixin/helper modules add to get export + kpi + reports with minimal code
C) The chart-data response schema (Pydantic) and one worked example per chart_type
D) Caching + invalidation approach
E) Permission seeding pattern for {module}:export across all modules
F) Frontend spec: reusable KPI-card, chart, filter-bar, and Export(xlsx/csv/pdf) components
```


### PROMPT 16 — Employee Management (Phase 3)

```
PROJECT CONTEXT:
We are building a CMMS for the petroleum industry on top of an existing RAG/KMS system.
Backend: FastAPI + PostgreSQL + pgvector + SQLAlchemy + Alembic + Celery.
Architecture: a modular monolith targeting future microservice extraction.
Database: PostgreSQL + pgvector. Search: keyword (ILIKE) + semantic (pgvector, Jina embeddings) + hybrid.
Every module needs a search/ subfolder matching the financial_management/search/ pattern (repository/service/routes).
Search endpoint: POST /{module}/search with mode: keyword | semantic | hybrid (Section 2.1).

ARCHITECTURAL GOAL — MODULAR MONOLITH → FUTURE MICROSERVICES:
This project is built as a modular monolith. Every module must be independently extractable into a
microservice in the future. ALL new code must follow these rules without exception:
1. NEVER import another module's SQLAlchemy model. Use that module's service functions instead.
2. NEVER call another module's route functions. Routes are HTTP handlers, not a service API.
3. Cross-module writes happen via Celery tasks (async event) — not synchronous service calls.
4. Shared types/enums live in backend/shared/ only — never in one module imported by another.
5. Each module has its own independent Alembic migrations — never mix two modules in one revision.
6. Models/__init__.py is for Alembic discovery only — no business code imports from it.
Already built: All Phase 1 (procurement + warehouse) and Phase 2 (assets + work orders + PM +
defect reporting + notifications) modules. The Assistant Core (backend/assistant/, Phase 0-AI) exists;
this module registers a tool set into it (Section 12.4).

TODAY'S TASK: hr_management — Part 1: Employee master data, department/position hierarchy, org chart.

REQUIREMENTS:
1. Department model:
   - code (auto: DEP-001, unique per company), name, description
   - parent_department_id (self-referential, nullable — org tree)
   - head_employee_id (nullable FK to Employee — resolved after employees exist)
   - is_active, company_id
2. Position model:
   - code (unique per company), title, description
   - department_id (FK Department)
   - grade_level (int), is_management (bool)
   - job_description (text — embedded for semantic search)
3. Employee model:
   - employee_number (auto: EMP-001, unique per company)
   - first_name, last_name, full_name (computed/stored)
   - national_id (store encrypted/hashed — never log it; see Section 4.5 "no PII in logs")
   - date_of_birth, gender, nationality
   - hire_date, contract_type: Permanent / Contract / Secondment
   - department_id (FK), position_id (FK)
   - reports_to_employee_id (self-referential, nullable — manager link, drives org chart)
   - status: Active / On Leave / Terminated
   - user_id (nullable FK to existing User — links the employee to a system login if they have one)
   - email, phone, company_id
   - description_embedding: Vector(1024), nullable  (embeds job_description + position + department)
4. EmployeeDocument model:
   - employee_id, file_asset_id (existing file_asset), document_type:
     Contract / NationalID / Qualification / Certificate / Other, issued_date, notes
5. EmployeeHistory model (append-only lifecycle log):
   - employee_id, event_type: Hired / Promoted / Transferred / ContractChanged / Terminated
   - from_value (JSONB), to_value (JSONB), effective_date, performed_by, notes
6. Org chart: a service + endpoint that derives the tree from Employee.reports_to_employee_id
   and Department.parent_department_id (no separate OrgChart table — it is a projection).
7. Tag employees via existing tag_management; attach documents via existing file_asset.
8. Search (Section 2.1): keyword ILIKE on full_name, employee_number, position title, department name
   + semantic pgvector on description_embedding. ensure_employee_embeddings() + build_searchable_text().
9. Assistant Tool Contract (Section 12.4): register hr_management ToolSet (search / summarize / ask /
   add_draft) so the agent can answer "who is the maintenance manager?" and draft a new employee via
   draft-and-confirm (the frontend commits to the hr create endpoint; the assistant never writes) — RBAC
   enforced by that endpoint as the caller (Section 12.11).
10. RBAC (seed in seed_rbac.py): hr_management:employees:read / create / update / delete / search;
    hr_management:summary. hr_manager gets hr_management:*; department_head sees own department
    (record-level scope deferred per Section 6 — seed names now); employee can read own profile.

IMPACT:
- What changes: adds hr_management module; registers an Assistant tool set.
- Backward compatible: yes (purely additive; new nullable FK on no existing table except optional User link via user_id on the new Employee table).
- New tables: departments, positions, employees, employee_documents, employee_history.
- Existing routes affected: none.

Please provide:
A) All models with complete fields, types, constraints, indexes (incl. embedding column)
B) All API endpoints (employee/department/position CRUD + org-chart endpoint; ?q= shortcut +
   ?department=&status=&position= filters on the employee list)
C) search/ subfolder (repository.py ILIKE keyword + pgvector semantic + service.py hybrid — Section 2.1)
D) Alembic migration notes (encrypted national_id column, embedding column, self-referential FKs,
   deferred head_employee_id FK)
E) RBAC permission seeds (which roles get which permissions)
F) Frontend specification: employee list (filters), employee profile page, org chart view,
   document tab, history timeline
G) What you could add next (e.g. shift/roster management, payroll integration, skills matrix)
```

---

### PROMPT 17 — Leave & Training Management (Phase 3)

```
PROJECT CONTEXT:
We are building a CMMS for the petroleum industry on top of an existing RAG/KMS system.
Backend: FastAPI + PostgreSQL + pgvector + SQLAlchemy + Alembic + Celery.
Architecture: a modular monolith targeting future microservice extraction.
Database: PostgreSQL + pgvector. Search: keyword (ILIKE) + semantic (pgvector, Jina embeddings) + hybrid.
Every module needs a search/ subfolder matching the financial_management/search/ pattern (Section 2.1).

ARCHITECTURAL GOAL — MODULAR MONOLITH → FUTURE MICROSERVICES:
This project is built as a modular monolith. Every module must be independently extractable into a
microservice in the future. ALL new code must follow these rules without exception:
1. NEVER import another module's SQLAlchemy model. Use that module's service functions instead.
2. NEVER call another module's route functions. Routes are HTTP handlers, not a service API.
3. Cross-module writes happen via Celery tasks (async event) — not synchronous service calls.
4. Shared types/enums live in backend/shared/ only — never in one module imported by another.
5. Each module has its own independent Alembic migrations — never mix two modules in one revision.
6. Models/__init__.py is for Alembic discovery only — no business code imports from it.
Already built: Prompt 16 (hr_management employees/departments/positions/org chart), the Notification &
Workflow Engine (Approval Workflow Engine §4.2 — reuse it for leave approval), the Assistant Core.
This prompt EXTENDS hr_management — same module folder, new sub-resources (leave, training). It must
not duplicate or rewrite the employee models from Prompt 16; it references them via hr_management's own
internal services (same module — direct use is allowed within a module).

TODAY'S TASK: hr_management — Part 2: Leave Management + Training & Certification, with expiry alerting.

REQUIREMENTS:
1. LeaveType model: code, name (Annual / Sick / Emergency / Maternity / Study / Unpaid),
   is_paid, default_annual_days, requires_attachment (bool), company_id, is_active
2. LeaveBalance model (employee × leave_type × year):
   - employee_id, leave_type_id, year, entitled_days, used_days, pending_days
   - available_days (computed: entitled - used - pending)
3. LeaveRequest model:
   - request_number (auto: LV-2026-0001)
   - employee_id, leave_type_id, from_date, to_date, total_days (computed, excludes weekends/holidays)
   - reason, attachment_file_asset_id (optional), status: Draft / Submitted / Approved / Rejected / Cancelled
   - submitted_at, decided_at
4. LeaveApproval model (uses Approval Workflow Engine §4.2):
   - leave_request_id, approver_user_id, decision: Approved / Rejected, decided_at, note
   - On Approved: move pending_days → used_days in LeaveBalance (within hr_management service).
5. TrainingProgram model:
   - code, name, provider, category (e.g. Safety / Technical / Compliance), duration_hours,
     description (embedded for semantic search), is_active, company_id
6. Certification model (the credential definition):
   - code, name (e.g. H2S, BOSIET, Confined Space), issuing_body, validity_period_months, is_active
7. EmployeeTraining model (employee × training × completion):
   - employee_id, training_program_id, completed_date, score, result: Pass / Fail,
     certificate_file_asset_id (optional)
8. EmployeeCertification model (employee × cert × dates):
   - employee_id, certification_id, issue_date, expiry_date (computed from validity_period_months),
     certificate_file_asset_id, is_valid (computed: today <= expiry_date)
9. TrainingPlan model (annual plan per department): department_id, year, planned_programs (list),
   notes — drives the "training compliance" KPI in Prompt 20.
10. Celery (Rule 10): daily Beat task scan EmployeeCertification where expiry_date within 30 days →
    publish notification event to employee + their manager (via the Notification Engine, Prompt 21).
    Also flag already-expired certs. Cross-module notify is a Celery event, not a direct call.
11. Search (Section 2.1): keyword ILIKE on training/cert name, employee name; semantic on
    TrainingProgram.description_embedding. Reuse hr_management's search/ folder (add entity functions).
12. Assistant Tool Contract (Section 12.4): extend the hr_management ToolSet so the agent can answer
    "which employees have an expired H2S certification?" and draft a leave request (draft-and-confirm).
13. RBAC (seed in seed_rbac.py): hr_management:leave:read / create / approve;
    hr_management:training:read / manage. Employees create own leave + read own training; hr_manager
    has hr_management:* ; a manager approves their team's leave (record-level scope deferred per §6).

IMPACT:
- What changes: extends hr_management with leave + training sub-resources; adds a daily expiry-alert task.
- Backward compatible: yes (additive; references Prompt 16 employees within the same module).
- New tables: leave_types, leave_balances, leave_requests, leave_approvals, training_programs,
  certifications, employee_trainings, employee_certifications, training_plans.
- Existing routes affected: none.

Please provide:
A) All models with complete fields, types, constraints, indexes
B) All API endpoints (leave CRUD + submit/approve/reject transitions, balance view, training/cert CRUD,
   employee training matrix, expiring-certs list; filters: ?employee=&status=&from=&to=&expiring_in_days=)
C) search/ subfolder additions (keyword + pgvector semantic + hybrid — Section 2.1)
D) Alembic migration notes (computed columns / triggers vs application-side computation, embedding column)
E) RBAC permission seeds (which roles get which permissions)
F) Frontend specification: leave request form, leave balance widget, team leave calendar, approval inbox,
   training matrix, certification expiry dashboard
G) What you could add next (e.g. competency/skills gap analysis, e-signature on certificates,
   auto-block work assignment when a required cert is expired — ties into HSE Prompt 19)
```

---

### PROMPT 18 — Internal Communication (Phase 3)

```
PROJECT CONTEXT:
We are building a CMMS for the petroleum industry on top of an existing RAG/KMS system.
Backend: FastAPI + PostgreSQL + pgvector + SQLAlchemy + Alembic + Celery.
Architecture: a modular monolith targeting future microservice extraction.
Database: PostgreSQL + pgvector. Search: keyword (ILIKE) + semantic (pgvector, Jina embeddings) + hybrid.
Every module needs a search/ subfolder matching the financial_management/search/ pattern (Section 2.1).

ARCHITECTURAL GOAL — MODULAR MONOLITH → FUTURE MICROSERVICES:
This project is built as a modular monolith. Every module must be independently extractable into a
microservice in the future. ALL new code must follow these rules without exception:
1. NEVER import another module's SQLAlchemy model. Use that module's service functions instead.
2. NEVER call another module's route functions. Routes are HTTP handlers, not a service API.
3. Cross-module writes happen via Celery tasks (async event) — not synchronous service calls.
4. Shared types/enums live in backend/shared/ only — never in one module imported by another.
5. Each module has its own independent Alembic migrations — never mix two modules in one revision.
6. Models/__init__.py is for Alembic discovery only — no business code imports from it.
Already built: All Phase 1 + Phase 2 modules, hr_management (Prompts 16–17), the Notification Engine
(Prompt 21 — publish events to it), tag_management (existing), the Assistant Core.

TODAY'S TASK: communication_management — formal internal letters, announcements, and threaded messaging.

REQUIREMENTS:
1. LetterTemplate model:
   - code, name, letter_type: Memo / FormalLetter / Circular / Report / Request
   - subject_template, body_template (Jinja2-style placeholders), company_id, is_active
2. Letter model:
   - letter_number (auto, configurable prefix per letter_type and year, e.g. MAINT-2026-001, HR-2026-045)
   - letter_type, subject, body (rich text), template_id (nullable)
   - from_department_id, from_employee_id (resolved via hr_management service — no model import)
   - priority: Normal / Urgent / Confidential
   - status: Draft / Sent / Acknowledged / Archived
   - sent_at, acknowledged_at, company_id
   - body_embedding: Vector(1024), nullable
   - tag_ids: letters may reference tag_management tags (read via the tag_management service) so a letter
     "regarding maintenance of pump P-1001" links to that tag.
3. LetterRecipient model: letter_id, recipient_type: TO / CC,
   to_department_id (nullable), to_employee_id (nullable), acknowledged_at (per recipient)
4. LetterVersion model (append-only edit history of a draft): letter_id, version_no, subject, body,
   edited_by, edited_at — so a sent letter's content is immutable and prior drafts are auditable.
5. LetterAttachment model: letter_id, file_asset_id (existing file_asset), caption
6. LetterComment model: letter_id, author_user_id, body, created_at (reply/note on a letter; audit-logged)
7. Announcement model:
   - title, body, target_audience: All / Departments / Roles
   - target_department_ids (JSONB), target_role_ids (JSONB)
   - published_by, published_at, expires_at, is_pinned, company_id
8. MessageThread model: subject, participant_user_ids (JSONB), created_by, created_at
   MessageThreadMessage model: thread_id, sender_user_id, body, sent_at, read_by_user_ids (JSONB)
9. Letter numbering logic: a per-(company, letter_type, year) counter, allocated atomically on Send
   (Draft has no number until sent). Prefix configurable per letter_type.
10. Workflow: Draft → Sent (allocates number, snapshots a LetterVersion, publishes a Celery event to the
    Notification Engine so recipients are notified) → Acknowledged (per recipient) → Archived.
11. Search (Section 2.1): keyword ILIKE on letter_number, subject, body, sender name; semantic pgvector on
    body_embedding. Filters: ?from=&to=&sender=&recipient=&status=&letter_type=. ensure_letter_embeddings().
12. Assistant Tool Contract (Section 12.4): register communication_management ToolSet so the agent can
    "find all letters about pump P-1001 in the last 6 months" and draft a memo via draft-and-confirm.
13. RBAC (seed in seed_rbac.py): communication_management:letters:read / create / update / delete /
    search / ask; communication_management:announcements:read / manage. A communication_officer/creator
    role gets create+manage; all authenticated users get read on letters addressed to them + announcements.
    Confidential letters are restricted to sender + recipients (record-level scope deferred per §6).

IMPACT:
- What changes: adds communication_management module; publishes "letter.sent" events; registers a tool set.
- Backward compatible: yes (purely additive).
- New tables: letter_templates, letters, letter_recipients, letter_versions, letter_attachments,
  letter_comments, announcements, message_threads, message_thread_messages.
- Existing routes affected: none.

Please provide:
A) All models with complete fields, types, constraints, indexes (incl. body_embedding)
B) All API endpoints (letter CRUD + send/acknowledge/archive transitions, recipient ack, comments,
   announcement CRUD, thread + message endpoints; ?q= shortcut + the filters above)
C) search/ subfolder (repository.py ILIKE keyword + pgvector semantic + service.py hybrid — Section 2.1)
D) Alembic migration notes (per-type/year number-counter table, embedding column, JSONB targets)
E) RBAC permission seeds (which roles get which permissions)
F) Frontend specification: letter inbox, compose-letter (template picker + tag link), letter detail with
   ack + comments, announcement board, direct-message threads
G) What you could add next (e.g. read receipts analytics, letter approval routing before Send,
   org-wide broadcast scheduling, AI letter drafting from a tag/work-order context — ties into §12.14)
```

---

### PROMPT 19 — HSE Management (Phase 3)

```
PROJECT CONTEXT:
We are building a CMMS for the petroleum industry on top of an existing RAG/KMS system.
Backend: FastAPI + PostgreSQL + pgvector + SQLAlchemy + Alembic + Celery.
Architecture: a modular monolith targeting future microservice extraction.
Database: PostgreSQL + pgvector. Search: keyword (ILIKE) + semantic (pgvector, Jina embeddings) + hybrid.
Every module needs a search/ subfolder matching the financial_management/search/ pattern (Section 2.1).

ARCHITECTURAL GOAL — MODULAR MONOLITH → FUTURE MICROSERVICES:
This project is built as a modular monolith. Every module must be independently extractable into a
microservice in the future. ALL new code must follow these rules without exception:
1. NEVER import another module's SQLAlchemy model. Use that module's service functions instead.
2. NEVER call another module's route functions. Routes are HTTP handlers, not a service API.
3. Cross-module writes happen via Celery tasks (async event) — not synchronous service calls.
4. Shared types/enums live in backend/shared/ only — never in one module imported by another.
5. Each module has its own independent Alembic migrations — never mix two modules in one revision.
6. Models/__init__.py is for Alembic discovery only — no business code imports from it.
Already built: All Phase 1 + Phase 2 modules — including work_order_management (Prompt 7) and the Phase 2
DefectReport (Prompt 14, "tag X has a problem; the pump under it failed") — plus the Approval Workflow
Engine (§4.2), the Notification Engine (Prompt 21), the Export Engine (Prompt 15), and the Assistant Core.

TODAY'S TASK: hse_management — incidents + investigations, Permit to Work, the dual-approval Work Access
Request that gates maintenance work, risk assessments, safety observations, and HSE statistics.

This is the back half of the maintenance loop that starts at a DefectReport (Prompt 14): a fault is open
on a tag; someone wants to fix the failed asset; they must be granted access by BOTH the HSE team and the
Manager team, and a valid Permit to Work must exist, before a Work Order can go In Progress.

REQUIREMENTS:
1. HSEIncident model:
   - incident_number (auto: INC-2026-001)
   - incident_type: NearMiss / FirstAid / MedicalTreatment / LostTime / Fatality / Environmental / PropertyDamage
   - severity: Low / Medium / High / Critical
   - location, occurred_at, reported_by, reported_at
   - description (embedded for semantic search), immediate_action_taken
   - injured_employee_id (nullable — via hr_management service, no model import)
   - status: Reported / UnderInvestigation / Closed, company_id, description_embedding: Vector(1024)
2. IncidentInvestigation model (root cause analysis):
   - incident_id, immediate_cause, root_cause, contributing_factors (JSONB)
   - corrective_actions (JSONB list: action, owner_user_id, due_date, status), closed_at
3. PermitToWork model:
   - permit_number (auto: PTW-2026-001)
   - permit_type: HotWork / ConfinedSpace / ElectricalIsolation / WorkingAtHeight / ColdWork / Excavation
   - work_order_id (nullable — link via work_order_management service)
   - location, description_of_work, valid_from, valid_to
   - issuer_user_id (safety officer), receiver_user_id (supervisor)
   - status: Draft / PendingApproval / Active / Suspended / Closed / Cancelled
   - isolation_points (JSONB list), jsa_file_asset_id (Job Safety Analysis document)
4. PTWChecklistItem model: permit_id, sequence, description, is_completed, completed_by, completed_at
   (all required items must be completed before a permit goes Active).
5. WorkAccessRequest model (the "I want to fix this" request following a DefectReport):
   - request_number (auto: WAR-2026-001)
   - defect_id (nullable — link via defect module service), work_order_id (nullable), tag_id, asset_id
   - requested_by, requested_at, scope_of_work, required_permit_types (JSONB)
   - status: Requested / Granted / Active / Closed / Rejected
6. WorkAccessApproval model (DUAL approval — one row per required group):
   - access_request_id, approver_group: HSE | MANAGER
   - approver_user_id, decision: Approved | Rejected, decided_at, note
   - Rule: request becomes Granted only when BOTH groups have Approved; a Rejected from EITHER group
     blocks it. Implemented on the Approval Workflow Engine (§4.2) as two parallel approver groups.
7. RiskAssessment model:
   - hazard, likelihood (1-5), severity (1-5), risk_score (computed = likelihood × severity)
   - control_measures, residual_risk_score, notes (embedded for semantic search), assessed_by
8. SafetyObservation model (anyone can report):
   - observation_type: Positive / UnsafeAct / UnsafeCondition
   - location, description, photo_file_asset_id, reported_by, reported_at
9. HSEStatistic model (auto-calculated weekly/monthly):
   - period_start, period_end, man_hours_worked, lti_count, recordable_count, near_miss_count,
     trir (computed), ltir (computed)
10. Work Order gate (cross-module, NO model import): work_order_management calls an hse_management
    service function can_start_work(work_order_id) → bool/reason. A WO cannot transition to In Progress
    unless (a) a valid (Active) PermitToWork exists AND (b) its WorkAccessRequest status = Granted.
    The dependency direction: work_order_management calls hse_management's service (one-way), keeping
    HSE the owner of the gate decision. Defect auto-resolve and WO-close side-effects stay Celery events.
11. Notifications (Prompt 21, via Celery events): request raised → notify HSE + Manager queues;
    each decision → notify requester; granted → notify maintenance; permit expiring → notify issuer.
12. Search (Section 2.1): keyword ILIKE on incident_number/description/location, permit_number,
    access-request scope; semantic pgvector on incident description_embedding + risk-assessment notes.
13. KPI + export (reuse Prompt 15 — do NOT re-implement): GET /kpi/hse and GET /reports/hse/... per the
    §4.7 chart-data shape; every register (incidents, permits, access requests) supports
    POST /{entity}/export to xlsx/csv/pdf via the shared Export Engine (§4.6).
14. Assistant Tool Contract (Section 12.4): register hse_management ToolSet so the agent can answer
    "show all open hot work permits" / "what is our TRIR for Q1?" and DRAFT (never auto-approve) a work
    access request via draft-and-confirm — the agent inherits exactly the caller's RBAC (§12.11).
15. RBAC (seed in seed_rbac.py):
    hse_management:incidents:read / create / update / close / search / ask;
    hse_management:permits:read / create / approve; hse_management:summary;
    plus the dual-approval gate permissions: hse:permit_approve (HSE team approves HSE side),
    maintenance:access_approve (Manager team approves Manager side),
    maintenance:access_request (anyone who may raise a request). Anyone may submit a SafetyObservation.
    hse_officer gets hse_management:* ; observations are open to all authenticated users.

IMPACT:
- What changes: adds hse_management module; adds an HSE gate that work_order_management consults before
  In Progress; publishes HSE events to the Notification Engine.
- Backward compatible: yes for data; the WO "In Progress" gate is a NEW precondition — flag to the owner
  that work orders requiring access can no longer start without a Granted request + Active permit
  (this is intended behavior, but it is a behavior change on the WO state machine — confirm before build).
- New tables: hse_incidents, incident_investigations, permits_to_work, ptw_checklist_items,
  work_access_requests, work_access_approvals, risk_assessments, safety_observations, hse_statistics.
- Existing routes affected: work_order_management transition-to-In-Progress now calls the HSE gate.

Please provide:
A) All models with complete fields, types, constraints, indexes (incl. embedding columns)
B) All API endpoints (incident + investigation CRUD/close; PTW CRUD + checklist + status transitions;
   access-request create + per-group approve/reject + status transitions; risk assessment; observations)
C) The PTW + dual-approval gate: exact signature of hse_management.can_start_work(work_order_id) and how
   work_order_management consults it (one-way service call; the cross-module side-effects stay Celery events)
D) TRIR/LTIR calculation logic (standard formulas: per 200,000 man-hours)
E) The dual-approval state machine (HSE + Manager, both required, either can reject) on the Approval Engine
F) KPI/chart-data endpoints and the export endpoints (reuse §4.6 / §4.7 — Prompt 15 — no duplication)
G) Frontend specification: incident form, investigation/CAPA tracker, PTW issue screen with checklist,
   access-request + dual-approval inbox, safety observation wall, HSE dashboard (KPI cards + charts +
   Excel/PDF export); plus "What you could add next" (e.g. MoC, audit/inspection module, contractor HSE)
```

---

### PROMPT 20 — Phase 3 KPIs & Reporting (HR + HSE Dashboards) (Phase 3-R)

```
PROJECT CONTEXT:
We are building a CMMS for the petroleum industry on top of an existing RAG/KMS system.
Backend: FastAPI + PostgreSQL + pgvector + SQLAlchemy + Alembic + Celery.
Architecture: a modular monolith targeting future microservice extraction.
This is a REPORTING sub-phase (Phase 3-R), built entirely on the shared conventions in §4.6 (Export
Engine) and §4.7 (Dashboard & Chart-Data Convention), already delivered in Prompt 15.

ARCHITECTURAL GOAL — MODULAR MONOLITH → FUTURE MICROSERVICES:
This project is built as a modular monolith. Every module must be independently extractable into a
microservice in the future. ALL new code must follow these rules without exception:
1. NEVER import another module's SQLAlchemy model. Use that module's service functions instead.
2. NEVER call another module's route functions. Routes are HTTP handlers, not a service API.
3. Cross-module writes happen via Celery tasks (async event) — not synchronous service calls.
4. Shared types/enums live in backend/shared/ only — never in one module imported by another.
5. Each module has its own independent Alembic migrations — never mix two modules in one revision.
6. Models/__init__.py is for Alembic discovery only — no business code imports from it.
Already built: hr_management (Prompts 16–17), hse_management (Prompt 19), and the shared Export Engine +
Dashboard/Chart-Data framework (Prompt 15). DO NOT re-implement export or the chart-data schema — reuse them.

TODAY'S TASK: the Phase 3 reporting layer — HR and HSE KPI cards, chart-data report endpoints, summary
pages, and export wiring. This is mostly aggregation endpoints — typically NO new tables (KPIs are
computed over existing hr_management / hse_management data, cached per §4.7).

REQUIREMENTS:
1. HR KPI cards — GET /kpi/hr → [{ key, label, value, unit, trend }] (§4.7 shape), e.g.:
   total_headcount, headcount_by_status, leave_utilisation_pct, certs_expiring_30d, training_compliance_pct.
2. HSE KPI cards — GET /kpi/hse → e.g.: open_permits, pending_access_requests_by_group, trir, ltir,
   open_incidents, overdue_corrective_actions, near_misses_this_period.
3. HR report endpoints (chart-data shape: { chart_type, x, series, unit }; recommended chart_type set
   by backend), each accepting ?from=&to=&group_by=day|week|month and relevant dimension filters:
   - GET /reports/hr/headcount            → headcount by department over time      (stacked_bar / line)
   - GET /reports/hr/leave-utilisation    → used vs entitled leave days by type     (bar)
   - GET /reports/hr/training-compliance  → % of required trainings completed       (gauge / bar)
   - GET /reports/hr/cert-expiry          → certs expiring by month / by status     (bar)
4. HSE report endpoints:
   - GET /reports/hse/incident-rate       → TRIR / LTIR trend over time             (line)
   - GET /reports/hse/incidents-by-type   → incident composition                    (donut)
   - GET /reports/hse/permits-status      → permits by status                       (stacked_bar)
   - GET /reports/hse/access-requests     → access requests pending HSE vs Manager   (bar)
5. Each aggregation reads ONLY through the owning module's service functions (hr_management /
   hse_management) — never their models. New cross-module reads, if any, go through service calls.
6. Summary pages: KPI cards on top, charts below, a filter bar (period + dimension), and an Export button
   (xlsx / csv / pdf) wired to the shared Export Engine (§4.6) — the same filters export the on-screen view.
   DO NOT implement export here; just call POST /{module}/{entity}/export from Prompt 15.
7. Caching: short-TTL cache per (company, params), invalidated on the relevant module's events (§4.7).
8. Assistant integration (§12.4/§12.5): the existing hr/hse tool sets' summarize/ask already expose these
   numbers to chat ("how many employees are on leave this week?", "what's our TRIR for Q1?") and can
   trigger an export from chat — wire the report endpoints into those tool sets, no new agent code.
9. RBAC: reuse existing module permissions — viewing HR KPIs requires hr_management:summary, HSE KPIs
   require hse_management:summary; export requires the module's {module}:export (Prompt 15). No NEW
   permission names unless a dashboard-level gate is needed; if so, seed hr_management:summary /
   hse_management:summary (already in §6) — do not invent new ones.

IMPACT:
- What changes: adds KPI + report (chart-data) endpoints and summary pages for HR and HSE; wires export.
- Backward compatible: yes (read-only aggregation; no schema change expected).
- New tables: none (optional: a small report-cache table if not using an existing cache layer).
- Existing routes affected: none.

Please provide:
A) All KPI + report endpoint definitions with the exact §4.7 response schema and recommended chart_type
B) The aggregation/service approach (which hr_management / hse_management service functions each report calls)
C) (No new search module — these are dashboards; note search reuse where a report drills into a register)
D) Migration notes (only if a report-cache table is introduced; otherwise "no migration")
E) RBAC: reuse hr_management:summary / hse_management:summary + {module}:export — list the mapping
F) Frontend specification: HR summary page + HSE summary page (which KPI cards, which charts with
   recommended type, where the period/filter/export controls sit), reusing the Prompt 15 chart components
G) What you could add next (e.g. drill-down from a KPI card into the filtered register, scheduled
   email of the dashboard, target/threshold lines on the rate charts)
```

---

### PROMPT 21 — Notification Engine (Phase 4, Cross-Cutting)

```
PROJECT CONTEXT:
We are building a CMMS for the petroleum industry on top of an existing RAG/KMS system.
Backend: FastAPI + PostgreSQL + pgvector + SQLAlchemy + Alembic + Celery.
Architecture: a modular monolith targeting future microservice extraction.

ARCHITECTURAL GOAL — MODULAR MONOLITH → FUTURE MICROSERVICES:
This project is built as a modular monolith. Every module must be independently extractable into a
microservice in the future. ALL new code must follow these rules without exception:
1. NEVER import another module's SQLAlchemy model. Use that module's service functions instead.
2. NEVER call another module's route functions. Routes are HTTP handlers, not a service API.
3. Cross-module writes happen via Celery tasks (async event) — not synchronous service calls.
4. Shared types/enums live in backend/shared/ only — never in one module imported by another.
5. Each module has its own independent Alembic migrations — never mix two modules in one revision.
6. Models/__init__.py is for Alembic discovery only — no business code imports from it.
This is a CROSS-CUTTING engine (§4.1), not a domain module. It lives in backend/core/notifications/.
Every module already publishes Celery events (per its own prompt). This engine LISTENS and routes them.
Celery tasks follow Rule 10 (acks_late, retries, TaskResult). Email send is heavy → Celery (Rule 8).

TODAY'S TASK: the Notification Engine — turn cross-module domain events into in-app bell notifications
and emails, driven by configurable rules.

REQUIREMENTS:
1. NotificationTemplate model:
   - event_type (string key: "work_order.approved", "stock.below_minimum", "pm.due_soon",
     "leave.pending", "certification.expiring", "letter.sent", "access_request.raised", ...)
   - title_template, body_template (Jinja2), default_channels: in_app / email / both
   - locale-aware: title/body templates keyed by language (multilingual per §12.5), company_id
2. NotificationRule model (the "when X happens in module Y, notify Z" rule):
   - event_type, is_active
   - recipient_resolver: a declarative spec (JSONB) describing who to notify — e.g.
     { "type": "entity_field", "field": "assignee_user_id" } | { "type": "role", "role": "hse_officer" }
     | { "type": "approver_group", "group": "MANAGER" } | { "type": "static_users", "ids": [...] }
   - channel_override (nullable), company_id
   - Configurable via an admin UI (the admin UI itself is out of scope for this prompt, but the engine
     must support CRUD on rules so that UI can drive it).
3. Notification model (the in-app bell item):
   - recipient_user_id, title, body, entity_type, entity_id (deep-link target),
     event_type, is_read, read_at, created_at, company_id
4. NotificationDelivery model (per-channel audit): notification_id, channel: in_app | email,
   status: queued | sent | failed, error, sent_at — so a failed email is visible and retryable.
5. Event intake: a single entry point publish(event_type, entity_ref, payload) that modules call by
   dispatching a Celery task (e.g. app.send_task("core.notifications.tasks.on_event", ...)). The engine
   resolves matching rules → recipients → renders templates → writes Notification rows → dispatches email.
   Cross-module Celery tasks run as system (no per-user permission check inside — §Rule 10); the
   dispatching route already verified the actor's permission.
6. Channels: (a) in-app bell (Notification rows, exposed via API + unread count), (b) email via Celery
   (reuse the existing mailer; one Celery task per email; retries per Rule 10). Design so SMS/push can be
   added later as new channels without schema change.
7. Endpoints: list my notifications (paginated, ?unread=true), unread count, mark one/all read,
   rule CRUD (admin), template CRUD (admin), resend a failed delivery (admin).
8. Concrete rules to ship as seed examples (mapping the events emitted by earlier prompts):
   - work_order.approved          → notify assignee
   - leave.pending                → notify the approver (manager)
   - certification.expiring       → notify employee + their manager (Prompt 17 daily task)
   - letter.sent                  → notify recipients (Prompt 18)
   - access_request.raised        → notify HSE queue + Manager queue (Prompt 19)
   - access_request.decided       → notify requester; access_request.granted → notify maintenance
   - stock.below_minimum / pm.due_soon → notify the relevant role
9. RBAC: admins configure rules/templates (notifications:rules:manage, notifications:templates:manage);
   every user can read/dismiss their own notifications (notifications:read). The engine itself publishes
   as system — no user permission check inside the worker (§Rule 10). Seed all in seed_rbac.py.

IMPACT:
- What changes: adds backend/core/notifications/ engine; modules' existing events now produce
  notifications + emails via rules. No change to how modules publish (they already send Celery events).
- Backward compatible: yes (additive; if no rule matches an event, nothing happens).
- New tables: notification_templates, notification_rules, notifications, notification_deliveries.
- Existing routes affected: none (modules keep publishing the same events).

Please provide:
A) All models with complete fields, types, constraints, indexes
B) All API endpoints (my-notifications list + unread count + mark-read; rule/template admin CRUD; resend)
C) The event-intake contract: exact publish(...) signature + the Celery on_event task, the recipient-
   resolver spec (JSONB) and how each resolver type maps to users, and template rendering (multilingual)
D) Alembic migration notes (+ the seed example rules/templates from requirement 8)
E) RBAC permission seeds (notifications:read, notifications:rules:manage, notifications:templates:manage)
F) Frontend specification: notification bell + dropdown, unread badge, notification center (filter by
   module/read), admin rule/template editor
G) What you could add next (e.g. per-user channel preferences / quiet hours, digest emails,
   web-push/SMS channels, escalation when a notification is unread past a deadline)
```

---

### PROMPT 22 — AI Manager Agent: Mature Assistant Core (Phase 4)

```
PROJECT CONTEXT:
We are building a CMMS for the petroleum industry on top of an existing RAG/KMS system.
Backend: FastAPI + PostgreSQL + pgvector + SQLAlchemy + Alembic + Celery.
Architecture: a modular monolith targeting future microservice extraction.

ARCHITECTURAL GOAL — MODULAR MONOLITH → FUTURE MICROSERVICES:
This project is built as a modular monolith. Every module must be independently extractable into a
microservice in the future. ALL new code must follow these rules without exception:
1. NEVER import another module's SQLAlchemy model. Use that module's service functions instead.
2. NEVER call another module's route functions. Routes are HTTP handlers, not a service API.
3. Cross-module writes happen via Celery tasks (async event) — not synchronous service calls.
4. Shared types/enums live in backend/shared/ only — never in one module imported by another.
5. Each module has its own independent Alembic migrations — never mix two modules in one revision.
6. Models/__init__.py is for Alembic discovery only — no business code imports from it.

THIS IS NOT A NEW MODULE. It is the MATURE STATE of the Assistant Core (backend/assistant/) defined in
master plan SECTION 12 — read §12 as the source of truth, especially:
- §12.1 Vision, §12.3 control flow (LangGraph router: search/summarize/ask/add_draft/general/file_intake/
  clarify), §12.4 Module Tool Contract + §12.4.1 in-process service calls (NOT loopback HTTP),
  §12.5 Draft-and-Confirm, §12.8 persistence/resumability (Postgres checkpointer), §12.9 error catalog,
  §12.11 RBAC (agent runs as exactly the caller, never more), §12.12 testing standard.
Already built (Phase 0-AI): the LangGraph agent, the router, the draft-and-confirm framework, the Module
Tool Contract + registry, the Postgres checkpointer, the error catalog. Per-phase AI sub-phases (§12.13)
have registered each module's ToolSet (procurement, warehouse, assets, work orders, PM, defects, HR,
communication, HSE) as they shipped.

TODAY'S TASK: bring the Assistant Core to full Phase-4 maturity — cross-module synthesis, manager
dashboard synthesis, and report generation — WITHOUT re-implementing the agent. This is refinement,
orchestration, and integration testing on top of what §12 already defines.

REQUIREMENTS:
1. Cross-module synthesis: the agent answers questions that span multiple registered tool sets in one
   turn — e.g. "show all assets with overdue maintenance that cost more than 5M in the last month". The
   planner (router, §12.3) fans out to the relevant modules' search/summarize/ask (in-process service
   calls, §12.4.1), MERGES and de-duplicates results, and CITES sources (module + entity ids). Define the
   multi-tool planning loop and the result-merge/citation format — building on the §12.3 graph, not replacing it.
2. Manager dashboard synthesis: a conversational path that aggregates the per-module KPI/summary tools
   (Prompt 20 + the financial/maintenance dashboards) into one executive narrative. This CONSUMES the
   Manager Dashboard API (Prompt 23) and each module's summarize tool — it does not compute KPIs itself.
3. Report generation: the agent generates a structured report (e.g. "generate a monthly maintenance
   report for Unit 2") by gathering data via tool sets and rendering through the shared Export Engine
   (Prompt 15, §4.6) to xlsx/pdf — as a draft-and-confirm action (§12.5). Reuse Prompt 15; do NOT build
   a second export path. (Ties into §12.14 future document generation.)
4. LLM routing refinement: improve tool selection as the number of registered tools grows — better tool
   descriptions, disambiguation/clarify (§12.7) when intent is ambiguous, and a fallback when no tool
   fits. No new graph; refine the existing router + tool descriptions.
5. RBAC (§12.11, non-negotiable): the agent runs as exactly the current user. Every read tool action re-checks
   the user's permissions before running; reads are scoped to the user; drafts commit only if the user
   holds the action permission — enforced by the module's own create/update endpoint that the frontend commits
   to (the agent performs no write). Cross-module synthesis must never surface rows the user
   can't read. No new permission names beyond assistant:chat / assistant:draft / assistant:files (§12.11)
   — manager-only features are gated by the underlying module summary permissions, not a new agent role.
6. Audit (§12.18): every agent query/answer and every committed draft is logged (who asked what, which
   tools ran, what was returned/committed) via the Audit Log (§4.3).
7. Observability (§12.20): LLM usage + per-step tracing on top of the structured logging (§4.5).
8. Test suite (§12.12, mandatory): unit (mocked LLM) for the new synthesis/merge/report logic; route
   integration; and agent end-to-end for complex multi-step scenarios — multi-tool fan-out + merge +
   citation, report-generation draft → confirm, interruption (pause → answer → resume), resume-after-
   restart (checkpointer), multilingual, and RBAC scoping (a low-privilege user gets a correctly reduced answer).

IMPACT:
- What changes: matures backend/assistant/ (synthesis, dashboard narrative, report generation, router
  refinement). Refinements + integration — NOT a rewrite of the agent.
- Backward compatible: yes (the chat endpoint and draft API are unchanged; new capabilities are additive).
- New tables: none expected (reuse AgentRun / Draft / checkpointer from §12.8). Note any new index needed.
- Existing routes affected: POST /assistant/chat behavior is extended (richer answers), not its contract.

Please provide:
A) How the agent synthesizes cross-module data (the multi-tool planning loop on the §12.3 graph: fan-out
   to registered tool sets via in-process service calls §12.4.1, merge + de-duplicate, cite sources)
B) How it generates reports (gather via tool sets → shared Export Engine §4.6/Prompt 15 → draft-and-confirm §12.5)
C) LLM routing refinement (tool-description strategy, clarify branch §12.7, no-tool-fits fallback)
D) The RBAC enforcement path through synthesis (§12.11) — where the per-action permission re-check sits
E) Reference to §12 for the Agent Core architecture (state, checkpointer, draft model) — do NOT re-specify it
F) The test suite for complex multi-step scenarios (§12.12) — list the end-to-end cases
G) What you could add next (e.g. proactive insights/alerts pushed to managers, scheduled report runs via
   the scheduler, agent-authored letters via communication_management — all as draft-and-confirm)
```

---

### PROMPT 23 — Manager Dashboard API (Phase 4)

```
PROJECT CONTEXT:
We are building a CMMS for the petroleum industry on top of an existing RAG/KMS system.
Backend: FastAPI + PostgreSQL + pgvector + SQLAlchemy + Alembic + Celery.
Architecture: a modular monolith targeting future microservice extraction.
Built on the §4.7 Dashboard & Chart-Data Convention and the §4.6 Export Engine (Prompt 15) and the
per-module /kpi/{module} + /reports/{module}/{name} endpoints delivered in each phase's reporting sprint
(financial 0-R, inventory/procurement 1-R, maintenance 2-R, HR/HSE 3-R / Prompt 20).

ARCHITECTURAL GOAL — MODULAR MONOLITH → FUTURE MICROSERVICES:
This project is built as a modular monolith. Every module must be independently extractable into a
microservice in the future. ALL new code must follow these rules without exception:
1. NEVER import another module's SQLAlchemy model. Use that module's service functions instead.
2. NEVER call another module's route functions. Routes are HTTP handlers, not a service API.
3. Cross-module writes happen via Celery tasks (async event) — not synchronous service calls.
4. Shared types/enums live in backend/shared/ only — never in one module imported by another.
5. Each module has its own independent Alembic migrations — never mix two modules in one revision.
6. Models/__init__.py is for Alembic discovery only — no business code imports from it.
Already built: every module's KPI/report endpoints (financial, procurement, warehouse, work orders, PM,
defects, HR, HSE) and the shared Export Engine + chart-data schema (Prompt 15). DO NOT re-implement
per-module KPIs or export — this endpoint AGGREGATES them.

TODAY'S TASK: a single unified executive aggregation endpoint that returns one consolidated KPI view
across all modules, for the frontend's one-page executive dashboard.

REQUIREMENTS:
1. GET /dashboard/executive — returns KPIs from every domain in one response, grouped by domain:
   { financial: {cards:[...]}, procurement: {...}, warehouse: {...}, maintenance: {...},
     hr: {...}, hse: {...} } — each card in the §4.7 { key, label, value, unit, trend } shape.
2. It aggregates by calling each module's existing KPI/summary SERVICE function (the same logic behind
   GET /kpi/{module}) in-process — never by importing module models and never via loopback HTTP to the
   /kpi routes (§12.4.1). If a module's KPI logic lives in a route handler, refactor it into a service
   function both the route and this aggregator call (one implementation).
3. Params: ?from=&to=&company_id= (multi-tenant aware — company scope enforced; a user only sees their
   company). Optional ?domains=financial,maintenance,hse to fetch a subset.
4. Partial-failure tolerance: if one module's KPI call fails or the user lacks its permission, return the
   domains the user CAN see and mark the omitted ones (status per domain) rather than failing the whole
   response. The dashboard degrades gracefully.
5. RBAC: gate the endpoint with a high-level role (general_manager and above). CRUCIALLY, each domain's
   numbers are still filtered by the caller's existing module permissions — a user without
   hse_management:summary does not get HSE cards even if they can hit /dashboard/executive. Reuse existing
   {module}:summary permissions; the only new gate is dashboard:executive:read (seed in seed_rbac.py).
   No sensitive figure is exposed beyond what the user could already see on the per-module dashboards.
6. Caching (§4.7): short TTL per (company, params, user-permission-set), invalidated on any contributing
   module's events. Reuse the Prompt 15 caching approach; do not invent a new one.
7. Export: the whole executive view exports via the shared Export Engine (§4.6, Prompt 15) —
   POST /dashboard/executive/export → xlsx/pdf. Do NOT re-implement export.
8. Assistant integration (§12.4): expose the aggregator as the data source the Manager Dashboard
   synthesis path in Prompt 22 consumes (one shared service, used by both the route and the agent tool).

IMPACT:
- What changes: adds /dashboard/executive (read-only aggregation) + its export; refactors any KPI logic
  still trapped in route handlers down into reusable service functions.
- Backward compatible: yes (additive; per-module /kpi endpoints are unchanged).
- New tables: none (optional small cache table if not reusing an existing cache layer).
- Existing routes affected: none functionally; some module KPI logic may move route → service (same output).

Please provide:
A) The /dashboard/executive response schema (domains → cards, per-domain status for partial failure)
B) The aggregation approach — which per-module KPI SERVICE functions it calls and how it parallelizes/
   tolerates partial failure, with the §12.4.1 in-process (not loopback HTTP) rule made explicit
C) (No new search — this is a dashboard endpoint; note it reuses each module's existing KPI services)
D) Migration notes (only if a cache table is added; otherwise "no migration") + the dashboard:executive:read seed
E) RBAC: dashboard:executive:read gate + per-domain filtering by existing {module}:summary permissions
F) Frontend specification: the one-page executive dashboard (domain sections, KPI cards with trend chips,
   period/company filter bar, Export to Excel/PDF), reusing the Prompt 15 chart/card components
G) What you could add next (e.g. configurable card layout per manager, target/threshold alerting,
   period-over-period comparison view, drill-down from an executive card into the owning module's report)
```

---

## 9. Frontend Specification Format

After each backend implementation, provide the frontend team with this structure:

```
FRONTEND SPEC — [Module Name]

SCREENS:
  1. [Screen Name]
     - Route: /module/screen
     - Access: roles that can see this
     - Purpose: what the user does here
     - Key components:
       • [Component]: what it shows/does
     - API calls:
       • GET /endpoint → what it returns
       • POST /endpoint → what it creates
     - States: loading / empty / error / filled

FORMS:
  1. [Form Name]
     - Trigger: when/how opened
     - Fields: field name (type, required/optional, validation)
     - Submit: which endpoint, success/error behavior

WIDGETS/REUSABLE COMPONENTS:
  - Component name: what it is, what props it takes, which screens use it
```

---

## 10. Naming Conventions (Follow Always)

| Concern | Convention | Example |
|---|---|---|
| App folder | snake_case | `warehouse_management/` |
| Model class | PascalCase | `StockMovement` |
| DB table | snake_case plural | `stock_movements` |
| API route | kebab-case | `/stock-movements` |
| Pydantic schema | PascalCase + suffix | `StockMovementCreate`, `StockMovementRead` |
| Service function | snake_case verb_noun | `create_stock_movement()` |
| Permission name | `module:action` | `warehouse:create_movement` |
| Number series | MODULE-YEAR-NNNN | `WO-2026-0042` |

---

## 11. Quick Reference: What Each Role Can Do

| Role | Phase 1 Access | Phase 2 Access | Phase 3 Access | Phase 4 Access |
|---|---|---|---|---|
| `system_admin` | Full | Full | Full | Full |
| `general_manager` | View + Reports | View + Reports | View + Reports | Full + Agent |
| `procurement_officer` | Full Procurement | View Assets | - | Letters |
| `warehouse_keeper` | Full Warehouse | View Materials | - | Letters |
| `maintenance_engineer` | View Materials + Issue Stock | Full WO + Assets | - | Letters + PTW |
| `maintenance_planner` | View Materials | Full PM Plans | - | Letters |
| `hr_manager` | - | - | Full HR | Letters |
| `hse_officer` | - | View WO | - | Full HSE |
| `department_head` | View Procurement | View WO | View Dept HR + Approve Leave | Letters |
| `employee` | - | - | Own data + Leave | View Announcements |

---

## 12. AI Assistant Backbone (Chat as the Universal Interface)

> This section is **authoritative** for everything related to the chat page, the AI agent, and AI-friendliness.
> The Phase 4 "AI Manager Agent" (Prompt 13 / Prompt 20) is **superseded** by this section: it is no longer a
> one-off final-phase build but the **mature state** of the Assistant Core defined here, which is built early
> and grown phase by phase.

### 12.1 Vision

The **chat page is the main page of the system**. A user must be able to do *anything* there without navigating to other parts of the UI:

1. **Search** across any module — financial, documents, warehouse, purchase, and (as they are built) maintenance, HR, HSE, etc.
2. **Add data** by describing it ("add a recipe with this data and this picture") — the agent builds a **draft**, shows it for review, and writes only after the user accepts.
3. **Summarize** — "how much money do we have", "which cards exist", "how many of this product are in the warehouse".
4. **Answer general questions** from the model's own knowledge, clearly separated from grounded system data.
5. **Accept files** — PDFs and photos — as input.
6. Operate **without the UI at all**: every capability is a clean backend API, so a user (or another LLM) can drive the system purely through the assistant API.

The system must be **LLM-friendly end to end** and **multilingual** — the user may work in a language other than English; the assistant detects the user's language and responds and drafts in it.

### 12.2 Where it lives — Assistant Core + per-phase AI tracks

**Decision:** A new cross-cutting module **`backend/assistant/`** ("Assistant Core") is built early (Phase 0-AI) and owns the agent. Each later delivery phase ships a **thin AI track** that registers that phase's modules as tools into the Core — it does **not** rebuild the agent.

```
backend/assistant/
  agent/
    graph.py          ← the LangGraph stateful agent (nodes, edges, router)
    router.py         ← intent classification → next step
    nodes/            ← one file per step type (search, summarize, ask, add_draft, general, file_intake)
    state.py          ← AgentState TypedDict (question, plan, current_step, pending_draft, language, ...)
    checkpointer.py   ← LangGraph Postgres checkpointer (resumable runs)
  tools/
    registry.py       ← ToolRegistry: modules register their tool sets here at startup
    contract.py       ← the Module Tool Contract (Section 12.4) — base classes/protocols
  drafts/
    models.py         ← Draft, AgentRun models
    service.py        ← create/get/update/cancel draft + record-committed (no domain write)
    routes.py         ← draft committed-notification/cancel endpoints
  intake/
    service.py        ← multimodal routing: heavy pipeline vs inline (Section 12.6)
  routes.py           ← POST /assistant/chat (the one agentic endpoint), plus session/run endpoints
  permissions.py
  search/             ← (the assistant itself is searchable over its own sessions if needed)
```

> **Modular-monolith compliance.** Assistant Core never imports another module's SQLAlchemy models. Modules
> register their tools via the registry (Section 12.4); the agent calls those registered callables. Heavy work
> goes through Celery (Rule 8/10). This keeps the assistant extractable as its own service later.

The existing `core/agents/` (langgraph.py, pre_search.py, file_founder.py) and `routs/chat.py` are the **seed** of this module. Phase 0-AI refactors them into `backend/assistant/` cleanly; the existing document/comment/financial retrieval becomes the first registered tool set.

### 12.3 The agent control flow (stateful, interruptible)

The chat route is a **stateful LangGraph agent**, not a single request/response. It plans in steps and decides the next step from the user's input.

```
            ┌─────────────────────────────────────────────┐
            │              ASSISTANT GRAPH                 │
  user msg →│  [router] → classify intent + language       │
            │     │                                        │
            │     ├─→ search        (cross-module)         │
            │     ├─→ summarize     (KPIs/totals)          │
            │     ├─→ ask           (grounded module Q&A)  │
            │     ├─→ add_draft     (build → confirm)      │
            │     ├─→ general       (model knowledge)      │
            │     ├─→ file_intake   (PDF/photo)            │
            │     └─→ clarify       (ask user a question)  │
            │     │                                        │
            │  [decide next] → loop or finish              │
            └─────────────────────────────────────────────┘
```

**Multi-step planning.** After each step the agent re-evaluates and decides the next step based on results and any new user input. A task can span several steps (e.g. file_intake → add_draft → confirm).

**Interruption (chosen behavior: pause → answer → offer resume).** If the user sends a new request while a task is in progress (e.g. mid add-draft), the agent **suspends** the current run (its full state is checkpointed), handles the new request, then offers: *"Resume the draft you were building?"* Unfinished work is never silently lost. Multiple suspended runs may stack per chat.

**Cancellation.** The user can cancel the current task at any time. Cancelling sets the `AgentRun` to `cancelled`, discards the associated unconfirmed `Draft`, and (if a Celery job was dispatched) revokes it where possible.

**Long-running work.** Any step exceeding ~200ms (embedding, PDF parse, image analysis, bulk add) is dispatched to Celery per Rules 8 & 10; the chat stays interactive and the result surfaces when the task completes (the run is checkpointed as `waiting_on_task`).

### 12.4 Module Tool Contract (every module must implement)

Every module registers a tool set into `assistant/tools/registry.py` at startup. This is the **only** way the agent reaches a module — no model imports.

```python
# Each module provides, in {module}/assistant_tools.py:
class ModuleToolSet:
    name: str                 # e.g. "warehouse"
    description: str          # natural-language; the LLM uses this to route
    permissions: dict         # action -> required RBAC permission

    def search(db, user, query, mode, filters, limit) -> list[Hit]: ...
    def summarize(db, user, request) -> Summary:    # totals/KPIs in user's base currency
    def ask(db, user, question) -> GroundedAnswer:  # grounded NL answer + sources
    def add_draft(db, user, payload, attachments) -> Draft:  # builds a draft + its commit_target; does NOT commit
```

- `search` / `summarize` / `ask` reuse the module's existing `search/` + `/ask` + `/summary` work — no duplication.
- `add_draft` returns a structured `Draft` (see 12.5) pre-filled with the proposed payload **and a `commit_target`** (the module's own create/update endpoint + HTTP method + required permission). **There is no `commit_draft` seam: the assistant never writes domain data.** The actual write is performed by the **frontend** calling that module endpoint directly (see 12.5) — the same endpoint the module UI uses, fully RBAC-checked there.
- Every action maps to an existing module permission (`{module}:search`, `{module}:summary`, `{module}:ask`, `{module}:create`). For reads the agent enforces the user's RBAC before invoking the action; for writes `add_draft` checks the create/update permission early (so no un-committable draft is offered) and the **module endpoint is the authoritative enforcement point** at commit. A missing permission surfaces as `PERMISSION_DENIED` from the error catalog (Section 12.9).

#### 12.4.1 How the agent talks to modules — in-process service calls, NOT loopback HTTP

**Decision:** The agent reaches modules through **in-process service-function calls** (via each module's tool-set adapter), never by making HTTP requests to the system's own routes, and never through a duplicated AI-only function layer.

- **This applies to reads** (`search` / `summarize` / `ask`). **Do** call the same service functions the routes call. If read logic currently lives inside a route handler, refactor it down into a service function and have both the route and the tool set call it. One implementation, one test surface.
- **Do not** make the agent issue HTTP requests to `/purchase/...`, `/warehouse/...`, etc. (loopback HTTP). In a single-process modular monolith this only adds JSON serialization, a second auth round-trip, and middleware overhead, and it violates Rule 2 ("routes are HTTP handlers, not a service API").
- **Do not** write a parallel set of AI-only functions that re-implement what the services already do — they will drift from the routes.
- **Writes need no assistant-side path.** The agent does **not** commit. `add_draft` only assembles the payload and resolves the `commit_target`; the **frontend** performs the write by calling the module's existing create/update route directly (a real external client, not loopback HTTP). This keeps the write load off the assistant server and reuses the module's one create path.
- **RBAC is still enforced.** For reads, because the tool set bypasses the route's `require_permission` dependency, the agent calls the shared permission check (`has_permission` / `get_user_permissions`) **before** invoking the action, mapping failures to `PERMISSION_DENIED`. For writes, the module's create/update route applies its normal `require_permission` at commit time — the authoritative check — and `add_draft` checks the same permission early to avoid offering an un-committable draft. The agent never gains access the user lacks.
- **Cross-module side-effects keep the existing pattern:** the module's create/update route performs its own write and publishes any cross-module effect (e.g. warehouse intake on receipt) as a Celery event — not a direct call into another module (Rules 3, 8, 10). This is unchanged: the effect fires on the module's normal write path regardless of whether the write was triggered from the UI or from a confirmed assistant draft.
- **When HTTP becomes correct:** the read adapters switch from in-process service calls to an HTTP/RPC client only after a module is extracted into its own microservice (Phase 4+) — and nothing else in the agent changes. This is exactly why the adapter layer exists.

**Draft ownership (answering "central vs per-app"):** the generic draft machinery — the `Draft` table, lifecycle (create/edit/cancel/record-committed), persistence, resume, checkpointer, multilingual handling — lives **centrally in `backend/assistant/`**. Each module owns only its thin `assistant_tools.py` adapter: how to build/validate a draft payload for its entities and which endpoint+permission is its `commit_target`. The module does **not** expose a commit function to the assistant — committing is the frontend calling the module's own create/update route. This keeps module isolation (each module owns its data, validation, and migrations) while keeping the agent machinery DRY and giving the frontend one consistent draft API.

### 12.5 Draft-and-Confirm Write Framework (multilingual)

Writes never happen directly from a chat message, and **the assistant server never performs the write itself**.
Flow:

```
user describes data (+ optional file)
  → agent builds Draft (payload + commit_target)
  → frontend renders Draft → user edits/accepts
  → frontend POSTs the final payload to the module's OWN create/update endpoint (RBAC + validation there)
  → frontend notifies POST /assistant/drafts/{id}/committed → assistant records the result
```

This keeps the write load on the module's normal API path (the same endpoint the module UI calls) and off the
assistant server. The assistant's role for writes is to **assemble and track** the draft, not to commit it.

**`Draft` model** (in `assistant/drafts/models.py`):
```
Draft
  ├── id, chat_id, agent_run_id, created_by_user_id, company_id
  ├── target_module (str)        # "warehouse", "financial", ...
  ├── target_action (str)        # "create_item", ...
  ├── payload (JSONB)            # the proposed fields, pre-filled
  ├── commit_target (JSONB)      # { "method": "POST", "endpoint": "/financial/receipts",
  │                              #   "permission": "financial_management:receipts:create" }
  │                              # what the frontend calls to commit (PUT/PATCH + entity id for updates)
  ├── attachments (JSONB)        # file_asset ids extracted from uploaded PDF/photo
  ├── language (str)             # detected user language (BCP-47), e.g. "fa", "en"
  ├── status: pending | cancelled | committed | failed
  ├── validation (JSONB)         # per-field validation result for the frontend
  ├── committed_entity_ref (JSONB nullable)  # set from the frontend's committed-notification
  └── created_at, updated_at
```

**Endpoints** (Assistant Core):
- `POST /assistant/chat` — the agentic endpoint; may return a `Draft` (with its `commit_target`) for the frontend to render.
- `GET  /assistant/drafts/{id}` — fetch a draft (resume later).
- `PATCH /assistant/drafts/{id}` — user edits fields before committing (assistant-side bookkeeping copy).
- `POST /assistant/drafts/{id}/committed` — **record-only.** The frontend calls this *after* it has written via the
  module endpoint, passing the resulting `committed_entity_ref`. The assistant verifies the caller owns the draft,
  marks it `committed`, and logs it to history. **It writes no domain data and re-checks no domain permission** —
  the module endpoint already enforced RBAC and validation when the frontend wrote.
- `POST /assistant/drafts/{id}/cancel` — discard.

> The actual create/update is **not** an assistant endpoint. The frontend POSTs the final (possibly edited)
> payload straight to `commit_target.endpoint`, which applies `require_permission` and validation exactly as for a
> UI-initiated write. "Chat text never commits" still holds: commit requires the explicit frontend call, never prose.

**Multilingual rules:**
- The agent detects the user's language and conducts the whole exchange (questions, field labels, confirmations, errors) in that language.
- Drafts store `language`; field **labels/help** shown to the user are localized, while the **stored values** use the module's canonical field names/enums.
- Numerals, dates, and currency follow the user's locale on display but are stored canonically.

### 12.6 Multimodal input (PDF / photo)

Files attached to a chat message are routed by `assistant/intake/service.py`:

- **Heavy path (reuse existing pipeline):** documents needing full extraction/OCR/chunking go through the existing `document_management` + MinerU PDF pipeline + image embedding (already Celery-backed). The agent waits via the task-polling mechanism and uses the extracted content for search/add_draft/summary.
- **Lightweight inline path:** when full ingestion is unnecessary — e.g. a single photo to read off a nameplate, a short receipt image, a quick "what does this say" — the file is handled **inline** (passed directly to a vision/parse step) without creating a permanent document record, unless the user asks to save it.
- The router decides heavy vs inline based on file type, size, and the user's intent; the choice is recorded on the `AgentRun` for traceability.

### 12.7 General-knowledge answering (intent routing)

The router (12.3) has an explicit **`general`** branch for questions the model can answer from its own knowledge (not system data). Grounded answers (search/ask/summarize) always cite system sources; `general` answers are clearly marked as model knowledge so the two never blur. The router may also choose **`clarify`** to ask the user a question before proceeding.

### 12.8 Persistence & resumability

Chosen behavior: **persist server-side, resumable.**

- **`AgentRun` model:** id, chat_id, user_id, company_id, status (`active | suspended | waiting_on_task | completed | cancelled | failed`), current_step, plan (JSONB), language, created_at, updated_at.
- **LangGraph Postgres checkpointer:** the agent's full graph state is checkpointed to Postgres after each step, so a run can be suspended (interruption), parked (waiting on Celery), or resumed later from any device.
- Drafts persist independently (12.5), so a half-built draft survives app close and can be resumed.
- This persistence is what makes **"use without UI"** real: all state lives in the backend; any client (including another LLM) can start, resume, confirm, or cancel via the API.

### 12.9 Error catalog — consolidate + auto-export

Chosen scope: **consolidate into one registry + auto-export a machine-readable catalog.**

- `core/exceptions/error_codes.py` becomes the **single source of truth** for every non-500 error. Ad-hoc `HTTPException(...)` raises across modules are migrated to registered, coded `AppException`s.
- Standard shape stays: `{ error: { code, message, user_message, details, request_id } }` (see `docs/frontend-error-codes.md`).
- A build/CI step **auto-generates** the catalog from the registry into:
  - `docs/frontend-error-codes.md` (human-readable, already exists), and
  - a machine-readable `errors.json` (code, http_status, user_message, module) served at `GET /errors/catalog`.
- The frontend and the assistant both consume the catalog so they know every error a call can return. `INTERNAL_SERVER_ERROR` is the only uncatalogued case (it is just "something failed").
- Every new module's permissions/routes must raise only catalogued codes; CI fails on an uncatalogued raise.

### 12.10 Tag metadata — admin-defined per company (JSONB)

Chosen model: **admin-defined field schema + JSONB values**, because the required fields differ per customer.

Default fields requested (a starting template, fully editable by the admin): **MIH level, Criticality, Location, Type, P&ID number, Supplier, Group, Category, Unit.**

```
TagMetadataField   (per company — admin configurable)
  ├── id, company_id
  ├── key (str, stable)          # "criticality"
  ├── label (JSONB)              # localized display labels {"en": "...", "fa": "..."}
  ├── data_type: text | number | enum | date | reference
  ├── options (JSONB nullable)   # for enum
  ├── reference_module (str nullable)  # for "reference" type, e.g. supplier
  ├── required (bool), is_active (bool), sort_order (int)
  └── created_at, updated_at

Tag (existing tag_management) gains:
  └── metadata (JSONB)           # values keyed by TagMetadataField.key, validated against the company's schema
```

- An **admin UI** lets each company add/edit/reorder/retire metadata fields without a migration.
- Values are validated against the company's active `TagMetadataField` definitions on write.
- Metadata keys are searchable/filterable (the tag search includes JSONB key lookups), and exposed to the assistant so a user can say e.g. "show all tags where Criticality is A in Unit 2".
- Implementation lands as an extension of `tag_management` (its own migration), surfaced as a tool set per the Module Tool Contract.

### 12.11 RBAC for the assistant — the agent has exactly the caller's access, never more

**Core principle (non-negotiable): the agent's access is the access of the person using it.** The agent is not a privileged service account. It can see and do only what the current user is permitted to see and do. There is no path by which talking to the assistant grants more than the user already has in the UI.

Concrete rules:

- The agent **always runs as the current user** (`current_user`), carrying that user's identity and permission set into every step. It never elevates to admin or a system identity to "be helpful".
- **Every read tool action re-checks the user's RBAC** before it runs (`has_permission` / `get_user_permissions` in the adapter, per Section 12.4.1). A missing permission returns `PERMISSION_DENIED` from the error catalog — the agent does not silently skip or work around it. For writes, `add_draft` checks the create/update permission early (so no un-committable draft is offered).
- **Reads are scoped to the user too.** Search / summarize / ask only return data the user is allowed to read (company scope today; record-level scope when Section 6's `scope_checker` is activated). The agent must never surface rows from a module or company the user can't access.
- **Drafts inherit the creator's permissions.** A draft can only be *committed* if the user holds the target action's permission — enforced by the **module's own create/update endpoint** that the frontend POSTs to (which runs `require_permission` exactly as for a UI write). The assistant performs no domain write and re-checks no domain permission on the `committed` notification.
- **Multimodal / file input is access-checked too** — a user can only attach and act on files they're permitted to use (`assistant:files`).
- **Group chat (Phase 5):** each participant interacts with the agent under **their own** permissions. The agent's answer to person A may legitimately differ from its answer to person B in the same thread, because they have different access. The agent never leaks one participant's restricted data to another. See Section 12.17.
- Assistant-level permissions (declare in `assistant/permissions.py`, seed in migration) gate *use of the assistant itself*, on top of the per-module permissions above:
  ```
  assistant:chat      assistant   chat      Use the chat assistant
  assistant:draft     assistant   draft     Create/track add-drafts (commit is the module endpoint's own permission)
  assistant:files     assistant   files     Upload files to the assistant
  ```
- A user can only ever do *through chat* what they could do through the UI — chat is an interface, not an escalation path.

### 12.12 Testing standard (mandatory for every AI track)

Chosen bar: **unit (mocked LLM) + route integration + agent end-to-end.** Non-negotiable, enforced in CI. Every AI track and every backend module it touches must ship:

1. **Unit tests** for services and tool-set methods with the **LLM mocked** (deterministic) — `search`, `summarize`, `ask`, `add_draft` (incl. that it resolves the correct `commit_target`).
2. **Route integration tests** for every endpoint, asserting: success path, RBAC (403 → `PERMISSION_DENIED`) — including on the **module's own create/update endpoint** that the frontend commits to — validation, and that only **catalogued error codes** are returned.
3. **Agent end-to-end tests** (with a stubbed model) covering: intent routing per branch, draft built with the right `commit_target`, draft → `committed` notification (status + `committed_entity_ref` recorded, no domain write), draft → cancel, **interruption (pause → answer → resume)**, resume-after-restart (checkpointer), and multilingual response.
4. Tests for both the **LangGraph/LangChain layer** and the **backend routes** must be complete before a track is considered done. CI runs `pytest` + `alembic check`.

### 12.13 Per-phase AI sub-phase (parallel track template)

Each delivery phase has a matching **AI sub-phase** (`Phase N-AI`) worked **in parallel by a separate developer**, depending only on (a) the Assistant Core (Phase 0-AI) and (b) that phase's module APIs existing. Each `Phase N-AI` delivers:

1. A `{module}/assistant_tools.py` `ModuleToolSet` for each module in the phase (search/summarize/ask/add_draft — no commit_draft; the frontend commits via the module's own endpoint).
2. Registration of those tool sets into the Assistant Core registry.
3. Router/description updates so the agent knows when to use them.
4. The full test suite from Section 12.12 for the new tools.
5. A short "what the assistant can now do" note for the frontend (example utterances).

### 12.14 Future — file/document generation (noted, no design yet)

Generating Word/PDF files from tag data, letter data, and other module data is a **desired future capability** to be designed later (template-based generation with admin-defined templates filled from system data). It is **not** designed in this revision; modules should keep their data accessible via tool sets so a future generation service can consume it without rework.

### 12.15 "Use without UI" guarantee

Because all state is server-side (12.8), all writes go through draft-and-confirm APIs (12.5), every module is reachable via the tool contract (12.4), and every error is catalogued (12.9), the entire system is operable through the assistant API alone. Any new module is "done" only when a user could complete its core workflows by talking to the assistant — not just through the UI.

### 12.16 Frontend slash-command quick tools (`//`)

Users get an inline command launcher: typing `//` (or another configured trigger) in the chat box opens a menu of quick actions — e.g. "add a recipe", "add/edit tag data", "search warehouse", "summarize spend". Selecting one starts the corresponding assistant action (usually an add-draft, Section 12.5) with a guided form instead of free text.

Key rules:

- **The menu is generated from the tool registry (12.4), filtered by the user's RBAC (12.11).** A user only sees `//` actions they are permitted to perform — the slash menu is not a separate permission surface, it is a view onto the same registry.
- Each `//` action maps to a registered tool-set method (`add_draft`, `search`, `summarize`, …). There is **no new backend** for slash commands beyond what the tool contract already provides — it is a frontend affordance over the existing Assistant API.
- Selecting an `add_draft` command opens the draft form pre-structured for that entity; the user fills it (multilingual, 12.5) and confirms — same draft-and-confirm path as a typed request.
- Optional companion: `@`-mentions to reference a specific entity (an asset tag, a PO number) so a command can be scoped to it.
- This launcher is single-user and may ship **early**, alongside the Assistant Core UX, rather than waiting for Phase 5 — it is listed as item 5.2 only for bookkeeping.

### 12.17 Group chat with the assistant (Phase 5 — not urgent)

A later, low-priority capability: multi-participant chat threads where the assistant is a participant, invoked on demand with a trigger (`//` command or `@assistant` mention) rather than responding to every message.

Design notes (to be detailed when Phase 5 is scheduled):

- **Per-participant access (critical).** Each person addresses the agent under their own RBAC (12.11). The agent's response is computed against the *asking* user's permissions and must never expose data that user couldn't see — even though others are in the thread. This is the main reason group chat is deferred: it needs careful access-scoping and is not needed now.
- **Invocation model.** The agent stays silent until explicitly addressed (trigger/mention), to avoid noise in human-to-human discussion.
- **Shared context, private results.** The thread is shared, but any action that returns restricted data, or any draft/commit, is attributed to and permission-checked against the specific user who requested it.
- **Reuses everything else.** Same agent graph, tool registry, draft-and-confirm, error catalog, and checkpointer — group chat adds a thread/participant model and the addressing rules, not a second agent.
- Priority **P2**. Tracked as Phase 5.1.

### 12.18 Audit trail for agent actions

Because the agent acts on the user's behalf, every state-changing thing it does is auditable through the existing **Audit Log** (Section 5.4.3 / Section 6 "Audit Trail").

- The **domain write** is audited where it always was — on the module's create/update route the frontend commits to (`user_id`, `action`, `target_module`, `entity_type`, `entity_id`, `old_value → new_value`). To tie that write back to the assistant, the frontend includes the `draft_id` when committing (and again in the `committed` notification), so the assistant records the AI-specific context (`agent_run_id`, `draft_id`, the originating chat message id, `committed_entity_ref`) against the run. Draft cancels and the committed-notification itself are audited by the assistant.
- Reads via the agent are not audited as writes, but the `AgentRun` history (12.8) preserves what was asked and which tools ran, so any query is reconstructable.
- Audit records are immutable and queryable (and searchable by the agent itself, for "who changed PO-123 and when").

### 12.19 Prompt-injection & ingested-content guardrails

The agent ingests untrusted content (uploaded PDFs/photos, retrieved documents, OCR text). All of it is **data, never instructions**.

- **Content is never treated as commands.** Text extracted from a file or pulled from search is inserted into the model context as quoted data, clearly delimited; instructions found inside ingested content ("ignore previous rules", "delete all POs") are ignored.
- **No write is ever auto-committed from ingested content.** A file can *populate* a draft, but a human still confirms it (12.5). The agent never reads "please approve this" out of a document and acts on it.
- **Tool calls are constrained by the user's RBAC (12.11), not by anything a document says.** Injected content cannot widen access.
- **Untrusted-vs-trusted separation** is maintained in the prompt: the user's actual instruction is the only command channel; everything retrieved/ingested is reference material.
- File handling is defensive: type/size validation, and (when the heavy pipeline is used) the existing document security path. Suspicious or unparseable files surface a catalogued error, not a silent action.

### 12.20 LLM usage limits & observability

- **Usage limits.** Per-user and per-company rate/quota limits on assistant calls and token spend, enforced in the Assistant Core. Exceeding a limit returns a catalogued error (e.g. `ASSISTANT_RATE_LIMITED`). Usage is recorded per `AgentRun` for cost attribution.
- **Observability.** Every agent run is traced to **Langfuse** (already provisioned in the repo via `docker-compose-langfuse.yml`): the step graph, tool calls, latencies, token counts, and outcomes. Traces carry `agent_run_id`, `user_id`, and `company_id` so a production issue can be inspected end to end. Tracing is read-only and must never block or slow the user-facing path (fire-and-forget).

### 12.21 Streaming responses

- The assistant streams its reply token-by-token for a responsive chat UX.
- Intermediate step signals (e.g. "searching warehouse…", "building draft…") may be streamed as lightweight status events so the user sees progress during multi-step runs.
- Structured payloads (a `Draft`, search hits, a summary table) are delivered as a final, complete message at the end of the stream — the frontend renders the draft/confirm UI from that, not from partial tokens.
- Streaming is transport only; it changes nothing about RBAC, drafts, persistence, or the error catalog. A stream that fails mid-flight leaves the `AgentRun` resumable (12.8).
