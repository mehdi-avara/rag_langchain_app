# PHASE 2 — Maintenance & Admin (Asset · Work Order · PM · Inspection · Defect · Notification · KPI Dashboard)

> **Implementer: read only this file for Phase 2.** Part A embeds every shared rule; Part B is the full spec
> for every Phase 2 module. Build modules in the order in §B. Stack:
> **FastAPI + PostgreSQL + pgvector + SQLAlchemy + Alembic + Celery** (one shared DB).
>
> **Assumes Phase 0 + Phase 1 are complete:** `shared/currency/`, `purchase_management/`, the Celery
> `TaskResult` + `GET /tasks/{id}` poller, structured logging, the `Item` catalog (`material_management`),
> `warehouse_management` (StockItem/StockMovement), `supplier_management`, and the `shared/export/` Export
> Engine all exist. Phase 2 builds the maintenance loop on top of Assets, Items, and Stock.

---

# PART A — Shared standards (every module in every phase follows these)

## A1. Architecture: modular monolith, one shared database, FK-as-default

One deployable FastAPI process, **one shared PostgreSQL database**. Each module owns a Postgres **schema**
for organization. Modular monolith designed to be split into services later — a deliberate, last-resort
migration, not the default.

**Foreign keys are the default — including across module schemas** (DB-enforced integrity, no manual
existence checks, safe cascades). FKs and JOINs across schemas in this one shared DB are allowed and preferred.

**Divisibility comes from clean code seams, NOT from removing FKs.** The four seam rules (always):

1. **No cross-module imports of another module's internals** — never import its SQLAlchemy **models**, **route
   functions**, or **Pydantic schemas**. Declare a cross-schema `ForeignKey("other.table.id")` if you like,
   but resolve/display that row via the owning module's **service function**, never by importing its model.
2. **Reads go through service functions** (in-process today; HTTP client if ever extracted).
3. **Cross-module writes go through Celery events** (e.g. closing a WO auto-resolving a defect).
4. **Shared types live in `backend/shared/`.**

**Soft references are NOT the default** — used only at a seam deliberately designated for physical extraction;
no pre-emptive denormalized snapshot columns (denormalize only at extraction time). `purchase_management` is
the reference pattern (links a financial receipt by id with no import of `financial_management.models`).

> Full standard: master plan §0.5; everyday version in `docs/KEEP_IN_MIND.md`; canonical rules in `AGENTS.md`.

## A2. Glossary (canonical term meanings — do not redefine)

| Term | Meaning |
|---|---|
| **model** (`model_management.ManagedModel`) | An **equipment-model type** (manufacturer + model name + specs). NOT AI/ML, NOT stock. |
| **item** (`material_management.Item`) | A **stockable thing** (material/spare/consumable/tool/chemical/PPE). The universal stock/line entity; optional nullable `item.model_id`. |
| **tag** (`tag_management`) | A **functional position in the process** (P&ID tag). The central user-facing object in defect reporting. |
| **asset** (`asset_management.Asset`) | A **physical installed unit** (serial number, lifecycle/history); references its model via `asset.model_id`. |
| **stock** (`StockItem`) | On-hand quantity of an **item** at a location; points at `item_id`, never directly at a model. |

A Defect is raised against a **tag** (the central object), optionally linked to the failed **asset** under it.

## A3. Multi-currency — the 4-field money rule

Every monetary amount uses **four columns**: `amount`, `currency_id` **FK → `currencies.id`**, `amount_base`,
`exchange_rate_used` (Numeric 28,10, frozen). In Phase 2 this applies to work-order cost (labor + material in
base currency) on the maintenance dashboard.

## A4. Standard search pattern (every searchable module)

`search/` subfolder (`repository.py`/`service.py`/`routes.py`): **keyword** ILIKE on text columns (NOT
`tsvector`); **semantic** pgvector `<=>` on `embedding = Column(Vector(1024))` (Jina; migration needs
`import pgvector.sqlalchemy` + `CREATE EXTENSION IF NOT EXISTS vector`); **hybrid** = both merged + deduped by
id, graceful fallback to keyword. Endpoint `POST /{module}/search` `{query, ids:[], mode, limit}`, permission
`{module}:...:search`; `ensure_{entity}_embeddings()` backfills; list endpoints support `?q=`.

## A5. RBAC — declare → seed → protect

RBAC permissions (not `users.role`). Helpers in `deps.py`; models `Models/rbac.py`; seed `db/seed_rbac.py`.
Naming `{module}:{sub-resource}:{action}` / `{module}:{action}`; actions only `read, create, update, delete,
search, ask, approve, manage, summary, use, close, import`. Per module: **declare** in
`{module}/permissions.py` → **seed** in migration → **protect** every route (even reads). Cross-module Celery
tasks run as system; the dispatching route checks permission first.

## A6. Celery — heavy work + task standard

Work > ~200ms → Celery; `202 + task_id`; poll `GET /tasks/{task_id}` (Phase 0). Tasks use `bind=True,
max_retries=3, default_retry_delay=60, acks_late=True, reject_on_worker_lost=True`, write a `TaskResult`
(`done`/`failed`) before exit, retry transient errors; dispatching route writes the initial `queued` row.
**Celery Beat** is used in Phase 2 to auto-generate PM Work Orders from due schedules.

## A7. Migrations, errors, logging, naming, audit

- **Alembic owns the schema**; never `create_all()` at runtime. **Register every model in
  `Models/__init__.py`.** Each module owns its migrations (never mix two modules in one revision); root tables
  before leaf; defer circular FKs; match `db/base.py` naming; review by hand. A cross-schema FK is created in
  the revision of the module owning the *referencing* table.
- Fresh DB → `alembic upgrade head`; existing schema → `alembic stamp --purge head`.
- **Raise only catalogued errors** from `core/exceptions/error_codes.py`.
- **Structured JSON logging** with `request_id` across web + Celery; **audit log** on every write.
- **Naming:** folder `snake_case`; model `PascalCase`; table `snake_case` plural; number series
  `MODULE-YEAR-NNNN` (`WO-2026-0001`, `DEF-2026-0001`). No `/api/`/version prefix in Phases 0–3.
- **Backward compatibility mandatory** — new columns nullable/defaulted; flag breaking changes first.

## A8. Definition of done for any module

All tables in own schema + registered; cross-module access via service functions only; cross-module refs are
real FKs resolved via service (soft ref only at a designated split-seam); cross-module writes via events;
money uses 4 columns; shared types in `backend/shared/`; own `search/` + `/ask` + `?q=`; permissions declared
+ seeded + every route protected; heavy work in Celery; `pytest` + `alembic check` green.

---

# PART B — Phase 2 modules (build in this order)

| Order | Module | Key entities |
|---|---|---|
| 1 | `asset_management` | Plant, AssetSystem, Asset, AssetSpecification, AssetSpare, AssetDocument, AssetHistory |
| 2 | `work_order_management` | WorkOrder, Task, Labor, Material, Failure, Attachment + approval/close + MTTR |
| 3 | `pm_management` | MaintenancePlan, MaintenanceTask, TaskTrigger, PMSchedule (Celery Beat auto-gen) |
| 4 | `inspection_management` | InspectionChecklist, ChecklistItem (Pass/Fail/Measure), execution records |
| 5 | `defect_management` | DefectReport, DefectComment — "a tag has a problem; the asset under it failed" |
| 6 | Notification engine | cross-module event → bell/email routing (Celery) |
| 7 | Phase 2-R | Maintenance KPI dashboard (KPIs + charts + export) |

> **Employee is Phase 3.** Where Phase 2 needs a person on a work order, use a **nullable plain field /
> free-text fallback** now (same pattern as Phase 0 `supplier_name`); upgrade to a real FK → `hr.employees`
> in Phase 3. The acting `user_id` may still be a real FK → `platform.users`.
>
> **Parallel AI track:** register asset/WO/PM/inspection/defect tool sets into the Assistant Core (§12).
> Out of scope for this file.

---

## Module 2.1 — `asset_management/` (Equipment registry — run FIRST)

Hierarchy: `Plant → AssetSystem → Asset → Component (parent_asset_id)`.

**Models:**
```
Plant             - top level (Refinery/Platform/Pipeline)
AssetSystem       - functional system (Process/Utility/Fire&Gas/Instrument); plant_id FK → plants.id
Asset             - tag_number (unique, e.g. P-1001), name, description,
                    asset_type: Rotating/Static/Electrical/Instrument/Civil/Piping,
                    criticality: A/B/C, status: Active/Standby/Under Maintenance/Decommissioned,
                    model_id FK → model_management.managed_models.id (shared DB), nullable — resolve via the
                      model_management SERVICE, no model import (§0.5): the equipment-model type (manufacturer
                      + model live there, Glossary). manufacturer/model_number reached by asking the
                      model_management service (JOIN allowed), free-text fallback only if no ManagedModel
                      record exists yet. Do NOT add pre-emptive snapshot columns.
                    serial_number (the individual physical unit), installation_date, warranty_expiry,
                    parent_asset_id FK → assets.id (same module, sub-components),
                    asset_system_id FK → asset_systems.id, description_embedding (Vector 1024)
AssetSpecification - asset_id FK → assets.id, JSON key-value per asset type
AssetSpare        - asset_id FK → assets.id (same module),
                    item_id FK → material_management.items.id (shared DB — resolve via the material_management
                    service, no model import; §0.5)   [which items are spares for this asset]
AssetDocument     - asset_id FK → assets.id, file_asset link (manuals, P&IDs, drawings)
AssetHistory      - asset_id FK → assets.id, append-only lifecycle log (installed/modified/repaired/replaced)
```

**Endpoints:** asset CRUD + tree/hierarchy endpoint; specs; spares; documents; history; `POST
/assets/search`; `/assets/ask`. **Search:** keyword on tag_number/name/description/manufacturer + semantic.
**Permissions:** `asset_management:{read,create,update,delete,search,ask}`.
**Frontend:** asset tree view, asset detail, asset history.

---

## Module 2.2 — `work_order_management/` (the core of the CMMS — run SECOND)

Types: CM (corrective) / PM (preventive) / Inspection / Modification.
Lifecycle: `Draft → Submitted → Approved → Planned → In Progress → Completed → Closed` (+ Rejected, On Hold).

**Models:**
```
WorkOrder      - wo_number (auto WO-2026-0001), type, priority (Critical/High/Medium/Low),
                 asset_id FK → asset_management.assets.id (shared DB — resolve via the asset service, no
                 model import; §0.5), title, description, requested_by (user), assigned_to (user/team),
                 scheduled_start/end, actual_start/end, status (state machine),
                 source: Manual/PM Schedule, parent_pm_schedule_id (if from PM),
                 description_embedding (Vector 1024)
WorkOrderTask  - work_order_id FK → work_orders.id, checklist steps
WorkOrderLabor - work_order_id FK → work_orders.id, date, hours, craft_type,
                 employee_id — EMPLOYEE IS PHASE 3: nullable plain field / free-text fallback now (same
                 pattern as Phase-0 supplier_name); upgrade to FK → hr.employees in Phase 3. May record the
                 acting user_id as a real FK → platform.users.
WorkOrderMaterial - work_order_id FK → work_orders.id,
                 item_id FK → material_management.items.id (shared DB — resolve via the material service, no
                 model import; §0.5), planned_qty, actual_qty.
                 On actual_qty save: emit a Celery event that creates the StockMovement OUT in warehouse
                 (cross-module write = event, §A1).
WorkOrderFailure - work_order_id FK → work_orders.id (CM only): failure_code (ISO 14224), failure_cause,
                 corrective_action, root_cause
WorkOrderAttachment - work_order_id FK → work_orders.id, file_asset link (photos, reports)
```

**Logic:** approval (Draft → maintenance_supervisor approves → starts); material reservation in warehouse
before work starts (event); auto-calculate MTTR + downtime; close completed WOs. **Endpoints:** WO CRUD +
state-machine transition endpoints; tasks; labor; materials; failures; attachments; `POST
/work-orders/search`; `/work-orders/ask`. **Search:** keyword on wo_number/title/description/asset
tag/failure codes + semantic. **Permissions:**
`work_order_management:{read,create,update,delete,approve,close,search,ask,summary}`.
**Frontend:** WO list, WO detail, job-card print view, KPI widgets.

---

## Module 2.3 — `pm_management/` (Preventive Maintenance — run THIRD)

**Models:**
```
MaintenancePlan - plan_number (auto MP-2026-001), name, description,
                  asset_id FK → asset_management.assets.id (or asset_system_id FK → asset_systems.id for
                  grouped) — shared DB, resolve via the asset service, no model import (§0.5); is_active
MaintenanceTask - plan_id FK → maintenance_plans.id, task_name, description,
                  craft_type, estimated_hours,
                  required_items (list of item_id FK → material_management.items.id, shared DB — resolve via
                  the material service, no model import; §0.5)
TaskTrigger     - task_id FK → maintenance_tasks.id, trigger_type: CALENDAR (every N days) | METER (every N
                  hours/km/cycles), frequency_value, frequency_unit, last_done_date,
                  last_done_meter_reading, next_due_date (calculated)
PMSchedule      - plan_id FK → maintenance_plans.id, task_id FK → maintenance_tasks.id, due_date,
                  status: Pending/Generated/Overdue.
                  When status=Pending and due_date approaches: emit a Celery event that the
                  work_order_management module handles to create the WorkOrder (cross-module write = event,
                  §A1 — not a direct call into work_order).
InspectionChecklist (template) - belongs to MaintenanceTask; checklist_items (step, description,
                  response_type: OK/NOT_OK | Numeric | Text)
```
**Celery Beat:** daily check of due PM schedules → emit WO-generation events. Meter-based triggering; route
maintenance (multiple assets, one WO); calendar view. **Endpoints:** plan/task/trigger/schedule CRUD;
calendar; search. **Permissions:** `pm_management:{read,create,update,delete,search}`.

---

## Module 2.4 — `inspection_management/` (Checklists — run FOURTH)

```
InspectionChecklist - belongs to a MaintenanceTask or Asset; name, description
ChecklistItem       - checklist_id FK → inspection_checklists.id, step number, description,
                      response_type: Pass/Fail | Numeric/Measure | Text
InspectionResult    - execution record: checklist_id FK, asset_id FK → asset_management.assets.id (shared DB
                      — resolve via the asset service, no model import; §0.5), performed_by, date, results
```
**Endpoints:** checklist CRUD; record results; search. **Permissions:**
`inspection_management:{read,create,update,delete,search}`.

---

## Module 2.5 — `defect_management/` (Defect / Fault Reporting — run FIFTH)

The entry point of the maintenance loop: "a **tag** has a problem, and a specific **asset** under it (e.g. the
pump) has failed." A fault becomes visible on the KPI dashboard and can be turned into a Work Order. The fault
does **not** start work by itself — actual work is gated by the HSE permit/access workflow (Phase 4.2).

**Models:**
```
DefectReport - defect_number (auto DEF-2026-0001),
               tag_id FK → tag_management tag (shared DB) — resolve via the tag_management SERVICE, never a
                 model import (§0.5),
               asset_id (optional) FK → asset_management.assets.id (shared DB) — the failed equipment under
                 the tag; resolve via the asset service, no model import,
               severity: Low/Medium/High/Critical,
               status: Open/Acknowledged/In Progress/Resolved/Closed/Rejected,
               description, description_embedding (Vector 1024), reported_by, reported_at,
               work_order_id (optional) FK → work_order (shared DB) — set when a WO is raised; resolve via the
                 work_order service, no model import,
               photos (FileAsset attachments)
DefectComment - defect_id FK → defect_reports.id, follow-up notes / status changes (audit-logged)
```

**Key logic:** **criticality lives on the tag** (admin-defined tag metadata, JSONB) — read it via the
tag_management service to compute "critical tags with an open fault" (the headline maintenance KPI). Raising a
WO from a defect links them; **closing the WO auto-resolves the defect via a Celery event** (no direct
cross-module write). **Endpoints:** `POST /defects`, `GET /defects` (filter tag/asset/status/severity),
`GET /defects/{id}`, `PATCH /defects/{id}` (status), `POST /defects/{id}/comments`, `POST /defects/search`,
`POST /defects/export`, `/defects/ask`. **Permissions:** `defect:read, defect:write, defect:resolve,
defect:export` (seeded). **Frontend:** report-a-fault form, defect register (filter by tag/status/severity),
defect detail.

---

## Module 2.6 — Notification & Workflow Engine (cross-cutting — run SIXTH)

Internal bell + email (async via Celery). Every module publishes domain **events**; the engine routes them by
rule ("when X happens in module Y, notify user/role Z"). Cross-module triggers go through **Celery events**
(already the standard — leave as events; never a synchronous reach into another module). Build the generic
engine here so Phase 2 events (WO assigned, PM due, defect raised, low stock) have a consumer.

---

# PART C — Phase 2-R: Maintenance KPI Dashboard (reporting sprint)

The maintenance "view at a glance" page — KPI cards + charts + Excel/PDF export, on the shared chart-data
convention (`GET /kpi/{module}` → cards; `GET /reports/{module}/{name}` → `{chart_type, x, series, unit}`,
params `?from=&to=&group_by=&currency_id=`). Export via the `shared/export/` engine (Phase 1).

**KPI cards (`GET /kpi/maintenance`):**
- **Number of critical tags with an open fault** (headline KPI) — trend vs last week
- Open work-order backlog (by priority); MTTR + MTBF (trend); PM compliance % (gauge vs target); overdue WOs

**Charts (`GET /reports/maintenance/...`):**
- `backlog-trend` — open WOs over time → **line**
- `wo-by-status` — WO status breakdown → **donut**
- `faults-by-criticality` — open defects by tag criticality A/B/C → **stacked bar**
- `top-failing-tags` — tags/assets with most faults this period → **horizontal bar**
- `pm-compliance` — compliance % over time → **line with target band**
- `maintenance-cost` — labor + material cost over time, base currency → **bar**

**Summary page:** KPI cards row (critical-tags-with-faults first), backlog line + status donut,
faults-by-criticality + top-failing-tags, PM-compliance line, cost bar. Filter bar (period, unit/plant,
criticality) + Export to Excel/PDF. **Permissions:** `maintenance:read`, `maintenance:export`.

---

# PART D — Build order & exit checklist

**Order:** asset → work_order → pm → inspection → defect → notification engine → Phase 2-R dashboard.

**Phase 2 is done when:**
- [ ] All maintenance modules live, each with `search/`, `/ask`, permissions seeded, every route protected.
- [ ] Every cross-module ref is a real FK resolved via the owning module's service — no model/route/schema
      imports across modules.
- [ ] WO material consumption, PM→WO generation, and WO-close→defect-resolve are **Celery events**.
- [ ] `WorkOrderLabor.employee_id` is a nullable fallback now (FK in Phase 3); same-module FKs
      (`parent_asset_id`, `AssetSystem`, etc.) are real FKs.
- [ ] Notification engine consumes Phase 2 events; Phase 2-R dashboard live with "critical tags with open
      faults" as the headline KPI + export.
- [ ] `pytest` + `alembic check` green.

**Cross-module reference summary (Phase 2):**

| Reference | Final state |
|---|---|
| `Asset.model_id` | FK → `managed_models`, nullable, resolve via model_management service |
| `AssetSpare.item_id` | FK → `items`, resolve via material service |
| `WorkOrder.asset_id` | FK → `assets`, resolve via asset service |
| `WorkOrderMaterial.item_id` | FK → `items`, resolve via material service; consumption = **event** |
| `WorkOrderLabor.employee_id` | nullable fallback now → FK → `hr.employees` in Phase 3 |
| `MaintenancePlan.asset_id` / `asset_system_id` | FK → asset tables, resolve via asset service |
| `MaintenanceTask.required_items` | FK → `items`, resolve via material service |
| `PMSchedule` → WorkOrder | **Celery event** (cross-module write) |
| `InspectionResult.asset_id` | FK → `assets`, resolve via asset service |
| `DefectReport.tag_id` | FK → tag (shared DB), resolve via tag_management service |
| `DefectReport.asset_id` | FK → `assets`, resolve via asset service |
| `DefectReport.work_order_id` | FK → work_order, resolve via work_order service |
| WO close → defect resolve | **Celery event** (cross-module write) |
| Notification triggers | **Celery events** |
