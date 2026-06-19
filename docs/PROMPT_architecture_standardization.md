# Prompt — Standardize "Keep FKs, Stay Split-Ready" architecture in the plan + KEEP_IN_MIND

> Paste everything below the line into a new chat. It is self-contained.

---

## Context

This is the petroleum **CMMS** (FastAPI + PostgreSQL + pgvector + SQLAlchemy + Alembic + Celery), a **modular monolith**.

**Read `AGENTS.md` first.** Do **not** read `docs/CMMS_MASTER_PLAN.md` end to end — it's ~3,400 lines. Jump only to the sections named in the tasks (grep for the headings).

A previous session already made these edits, and we are now **revising** part of them:
- Added **Glossary §0** (canonical meanings for model / item / tag / asset / stock) — **keep this**.
- Added **§0.5 "Data Separation Architecture"** — currently written in a **strict "soft-reference everywhere"** style. **This must be revised** (see Decision below).
- Converted several connection points to **soft references** (`Item.model_id`, `StockItem.item_id`, `Asset.model_id`, `PurchasePhaseItem.item_id`) with pre-emptive denormalized snapshot fields. **These must be revised back to FKs** (see Decision).
- Augmented `AGENTS.md` rule 3 + added §0/§0.5 pointers. **Reconcile rule 3** to the new stance.

## Decision to encode (final — this is the target state)

We run **one shared PostgreSQL database** and we **keep foreign keys as the default**. We want DB-enforced referential integrity (no manual "does this id exist?" checks, safe cascades). FKs and JOINs across module schemas in the shared DB are allowed.

**Divisibility comes from clean code seams, NOT from removing FKs:**
- schema-per-module for organization;
- a module is only ever touched through its **service-layer functions**;
- **no cross-module imports** of another module's SQLAlchemy **models**, **route functions**, or **Pydantic schemas**;
- cross-module **writes** go through **Celery events**;
- shared types live in `backend/shared/`.

**Soft references are NOT the default.** They are introduced **only** at a seam we deliberately decide to split out physically. The chosen way to stay "split-ready" is: keep FKs now + a documented, mechanical **FK→soft-ref extraction recipe** for the day (if ever) a module needs its own database.

**Scaling order for large deployments:** index/query tuning → read replicas → partitioning → caching/pooling → (last resort) physically extract one hot module to its own database, converting only that seam's FKs to soft refs at that point.

**Shared platform/identity data** (users, companies, RBAC, currencies/FX) lives in a `platform` schema everyone references; the 4-column money rule still holds (`amount`, `currency_id`, `amount_base`, `exchange_rate_used`).

## Priority

**Phases 0, 1, and 2 are being implemented tomorrow — they MUST end fully consistent with the standard.** Tasks 1–6 set the foundation; **Task 7 is the per-reference sweep that actually fixes these three phases** and is the most important part of this job.

## Tasks

1. **Revise master plan §0.5** to the Decision above (replace the strict soft-ref-everywhere text). It must clearly state: FK-as-default, the seam-discipline rules, "soft-ref only at a designated split-seam," the scaling order, and a step-by-step **"How to extract a module later"** recipe (point the module's engine at a new DB → move its schema → convert only the FKs crossing the cut to soft refs + add service-side existence checks + events → swap in-process service calls for an HTTP client → no business-logic change).

2. **Revise the connection points** changed in the prior pass (`Item.model_id`, `StockItem.item_id`, `Asset.model_id`, `PurchasePhaseItem.item_id`) to **keep FKs** (single shared DB), while preserving the corrected semantics from Glossary §0 (nullable/optional `model_id`; `Item` is the universal stock entity; stock anchors to the item, equipment make/model reached via the model). Remove the pre-emptive denormalized snapshot fields and instead add a one-line note that denormalization happens only at extraction time.

3. **Keep Glossary §0** and all model/item/tag/asset corrections as-is.

4. **Update Phase 4.7 (Modular Monolith Refactor)** so it (a) reflects the seam standard and (b) lists the current cross-module coupling to remove. Run a fresh grep to confirm, but the known offenders are:
   - `tag_management` imports `model_management.models` (ManagedModel) and `financial_management` routes + schemas;
   - `model_management` imports `financial_management` routes + schemas;
   - `property_management` imports `model_management` (models + services) and `financial_management.models`.
   For each, the fix is: replace with a **service-layer call**; stop importing routes/schemas across modules. Note that `purchase_management` is already clean and is the reference pattern.

5. **Reconcile `AGENTS.md`:** rewrite the rule-3 addition to the new stance (FK default + clean seams + a pointer to the §0.5 extraction recipe). Keep the §0 and §0.5 lookup pointers.

6. **Add a new section to `docs/KEEP_IN_MIND.md`**, written in plain English for **both AI assistants and human developers**, titled e.g. **"Module boundaries & database separation — the rules."** It must include:
   - the **FK-default** rule and **why** (integrity, no manual existence checks, safe cascades);
   - the **four seam rules** (no cross-module model/route/schema imports; talk via service functions; events for cross-module writes; shared types in `backend/shared/`);
   - the **"soft-ref only at a designated split-seam"** rule;
   - the **scaling order** and the **extraction recipe**;
   - a short **DO / DON'T** with concrete examples (DON'T `from model_management.models import ManagedModel` in another module; DO call a `model_management` service function);
   - the **"definition of done for a new module"** checklist (all tables in own schema; cross-module access via service functions only; FKs allowed in shared DB but seam stays clean; own `search/` subfolder; own Alembic revisions).

7. **Cross-module consistency sweep — Phases 0, 1, and 2 (highest priority; implemented tomorrow).** Go through every module spec in these three phases and make **every** cross-module reference follow the standard, with this exact rule for each one: **a real FK is allowed and preferred in the shared DB; the code seam stays clean (resolve the other module's data via its service function — never import its model, route, or schema); use a soft-ref only at a deliberately designated split-seam.** So the canonical wording for a cross-module reference becomes: *"`x_id` FK → `<table>` (shared DB); resolve via `<module>` service — do not import its model."* Reconcile each reference below; also delete any leftover "SOFT reference, NO cross-schema FK" wording the prior pass left in these phases (it now contradicts the FK-default decision).

   **Phase 0 — purchase_management, currency:**
   - `PurchasePhaseItem.item_id` — free-text `item_name` in Phase 0, FK → `items` in Phase 1 (resolve via material_management service).
   - `PurchasePhaseItem.financial_receipt_id` (≈line 2050) — currently "plain ID, NOT an ORM FK." Reconcile to the standard: make it a real FK in the shared DB resolved via the financial_management service, OR state explicitly and consistently why it stays a plain id. Remove the contradiction either way.
   - `currency_id` / `base_currency_id` FKs — already correct; leave.
   - `supplier_id` — nullable, becomes a real FK once Supplier exists (Phase 1); keep the `supplier_name` free-text fallback pattern.

   **Phase 1 — material_management, warehouse, procurement, supplier:**
   - `Item.model_id` — FK → `managed_models`, NULLABLE; resolve via model_management service.
   - `StockItem.item_id`, `StockMovement.item_id` — FK → `items`; resolve via material_management service. (Restore these from the soft-ref version the prior pass introduced.)
   - GRN → `PurchasePhase` (FK); PO line → `Item` (FK); PO → `Supplier` (FK).

   **Phase 2 — asset_management, work_order, maintenance_planning, defect, notification:**
   - `Asset.model_id` — FK → `managed_models`, nullable; resolve via model_management service.
   - `AssetSpare.item_id` — FK → `items` (≈line 1144); resolve via material_management service.
   - WorkOrder → `Asset` (FK); WO material tracking → `Item` / `StockItem` (FK); WO labor → `Employee` — **Employee is Phase 3, so use a nullable plain field / free-text fallback now (same pattern as `supplier_name`), upgrade to a real FK in Phase 3.**
   - Defect → `tag` (tag_management) + `Asset` + WorkOrder (≈line 1222) — keep "resolve via service, not a model import," and allow the DB FK.
   - Notification engine — cross-module triggers go through Celery events (already correct; leave).
   - Same-module FKs (`parent_asset_id`, `AssetSystem`, `purchase_order_id`, `phase_id`) — leave as real FKs.

   Finally, **merge the three overlapping refactor specs — Phase 4.7, Prompt 22 ("Module Refactor"), and Prompt 23 ("Route Versioning / service boundary lock", ≈line 1901) — into one consistent description** using the seam-discipline + extraction-recipe framing, since it governs how Phase 2 modules are expected to be built.

## Constraints

- Follow `AGENTS.md` rules. Each module owns its Alembic migrations; never mix two modules in one revision.
- Don't rewrite unrelated sections.
- After editing, **grep to confirm no contradictions remain** (no leftover "soft reference everywhere" / "NO cross-schema FK" wording; §0.5, `AGENTS.md`, and `KEEP_IN_MIND.md` agree).
- **Verification for Task 7:** grep the Phase 0, 1, and 2 sections specifically for every `_id`, `FK`, `link to`, `soft reference`, and `plain ID`, and confirm each cross-module reference matches the standard. Deliver a **per-phase checklist (0, 1, 2)** listing every cross-module reference and its final state (FK / fallback / event) so I can verify before tomorrow's build.
- Give me a short summary of every change made across all tasks.
