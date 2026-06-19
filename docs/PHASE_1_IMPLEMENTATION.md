# PHASE 1 — Commerce & Warehouse (Supplier · Material Master · Procurement · Warehouse · Export Engine)

> **Implementer: read only this file for Phase 1.** It is self-contained — Part A embeds every shared rule;
> Part B is the full spec for every Phase 1 module. Build modules in the order in §B. Stack:
> **FastAPI + PostgreSQL + pgvector + SQLAlchemy + Alembic + Celery** (one shared DB).
>
> **Assumes Phase 0 is complete:** `shared/currency/` (Currency + ExchangeRate, 4-field money rule),
> `purchase_management/` (PurchaseOrder + Phases under `/purchase/`), the `TaskResult` + `GET /tasks/{id}`
> Celery poller, and structured logging all exist. Phase 1 builds the catalog + procurement + warehouse
> around the Phase-0 PurchaseOrder and upgrades Phase-0 free-text refs to real FKs.

---

# PART A — Shared standards (every module in every phase follows these)

## A1. Architecture: modular monolith, one shared database, FK-as-default

One deployable FastAPI process, **one shared PostgreSQL database**. Each feature area is its own
folder/module with its own Postgres **schema** (for organization). Modular monolith designed to be split
into services later — a deliberate, last-resort migration, not the default posture.

**Foreign keys are the default — including across module schemas.** We want the database to enforce
referential integrity (no orphan rows, no hand-written "does this id exist?" checks, safe cascades). FKs
and JOINs across module schemas in this one shared DB are **allowed and preferred**.

**Divisibility comes from clean code seams, NOT from removing FKs.** The four seam rules (always):

1. **No cross-module imports of another module's internals.** Never import another module's SQLAlchemy
   **models**, **route functions**, or **Pydantic schemas**. You may declare a cross-schema
   `ForeignKey("other.table.id")` column — but you resolve/display that row by calling the owning module's
   **service function**, never by importing its model or `relationship()`-ing into it.
2. **Reads from another module go through its service functions** (in-process today; same call behind an
   HTTP client if the module is ever extracted). Routes are not the service API.
3. **Cross-module writes go through Celery events.** When module A must cause a write in module B (e.g. a
   posted GRN creating a stock movement), A publishes a Celery event; B's handler does the write.
4. **Shared types live in `backend/shared/`** — enums, constants, money helpers, common exceptions.

**Soft references are NOT the default.** A soft reference (plain `INTEGER`, no FK, existence validated in
code) is used **only at a seam deliberately designated for physical extraction**. Do **not** add
pre-emptive denormalized snapshot columns — denormalize only at extraction time. `purchase_management` is
the reference pattern (links a financial receipt by id with no import of `financial_management.models`).

> Full standard: master plan §0.5; everyday version in `docs/KEEP_IN_MIND.md`; canonical rules in `AGENTS.md`.

## A2. Glossary (canonical term meanings — do not redefine)

| Term | Meaning |
|---|---|
| **model** (`model_management.ManagedModel`) | An **equipment-model type** (manufacturer + model name + specs). NOT an AI/ML model, NOT stock. |
| **item** (`material_management.Item`) | A **stockable thing** (material/spare/consumable/tool/chemical/PPE). The universal warehouse/PO line entity. Optional nullable `item.model_id`. |
| **tag** (`tag_management`) | A **functional position in the process** (P&ID tag). |
| **asset** (`asset_management.Asset`, Phase 2) | A **physical installed unit** with a serial; references its model via `asset.model_id`. |
| **stock** (`StockItem`) | The **on-hand quantity of an item at a location**. Always points at `item_id`, never directly at a model. |

Phase 1 introduces the **Item** catalog, so Phase-0 free-text `item_name` on purchase lines is upgraded to
a real `item_id` FK → `items`.

## A3. Multi-currency — the 4-field money rule

Every monetary amount uses **four columns**: `amount`, `currency_id` **FK → `currencies.id`**, `amount_base`
(company base currency), `exchange_rate_used` (Numeric 28,10, frozen at transaction time). Company base
currency on `Company.base_currency_id`. Dashboards aggregate in base currency. Rounding follows
`currency.decimal_places`. Applies in Phase 1 to: GRN landed cost, supplier evaluation price comparison,
inventory valuation (weighted-average cost always stored with currency).

## A4. Standard search pattern (every searchable module)

Each module ships a `search/` subfolder (`repository.py`/`service.py`/`routes.py`) modelled on
`financial_management/search/`:

- **Keyword** — `ILIKE '%query%'` across text columns (NOT `tsvector`).
- **Semantic** — pgvector `<=>` on `embedding = Column(Vector(1024))` (Jina). Migration needs
  `import pgvector.sqlalchemy` + `CREATE EXTENSION IF NOT EXISTS vector`.
- **Hybrid** — run both, merge + dedupe by id; graceful fallback to keyword if embeddings fail.

Endpoint `POST /{module}/search` body `{query, ids:[], mode, limit}`, permission `{module}:...:search`;
`ensure_{entity}_embeddings()` backfills before semantic runs; list endpoints support `?q=`.

## A5. RBAC — declare → seed → protect

RBAC permissions (not `users.role`). Helpers in `deps.py`; models in `Models/rbac.py`; seed pattern in
`db/seed_rbac.py`. Naming `{module}:{sub-resource}:{action}` or `{module}:{action}`; actions only
`read, create, update, delete, search, ask, approve, manage, summary, use, close, import`. Per module:
**declare** in `{module}/permissions.py` → **seed** in the migration → **protect** every route with
`Depends(require_permission(...))` (even reads). Cross-module Celery tasks run as system; the dispatching
route checks permission first.

## A6. Celery — heavy work + task standard

Work > ~200ms → Celery; route returns `202 + task_id`; poll `GET /tasks/{task_id}` (built in Phase 0). Every
task uses `bind=True, max_retries=3, default_retry_delay=60, acks_late=True, reject_on_worker_lost=True`,
writes a `TaskResult` row (`done`/`failed`) before exit, retries transient errors. The dispatching route
writes the initial `queued` row atomically. Daily Beat job prunes `TaskResult` > 30 days.

## A7. Migrations, errors, logging, naming, audit

- **Alembic owns the schema**; never `create_all()` at runtime. **Register every model in
  `Models/__init__.py`.** Each module owns its migrations (never mix two modules in one revision); root
  tables before leaf; defer circular FKs; match `db/base.py` constraint naming; review by hand. A
  cross-schema FK is created in the revision of the module owning the *referencing* table.
- Fresh DB → `alembic upgrade head`; existing schema → `alembic stamp --purge head`.
- **Raise only catalogued errors** from `core/exceptions/error_codes.py`.
- **Structured JSON logging** with `request_id` across web + Celery (Phase 0).
- **Audit log:** every write logs `user_id, action, entity_type, entity_id, old→new, timestamp`.
- **Naming:** folder `snake_case`; model `PascalCase`; table `snake_case` plural; route `kebab-case`;
  number series `MODULE-YEAR-NNNN`. No `/api/`/version prefix in Phases 0–3.
- **Backward compatibility mandatory** — new columns nullable/defaulted; flag breaking changes first.

## A8. Definition of done for any module

All tables in own schema + registered; cross-module access via service functions only; cross-module refs
are real FKs resolved via service (soft ref only at a designated split-seam); cross-module writes via
events; money uses 4 columns; shared types in `backend/shared/`; own `search/` + `/ask` + `?q=`; permissions
declared + seeded + every route protected; heavy work in Celery; `pytest` + `alembic check` green.

---

# PART B — Phase 1 modules (build in this order)

| Order | Module | Key entities |
|---|---|---|
| 1 | `supplier_management` | Supplier, Contact, Category, Document, Evaluation |
| 2 | `material_management` | Item (Material Master), ItemCategory, Unit, ItemAlternative, ItemDocument |
| 3 | `requisition_management` | MaterialRequisition (MR), MRItem, approval workflow |
| 4 | `rfq_management` | RFQ, RFQSupplier, RFQItem, QuotationResponse, QuotationResponseItem |
| 5 | `goods_receipt_management` | GoodsReceiptNote (GRN), GRNItem, link to PO/PurchasePhase |
| 6 | `warehouse_management` | Warehouse, Zone, StorageLocation, StockItem, StockMovement, StockCount |
| 7 | `shared/export/` + Phase 1-R | Export Engine (build once) + inventory/procurement dashboards |

> **PO note:** the **PurchaseOrder header was created in Phase 0** (`purchase_management`, `/purchase/`).
> Phase 1 wires the procurement workflow **MR → RFQ → (PO) → GRN** around it and upgrades Phase-0 free-text
> refs (`item_name`, `supplier_id`) to real FKs. PO line items resolve to the new `Item` catalog and the
> new `Supplier`. Treat PO as already existing; do not rebuild its header.
>
> **Parallel AI track:** register supplier/material/requisition/RFQ/GRN/warehouse tool sets into the
> Assistant Core (master plan §12). Out of scope for this file.

---

## Module 1.1 — `supplier_management/` (run FIRST)

Central registry of vendors and their performance.

**Models:**
```
Supplier            - code (auto SUP-001), name, type (Local/International/Manufacturer/Distributor),
                      country, city, address, tax_id, website, status (Pending/Approved/Blacklisted),
                      notes, description_embedding (Vector 1024)
SupplierContact     - supplier_id FK → suppliers.id, name, email, phone, position, is_primary
SupplierCategory    - supplier_id FK → suppliers.id, category_name (what they supply; many-to-many)
SupplierDocument    - supplier_id FK → suppliers.id, file_asset link, document_type
                      (Contract/NDA/Catalog/Certificate/License)   [uses existing file_assets]
SupplierEvaluation  - supplier_id FK → suppliers.id, evaluated_by, date,
                      delivery_score, quality_score, price_score (0-10), total_score (avg), notes
SupplierPerformance - derived from PO history (total_orders, on_time_rate, rejection_rate) — nullable,
                      populated once procurement data exists
```
All inter-table FKs here are **same-module** (real FKs).

**Endpoints:** supplier CRUD (list with `?q=` + `?status=`), contacts, categories, documents, evaluations,
`POST /suppliers/search`, `/suppliers/ask`. **Search:** keyword on name/country/category + semantic.

**Permissions:** `supplier_management:{read,create,update,delete,search,ask}`.

**Frontend:** supplier list, profile, evaluation form, document tab.

---

## Module 1.2 — `material_management/` (Item / Material Master — run SECOND)

The universal `Item` catalog (the stockable entity for warehouse + every PO/MR/RFQ line).

**Models:**
```
ItemCategory   - tree (parent_id self-ref), code, name, description
Unit           - code (KG/L/PCS/M/BOX), name, unit_type (Mass/Volume/Length/Count/Area)
Item           - item_code (unique per company), name, description (indexed), category_id FK, unit_id FK,
                 specs (JSONB), barcode, qr_code,
                 item_type: Material/Spare Part/Consumable/Tool/Chemical/PPE,
                 is_active, is_critical, lead_time_days, description_embedding (Vector 1024)
               - model_id FK → model_management.managed_models.id (shared DB), NULLABLE — resolve via the
                 model_management SERVICE, do not import its model (§0.5): set for equipment/model-specific
                 spares, NULL for generic materials (glue, grease, bolts). Item is the universal stock
                 entity; ManagedModel is the equipment-model catalog it optionally references (Glossary).
                 manufacturer/model_name for display come from the model — ask the model_management
                 service (JOIN allowed in the shared DB). Do NOT add pre-emptive snapshot columns.
ItemAlternative - item_id FK → items.id (same module), alt_code, alt_name,
                  supplier_id FK → supplier_management.suppliers.id (shared DB — resolve via the supplier
                  service, no model import; §0.5)
ItemDocument   - item_id FK → items.id, file_asset link (datasheets, SDS)
```

**Endpoints:** item CRUD (pagination + `?q=` + `?category=` + `?item_type=`), category tree, alternatives,
documents, `POST /materials/search`, `/materials/ask`, **Excel bulk import (Celery task** → 202 + task_id).
**Search:** keyword on item_code/name/description/specs + semantic.

**Permissions:** `material_management:{read,create,update,delete,search,ask,import}`.

**Frontend:** item list (filters), item detail, category tree, bulk-import screen.

**Phase-0 upgrade:** add `PurchasePhaseItem.item_id` FK → `items` (keep `item_name` for legacy rows),
resolved via this module's service.

---

## Module 1.3 — `requisition_management/` (Material Requisition — run THIRD)

**Workflow:** `MR → RFQ → QuotationResponse → PurchaseOrder → GRN → StockMovement IN`. This module covers MR.

**Models:**
```
MaterialRequisition - mr_number (auto MR-2026-0001), requested_by (user), department_id,
                      needed_by_date, reason, priority (Normal/Urgent/Critical),
                      status: Draft/Submitted/Under Review/Approved/Rejected/Ordered/Closed, notes
MRItem              - mr_id FK → material_requisitions.id (same module),
                      item_id FK → material_management.items.id (shared DB — resolve via the
                      material_management service, no model import; §0.5),
                      quantity, unit_id, estimated_unit_cost (optional), currency_id FK, notes
```
**Approval state machine:** Draft→Submitted (requester); Submitted→Approved/Rejected (dept_head or
procurement_officer); Approved→Ordered (when a PO is created from it).

**Endpoints:** MR CRUD + state transitions + search. **Permissions:**
`requisition_management:{read,create,update,delete,approve,search}`.
**Frontend:** MR form, MR approval inbox.

---

## Module 1.4 — `rfq_management/` (RFQ + Quotations — run FOURTH)

**Models:**
```
RequestForQuotation   - rfq_number (auto RFQ-2026-0001), mr_id (optional, FK → material_requisitions.id),
                        title, description, deadline_date, status: Draft/Sent/Closed/Cancelled
RFQSupplier           - rfq_id FK → rfqs.id, supplier_id FK → supplier_management.suppliers.id (shared DB —
                        resolve via the supplier service, no model import; §0.5), sent_at, response_status
RFQItem               - rfq_id FK → rfqs.id, item_id FK → material_management.items.id (shared DB — resolve
                        via the material_management service, no model import; §0.5), quantity, unit_id,
                        specifications (text)
QuotationResponse     - rfq_id FK → rfqs.id, supplier_id FK → supplier_management.suppliers.id (shared DB —
                        resolve via the supplier service, no model import; §0.5), received_at, valid_until,
                        payment_terms, delivery_days, notes
QuotationResponseItem - response_id FK → quotation_responses.id, rfq_item_id FK → rfq_items.id,
                        unit_price, currency_id FK, unit_price_base, exchange_rate_used, lead_time_days, notes
```
**Endpoints:** RFQ CRUD + state transitions; quotation responses; **RFQ comparison endpoint** (all supplier
responses side-by-side for one RFQ); search. **Permissions:**
`rfq_management:{read,create,update,delete,approve,search}` (`approve` = select winning quotation).
**Frontend:** RFQ form, supplier quotation comparison table.

---

## Module 1.5 — `goods_receipt_management/` (GRN — run FIFTH)

What actually arrived against a PO (and, in Phase 0 terms, a PurchasePhase). Posting a GRN creates stock.

**Models:**
```
GoodsReceiptNote - grn_number (auto GRN-2026-0001),
                   po_id FK → purchase_orders.id (shared DB — resolve via the purchase service, no model
                   import; §0.5). NOTE: equivalently links to PurchasePhase (FK → purchase_phases.id).
                   received_by (user), receipt_date, delivery_note_number,
                   status: Draft | Posted (posted = finalised, creates movements),
                   warehouse_id FK → warehouse_management.warehouses.id (shared DB — resolve via the
                   warehouse service, no model import), notes
GRNItem          - grn_id FK → goods_receipt_notes.id (same module), po_item_id (FK → po line),
                   item_id FK → material_management.items.id (shared DB — resolve via the material service,
                   no model import; §0.5), received_quantity, accepted_quantity, rejected_quantity,
                   rejection_reason, storage_location_id FK → warehouse_management.storage_locations.id
                   (shared DB — resolve via the warehouse service)
```
**On GRN POST (status → Posted):** **emit a Celery event** that the warehouse module handles by creating a
`StockMovement RECEIPT` for each accepted GRNItem (cross-module write = event, §A1 — **not** a synchronous
call into warehouse). Event payload carries the GRN id; the warehouse handler reads accepted items via this
module's service. Partial delivery: one PO → multiple GRNs; PO line `received_quantity` and PO status
(Partially/Fully Received) update on each post.

**Endpoints:** GRN CRUD + `post` action + search. **Permissions:**
`goods_receipt_management:{read,create,update,approve,search}`. **Frontend:** GRN entry screen, receiving
dashboard.

---

## Module 1.6 — `warehouse_management/` (Locations + Stock — run SIXTH)

Built after procurement so GRN → StockMovement integration is immediately usable. Supersedes the old
`property_management` warehouse skeleton.

**Models:**
```
Warehouse        - code, name, type (Main/Secondary/Field/Transit), location/address, manager_id
Zone             - warehouse_id FK → warehouses.id, code, name, description
StorageLocation  - zone_id FK → zones.id, code, name, capacity_unit, capacity_value, is_active   (shelf/bin)
StockItem        - one row per item per location (current state):
                   item_id FK → material_management.items.id (shared DB — resolve via the material service,
                   no model import; §0.5); storage_location_id FK → storage_locations.id (same module).
                   item_code/item_name for display come from the item — ask the material service (JOIN
                   allowed). Stock anchors to item_id, NEVER directly to a model; equipment make/model is
                   reached via the item's optional model (Glossary). Do NOT add pre-emptive snapshot columns.
                   quantity_on_hand, quantity_reserved, quantity_available (on_hand - reserved),
                   min_level, max_level, reorder_point,
                   unit_cost, unit_cost_currency_id (weighted avg), unit_cost_base
StockMovement    - append-only (never update/delete): movement_number (MOV-2026-00001),
                   movement_type: RECEIPT/ISSUE/TRANSFER_OUT/TRANSFER_IN/ADJUSTMENT/RETURN/COUNT_ADJUSTMENT,
                   item_id FK → material_management.items.id (shared DB — resolve via material service),
                   from_location_id (nullable), to_location_id (nullable) FK → storage_locations.id,
                   quantity (positive), unit_cost, currency_id, unit_cost_base, exchange_rate_used,
                   reference_type: GRN/WORK_ORDER/MANUAL/STOCK_COUNT, reference_id (polymorphic — plain id),
                   performed_by, movement_date, notes
StockCount       - count_number (auto), warehouse_id FK → warehouses.id, status (Open/In Progress/Posted),
                   performed_by
StockCountLine   - count_id FK → stock_counts.id (same module),
                   item_id FK → material_management.items.id (shared DB — resolve via material service),
                   location_id FK → storage_locations.id, system_quantity, counted_quantity, variance
                   - on post: auto-create COUNT_ADJUSTMENT StockMovements for variances
```

**Business logic:** when a **GRN-posted Celery event** arrives (from procurement), create the RECEIPT
StockMovements here (the handler reads accepted items via the procurement service); prevent ISSUE if
`quantity_available < requested`; recompute weighted-average cost on each RECEIPT; daily Celery task flags
items at/below `reorder_point` → notification.

**Migration of old data:** existing `property_management.WarehouseItem.model_id` (NOT NULL → managed_models)
→ create an `Item` per warehouse row carrying its model into `Item.model_id`, repoint stock to `item_id`
(real FK → items), and drop the old stock→model link and `relationship("ManagedModel")` so stock reaches a
model only through the item. The `color`-based uniqueness key → item + storage location (+ lot/batch).

**Endpoints:** locations CRUD; stock by location; movement history; low-stock list; `POST
/warehouse/items/search`; `/warehouse/ask`. **Permissions:**
`warehouse_management:{locations:read, locations:manage, stock:read, stock:manage, movements:read,
movements:create, search, summary}`. **Frontend:** warehouse map/tree, item stock view, movement history,
stock-count screen.

---

## Module 1.7 — `shared/export/` Export Engine (build once — used by Phase 1-R onward)

One shared service so every module gets xlsx/csv/pdf export for free. Lives in `backend/shared/export/`.

- **Three formats, one contract:** xlsx (openpyxl — header styling, frozen header, column widths,
  currency formatting), csv (UTF-8 BOM), pdf (server-side HTML→PDF: title block, logo, applied filters).
- **Endpoint pattern** every module mounts next to its list/search:
  `POST /{module}/{entity}/export` body `{format, filters, columns}` → **202 + {task_id}** (runs in Celery;
  reuse the Phase-0 `GET /tasks/{task_id}` poller; result stored as a short-lived `FileAsset` download_url).
  Small exports (<~1k rows) may return inline. `filters`/`columns` reuse the module's search request schema —
  export === "run this search, then serialize".
- **RBAC:** export requires `{module}:read` plus a separate seeded `{module}:export` permission. Every export
  is audit-logged.

---

# PART C — Phase 1-R: Inventory & Procurement dashboards (reporting sprint)

Chart-data convention (same as every phase): `GET /kpi/{module}` → `[{key,label,value,unit,trend}]`;
`GET /reports/{module}/{name}` → `{chart_type, x, series:[{name,data}], unit}` with params
`?from=&to=&group_by=&currency_id=`. Each summary page = KPI cards + charts + filter bar + Export button
(wired to the Export Engine).

**What managers see (Phase 1-R):** inventory levels, low-stock alerts, procurement cycle time (MR→PO→GRN),
spend by supplier, stock valuation (base currency), GRN-vs-PO variance. Suggested charts: stock value over
time → line; spend by supplier → horizontal bar; procurement cycle time → bar; low-stock list → table/KPI.

**Permissions:** `warehouse_management:summary`, `purchase_management:summary`, plus per-module `:export`.

---

# PART D — Build order & exit checklist

**Order:** supplier → material → requisition → rfq → goods_receipt → warehouse → export engine + Phase 1-R.

**Phase 1 is done when:**
- [ ] All six domain modules live, each with `search/`, `/ask`, permissions seeded, every route protected.
- [ ] `Item` catalog is the universal stock/line entity; `Item.model_id` nullable FK resolved via the
      model_management service; no module imports another module's models/routes/schemas.
- [ ] GRN-posted → stock movement is a **Celery event**; warehouse handler reads via the procurement service.
- [ ] Phase-0 upgrades applied: `PurchasePhaseItem.item_id` FK → `items`; `PurchaseOrder.supplier_id` real
      FK → `suppliers`; old `property_management` warehouse data migrated to `Item` + `item_id`.
- [ ] `shared/export/` live; Phase 1-R KPI/chart endpoints + summary pages with Export.
- [ ] Every money field uses the 4-column rule; `pytest` + `alembic check` green.

**Cross-module reference summary (Phase 1):**

| Reference | Final state |
|---|---|
| `Item.model_id` | FK → `managed_models`, NULLABLE, resolve via model_management service |
| `ItemAlternative.supplier_id` | FK → `suppliers`, resolve via supplier service |
| `MRItem.item_id`, `RFQItem.item_id` | FK → `items`, resolve via material service |
| `RFQSupplier.supplier_id`, `QuotationResponse.supplier_id` | FK → `suppliers`, resolve via supplier service |
| `PO line → Item`, `PO → Supplier` | FK → `items` / `suppliers`, resolve via service |
| `GRN.po_id` / PurchasePhase | FK (shared DB), resolve via purchase service |
| `GRN.warehouse_id`, `GRNItem.storage_location_id` | FK → warehouse tables, resolve via warehouse service |
| `StockItem.item_id`, `StockMovement.item_id`, `StockCountLine.item_id` | FK → `items`, resolve via material service |
| GRN-posted → StockMovement RECEIPT | **Celery event** (cross-module write) |
