# PHASE 0 — Foundation (Currency · Purchase Management · Celery · Logging · Financial Dashboard)

> **Implementer: read only this file for Phase 0.** It is self-contained — it embeds every shared
> rule you must follow plus the full spec for every Phase 0 module. Build the modules in the order
> in §6. Stack: **FastAPI + PostgreSQL + pgvector + SQLAlchemy + Alembic + Celery** (one shared DB).
>
> Phase 0 is the foundation everything else stands on. **It must end fully consistent with the
> standards in Part A** — Phases 1 and 2 assume Phase 0 is correct.

---

# PART A — Shared standards (every module in every phase follows these)

## A1. Architecture: modular monolith, one shared database, FK-as-default

One deployable FastAPI process, **one shared PostgreSQL database**. Each feature area is its own
folder/module with its own Postgres **schema** (for organization). The system is a *modular monolith*
designed to be split into services later — but that day is a deliberate, last-resort migration, not the
default posture.

**Foreign keys are the default — including across module schemas.** We want the database to enforce
referential integrity (no orphan rows, no hand-written "does this id exist?" checks, safe cascades).
FKs and JOINs across module schemas in this one shared DB are **allowed and preferred**.

**Divisibility comes from clean code seams, NOT from removing FKs.** The four seam rules (always):

1. **No cross-module imports of another module's internals.** Never import another module's SQLAlchemy
   **models**, **route functions**, or **Pydantic schemas**. You may declare a cross-schema
   `ForeignKey("other.table.id")` column — but you resolve/display that row by calling the owning
   module's **service function**, never by importing its model or `relationship()`-ing into it.
2. **Reads from another module go through its service functions** (an in-process call today; the same
   call behind an HTTP client if the module is ever extracted). Routes are not the service API.
3. **Cross-module writes go through Celery events.** When module A must cause a write in module B
   (e.g. a posted GRN creating a stock movement), A publishes a Celery event; B's handler does the write.
   Never reach synchronously into another module to mutate its rows.
4. **Shared types live in `backend/shared/`** — enums, constants, money helpers, common exceptions.

**Soft references are NOT the default.** A soft reference (plain `INTEGER`, no FK, existence validated
in code) is used **only at a seam deliberately designated for physical extraction**. Do **not** add
pre-emptive denormalized snapshot columns "just in case" — denormalize only at extraction time.
`purchase_management` is the reference pattern: it links a financial receipt by id with **no** import of
`financial_management.models`.

> Full standard: master plan §0.5; the everyday version: `docs/KEEP_IN_MIND.md` →
> "Module boundaries & database separation — the rules". The canonical rules live in `AGENTS.md`.

## A2. Glossary (canonical term meanings — do not redefine)

| Term | Meaning |
|---|---|
| **model** (`model_management.ManagedModel`) | An **equipment-model type** (manufacturer + model name + specs). NOT an AI/ML model, NOT stock. |
| **item** (`material_management.Item`) | A **stockable thing** (material/spare/consumable/tool/chemical/PPE). The universal warehouse/PO line entity. May optionally reference a model via nullable `item.model_id`. |
| **tag** (`tag_management`) | A **functional position in the process** (P&ID tag). |
| **asset** (`asset_management.Asset`) | A **physical installed unit** with a serial number; references its model via `asset.model_id`. |
| **stock** (`StockItem`) | The **on-hand quantity of an item at a location**. Always points at `item_id`, never directly at a model. |

In Phase 0 there is no Item module yet, so purchase lines carry **free-text `item_name`** (upgraded to an
`item_id` FK in Phase 1).

## A3. Multi-currency — the 4-field money rule (build in Phase 0, used forever)

Every monetary amount in every new module uses **four columns** — never a single bare Numeric:

- `amount` — value in the transaction currency
- `currency_id` **FK → `currencies.id`** — which currency
- `amount_base` — equivalent in the company base currency (for reporting/aggregation)
- `exchange_rate_used` (Numeric 28,10) — rate applied at transaction time, **frozen** (never recalculated)

Company base currency is set once on `Company.base_currency_id` (FK → `currencies.id`). All dashboards
aggregate in base currency. Rounding follows `currency.decimal_places` (USD=2, IRR=0, IRT=0). Old
`financial_receipts` free-text currency strings stay as-is — do not retrofit.

## A4. Standard search pattern (every searchable module)

Search runs entirely in PostgreSQL. Each module ships a `search/` subfolder
(`repository.py` / `service.py` / `routes.py`) modelled on `financial_management/search/`:

- **Keyword** — `ILIKE '%query%'` across meaningful text columns (do NOT use `tsvector`/`tsquery`).
- **Semantic** — pgvector cosine distance `<=>` on an `embedding = Column(Vector(1024))` column
  (Jina embeddings, 1024 dims). Add `import pgvector.sqlalchemy` in the migration; the DB needs
  `CREATE EXTENSION IF NOT EXISTS vector`.
- **Hybrid** — run both, merge + deduplicate by entity id. Graceful degradation: if embedding generation
  fails, fall back to keyword so search never errors.

Endpoint: `POST /{module}/search` body `{ query, ids:[], mode:"keyword"|"semantic"|"hybrid", limit:20 }`,
permission `{module}:...:search`. A `ensure_{entity}_embeddings(db, user, ids)` service backfills missing
embeddings before a semantic/hybrid run. The main list endpoint also supports `?q=` as a keyword shortcut.

## A5. RBAC — declare → seed → protect (every route, no exceptions)

Authorization is RBAC permissions, **not** the legacy `users.role` column. Existing helpers in `deps.py`:
`get_current_user`, `require_permission(name)`, `require_permissions(*names)`, `get_user_permissions(user)`.
Models live in `Models/rbac.py`; seeding pattern in `db/seed_rbac.py`.

Naming: `{module}:{sub-resource}:{action}` (3 parts) or `{module}:{action}` (2 parts). Standard actions
only: `read, create, update, delete, search, ask, approve, manage, summary, use` (and `close`/`import`
where listed). Steps for every module:

1. **Declare** permissions in `{module}/permissions.py` as `(name, resource, action, description)` tuples.
2. **Seed** them in the module's Alembic migration (`get_or_create_permission` in `upgrade()`).
3. **Protect** every route with `Depends(require_permission("{module}:{action}"))` — even read-only
   list/detail endpoints require `{module}:...:read`.
4. **Cross-module Celery tasks run as system** (no `require_permission` inside the task); the dispatching
   route verifies the user's permission before dispatching.

## A6. Celery — heavy work + the task standard (Rule 10)

Any operation > ~200ms (embedding generation, PDF/image processing, STT, report/export generation, bulk
import) goes to Celery. The route returns **`202 Accepted` + `task_id`**; the caller polls
`GET /tasks/{task_id}`. Every task:

```python
@app.task(bind=True, max_retries=3, default_retry_delay=60, acks_late=True, reject_on_worker_lost=True)
def my_task(self, ...):
    try:
        ...  # work
        TaskResult.mark_done(task_id, result)
    except (TransientError, ConnectionError) as exc:
        raise self.retry(exc=exc)
    except Exception as exc:
        TaskResult.mark_failed(task_id, str(exc)); raise
```

The dispatching route writes the initial `TaskResult` row (`status=queued`) atomically with dispatch so
the poller never 404s. A daily Beat job deletes `TaskResult` rows older than 30 days.

## A7. Migrations, errors, logging, naming, audit

- **Alembic owns the schema.** Never `Base.metadata.create_all()` in request/startup code.
- **Register every model in `backend/Models/__init__.py`** or autogenerate silently skips its table.
- **Each module owns its migrations** — never mix two modules in one revision. Create root tables before
  leaf tables; defer circular FKs; match the constraint naming in `db/base.py`; review autogenerated
  migrations by hand. A cross-schema FK is created in the revision of the module that owns the
  *referencing* table.
- **Fresh DB →** `alembic upgrade head`. **DB that already has the schema →** `alembic stamp --purge head`.
- **Raise only catalogued errors** from `core/exceptions/error_codes.py` (`INTERNAL_SERVER_ERROR` is the
  only uncatalogued case) — never bare `HTTPException` with ad-hoc text.
- **Structured JSON logging** (§A built in Phase 0, see Module 0.4): one configured logger, `request_id`
  propagated web→Celery, context (`user_id`, `company_id`, route, latency); no secrets/PII; no `print()`.
- **Audit log** (business): every write logs `user_id, action, entity_type, entity_id, old→new, timestamp`.
- **Naming:** folder `snake_case`; model `PascalCase`; table `snake_case` plural; route `kebab-case`;
  schema `PascalCase`+suffix; service `verb_noun()`; number series `MODULE-YEAR-NNNN` (`PO-2026-0001`).
- **Routes have no `/api/` or version prefix in Phases 0–3** (added in Phase 4).
- **Backward compatibility is mandatory** — new columns on existing tables are nullable/defaulted; flag any
  breaking change to the owner before building it.

## A8. Definition of done for any module

- [ ] All the module's tables in its own schema; registered in `Models/__init__.py`.
- [ ] Cross-module access via **service functions only** — no import of another module's models/routes/schemas.
- [ ] Cross-module references are **real FKs in the shared DB** (resolved via the owning module's service);
      soft refs only at a designated split-seam.
- [ ] Cross-module **writes go through Celery events**.
- [ ] Money fields use the 4-column rule; shared types in `backend/shared/`.
- [ ] Own `search/` subfolder; `/ask` endpoint; `?q=` shortcut.
- [ ] Permissions declared in `{module}/permissions.py` + seeded in migration + every route protected.
- [ ] Heavy work in Celery (202 + task_id); tests (pytest) + `alembic check` pass.

---

# PART B — Phase 0 modules (build in this order)

| Order | Module | What gets built |
|---|---|---|
| 1st | `shared/currency/` | Currency + ExchangeRate tables, `/currencies` endpoints (must exist before money) |
| 2nd | `purchase_management/` | PurchaseOrder + Phases + Items + Costs + ReceiptLinks (deletes `buying_management`) |
| 3rd | Celery foundation | `TaskResult` model + `GET /tasks/{task_id}` + STT moved to Celery |
| — | Structured logging | Cross-cutting (§4.5) — stand it up alongside the above |
| 4th | Phase 0-R | Financial summary dashboard + purchase KPIs (KPI/chart endpoints + export) |

> **Parallel AI track (separate developer):** build `backend/assistant/` per master plan §12. Not required
> for the backend modules below; out of scope for this file.

---

## Module 0.1 — `shared/currency/` (Multi-Currency Foundation — run FIRST)

Shared module, owned by no domain module. Implements the §A3 money rule's backing tables.

**Models** (`shared/currency/models.py`):

```
Currency (table: currencies)
  - code: VARCHAR(10) unique (ISO 4217: USD, EUR, IRR, IRT, AED, IQD, CNY, GBP, TRY, ...)
  - name, symbol, decimal_places (INT — USD=2, IRR=0), is_active (Boolean)
  - Pre-populate (seed in migration): IRT, IRR, USD, AED, IQD, CNY  (+ EUR, GBP, TRY)

ExchangeRate (table: exchange_rates)
  - from_currency_id FK → currencies.id
  - to_currency_id   FK → currencies.id
  - rate: Numeric(28, 10)
  - effective_date (DATE) — valid from this date; use closest rate ≤ transaction date
  - source: 'manual' | 'api'
  - created_by_user_id, created_at

Company (existing model) — add nullable base_currency_id FK → currencies.id  (backward compatible)
```

**Services** (`shared/currency/services.py`):
- `get_rate(db, from_code, to_code, on_date) -> Decimal` — closest rate ≤ `on_date`.
- `convert(db, amount, from_code, to_code, on_date) -> Decimal`.

**Endpoints** (`shared/currency/routes.py`, registered additively in `api.py`):
- `GET  /currencies` — list active currencies — `currencies:read`
- `POST /currencies` — create currency (admin) — `currencies:manage`
- `GET  /currencies/exchange-rates` — list rates (filter from/to/date range) — `exchange_rates:read`
- `POST /currencies/exchange-rates` — add a rate (finance role) — `exchange_rates:create`

**Permissions** (`shared/currency/permissions.py`):
```
currencies:read        currencies       read     View currencies and exchange rates
currencies:create      currencies       create   Add a currency
currencies:manage      currencies       manage   Manage currencies (admin only)
exchange_rates:create  exchange_rates   create   Enter an exchange rate
exchange_rates:read    exchange_rates   read     View exchange rate history
```

**Migration:** new `currencies` + `exchange_rates` tables; nullable `companies.base_currency_id`; seed the
currency rows + permissions. **Impact: no existing table/endpoint changed except the nullable Company FK.**

**Frontend:** currency settings page, exchange-rate entry, rate-history view.

---

## Module 0.2 — `purchase_management/` (Clean rewrite — run SECOND)

**Decision: delete `buying_management` entirely** (folder, tables, routes — no other team depends on it).
Build `purchase_management` fresh under prefix `/purchase/`. Depends on `shared/currency/` (run first).

**Do NOT replicate the old bugs:** the old `BuyingProcessItem` linked PO lines directly to a
`ManagedModel`; PO lines are **Items** (material/spare/consumable), and `Item.model_id` is *optional*. The
old `affects_warehouse` boolean is wrong — warehouse interaction is a **Celery event**, not a flag.

**Models:**

```
PurchaseOrder (purchase_orders)
  - id, reference_number (auto: PO-2026-0001), title, description
  - supplier_id  (nullable; plain INTEGER in Phase 0 because the Supplier module does not exist yet —
                  becomes a real FK → supplier_management.suppliers.id in Phase 1, resolved via the
                  supplier_management service, no model import; §0.5)
  - supplier_name (VARCHAR — free-text fallback for Phase 0 before the Supplier module exists)
  - currency_id FK → currencies.id, base_currency_id FK → currencies.id, exchange_rate_used (28,10)
  - status: draft | ordered | shipped | received | closed | cancelled
  - approval_status: draft | pending | approved | rejected
  - description_embedding (Vector 1024, nullable — semantic search)
  - created_by_user_id, approved_by_user_id, created_at, updated_at

PurchasePhase (purchase_phases)   [one PO has 1..N phases; a phase = one physical delivery batch]
  - id, purchase_order_id FK → purchase_orders.id (same module)
  - phase_number, title, description
  - status: draft | ordered | shipped | received | closed
  - currency_id FK → currencies.id (inherits from PO if null), exchange_rate_used
  - expected_delivery_date, actual_delivery_date, created_at, updated_at
  NOTE: approval gates live on PurchaseOrder.approval_status, NOT on phases.

PurchasePhaseItem (purchase_phase_items)   [Item rows: material/spare/consumable]
  - id, phase_id FK → purchase_phases.id (same module)
  - item_name (VARCHAR — free text in Phase 0; in Phase 1 add item_id FK → material_management.items in
               the shared DB, resolved via the material_management service — do not import its model; §0.5)
  - item_code (VARCHAR nullable — SKU/part number)
  - quantity (Numeric), unit (VARCHAR: "pcs","kg","m","L")
  - unit_price, currency_id FK, unit_price_base, base_currency_id FK, exchange_rate_used
  - line_total, line_total_base, notes

PurchaseOrderCost (purchase_order_costs)   [freight/customs/tax/insurance/other]
  - id, purchase_order_id FK → purchase_orders.id
  - cost_type, description, amount, currency_id FK, amount_base, base_currency_id FK, exchange_rate_used
  - allocation_method: per_item | per_value | manual

PurchaseOrderReceiptLink (purchase_order_receipt_links)
  - id, purchase_order_id FK → purchase_orders.id
  - financial_receipt_id FK → financial_management.financial_receipts.id (shared DB) — resolve the receipt
    via the financial_management SERVICE, never import its model; §0.5 (real FK for integrity, clean seam)
  - linked_at, linked_by_user_id
```

**Endpoints (prefix `/purchase/`):** create/list/detail/update/soft-delete PO; `PATCH .../approval`
(submit/approve/reject); add/list/update phases; add/update phase items; add costs; add receipt-links;
`POST /purchase/orders/search` (keyword|semantic|hybrid); `GET .../summary` (totals by currency + base).
Every route protected (§A5).

**Cross-module write (warehouse):** when a phase reaches `received`, **emit a Celery event**
(`notify_warehouse_of_receipt.delay(phase_id=...)`); the warehouse module (Phase 1) handles it and reads
phase items via the purchase service. No direct model imports.

**Search:** `purchase_management/search/` — keyword ILIKE on `reference_number, supplier_name, title,
description`; semantic on `description_embedding`; merge by `purchase_order_id`.

**Permissions** (`purchase_management/permissions.py`):
```
purchase_management:orders:read     ... read     View purchase orders
purchase_management:orders:create   ... create   Create purchase orders
purchase_management:orders:update   ... update   Edit purchase orders
purchase_management:orders:delete   ... delete   Delete/cancel purchase orders
purchase_management:orders:approve  ... approve  Approve or reject purchase orders
purchase_management:orders:search   ... search   Search purchase orders
purchase_management:orders:ask      ... ask      Ask AI about purchase orders
purchase_management:phases:manage   ... manage   Create/update delivery phases
purchase_management:costs:manage    ... manage   Add/update additional costs
purchase_management:summary         ... summary  View procurement totals
```

**Migration:** drop `buying_*` tables; create the five `purchase_*` tables; seed permissions. Run AFTER
the currency migration (needs `currencies.id`). Cleanup: remove `buying_management` from
`Models/__init__.py`, delete the folder, repoint the router prefix `/buying/` → `/purchase/`.

**Frontend:** PO list (status/approval filters, search), PO detail (Phases | Costs | Payments | Summary
tabs), new-purchase form.

---

## Module 0.3 — Celery foundation (`TaskResult` + polling + STT async — run THIRD)

Moves heavy work to Celery **without changing route URLs or request bodies** (response shape changes from
sync result → `202 {task_id, status}` — acceptable, frontend not shipped yet).

- **`TaskResult`** (`Models/task_result.py`): `task_id (UUID), celery_task_id, task_type, status
  (queued/processing/done/failed), result_json (JSONB), error_message, created_by (user_id),
  created_at, updated_at`.
- **`GET /tasks/{task_id}`** (`routs/tasks.py`): returns `{task_id, status, result, error, created_at,
  updated_at}` (checks Celery state + the `TaskResult` row). Shared poller reused by every later module.
- **STT** (`routs/stt.py`): move transcription into `transcribe_audio_task(asset_id, user_id, language)`;
  route returns `202 + {task_id, status:"queued"}`. Follow the §A6 task standard.
- **Migration:** new `task_results` table (no existing data affected).

---

## Module 0.4 — Structured logging & observability (cross-cutting — build in Phase 0)

Technical logging (distinct from the business Audit Log). One configured logger emitting **structured JSON**
(levels DEBUG→CRITICAL, driven by env). Every request gets a `request_id` propagated through logs **and into
Celery tasks**; each line carries `request_id, user_id, company_id, route, latency, outcome`. Every
catalogued error and every 500 logs a stack trace + `request_id` (returned to the client). Celery tasks log
start/finish/retry/failure with the originating `request_id` + `TaskResult` id. No secrets/PII in logs.
Replaces ad-hoc `print()` / loose `logs/` usage.

---

# PART C — Phase 0-R: Financial Summary & Charts Dashboard (reporting sprint)

Ships at the end of Phase 0 (data already exists). Built on the shared chart-data convention (KPI cards +
chart-ready series) — the frontend reuses one set of chart components.

**Chart-data shape** (every report endpoint, params `?from=&to=&group_by=day|week|month&currency_id=`):
`GET /reports/{module}/{name}` → `{ chart_type, x:[...], series:[{name,data:[...]}], unit }` where
`chart_type ∈ line|bar|stacked_bar|pie|donut|gauge|table`. `GET /kpi/{module}` →
`[{ key, label, value, unit, trend }]` (5–8 cards).

**Financial dashboard endpoints (all in base currency, §A3):**
- `GET /kpi/financial` — total income, total expense, net cash position, receivables outstanding, MoM deltas.
- `GET /reports/financial/cashflow` — income vs expense over time → **line** (two series).
- `GET /reports/financial/by-category` — composition → **donut**.
- `GET /reports/financial/by-currency` — exposure per currency (original + base) → **stacked bar**.
- `GET /reports/financial/top-customers` — top counterparties by value → **horizontal bar**.
- `GET /reports/financial/receivables-aging` — buckets 0–30/31–60/61–90/90+ → **bar**.

**Purchase KPIs (Phase 0-R):** total open POs + combined value (base currency); avg PO-creation→received
time (trend); spend by currency MoM (grouped/stacked bar); POs by status (donut); top 5 suppliers by spend
(from `supplier_name`, upgrades to supplier FK in Phase 1).

**Export Engine note:** Phase 0-R may ship inline exports; the reusable `backend/shared/export/` service
(xlsx/csv/pdf, `POST /{module}/{entity}/export` → 202 + task_id) is **built once in Phase 1** and then used
everywhere. Wire the dashboard's Export button to it when available; until then, inline xlsx/pdf is fine.

**Permissions:** `financial:read` to view, `financial:export` to download (sensitive figures stay role-gated).

**Frontend (financial summary page):** row of KPI cards with trend chips; cashflow line (default last 12
months, `group_by=month`); category donut + currency stacked bar side by side; receivables-aging bar +
top-customers bar; filter bar (date range, currency) + Export to Excel/PDF.

---

# PART D — Build order & exit checklist

**Order:** currency → purchase_management → Celery foundation (+ logging alongside) → Phase 0-R dashboard.

**Phase 0 is done when:**
- [ ] `shared/currency/` live; `Company.base_currency_id` added; currencies seeded.
- [ ] `buying_management` deleted; `purchase_management` live under `/purchase/` with all 5 models,
      search, summary, and the warehouse-receipt **Celery event** (not a sync call).
- [ ] Every money field uses the 4-column rule; every cross-module ref is a real FK resolved via service
      (or the documented Phase-0 `supplier_id`/`item_name` free-text fallbacks).
- [ ] `TaskResult` + `GET /tasks/{task_id}` live; STT returns 202 + task_id.
- [ ] Structured JSON logging with `request_id` across web + Celery.
- [ ] Phase 0-R financial + purchase KPI/chart endpoints + summary page.
- [ ] Every route permission-protected and seeded; all models in `Models/__init__.py`; `pytest` +
      `alembic check` green.

**Cross-module reference summary (Phase 0):**

| Reference | Final state |
|---|---|
| `PurchasePhaseItem.item_id` | free-text `item_name` in Phase 0 → FK → `items` in Phase 1 (resolve via material_management service) |
| `PurchaseOrderReceiptLink.financial_receipt_id` | **real FK** → `financial_receipts`, resolve via financial_management service |
| `PurchaseOrder.supplier_id` | nullable plain int in Phase 0 (Supplier not built) → real FK in Phase 1; `supplier_name` free-text fallback |
| `currency_id` / `base_currency_id` | FK → `currencies` (everywhere money appears) |
