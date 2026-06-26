# Phase 1 — End-to-End Test Procedure (Procure-to-Stock)

Goal: exercise **every Phase 1 module and integration** in one happy-path run, plus the
key negative cases. This is a manual / scriptable API test — run it against a live instance
(Swagger UI at `/docs`, curl, or a REST client).

## 0. Prerequisites (must all be true before you start)

- API process running **and** a Celery worker running (the GRN→stock step is async — without a
  worker, stock will never be created).
- Postgres migrated: `alembic upgrade head`; RBAC seeded (`seed_rbac.py`); base currency seeded.
- A test user whose role has **all** Phase 1 permissions. Keep a **second** user with NO
  `*:export` and limited perms for the RBAC negative tests in §11.
- Note your company's `base_currency_id`. Have at least one **non-base** currency + an exchange
  rate, so the multi-currency assertions in §10 are meaningful.

Get a token: `POST /auth/login` → use `Authorization: Bearer <token>` on every call below.

---

## 1. Supplier  (`supplier_management`)

1. `POST /suppliers` — name, type `Local`, country, status `Approved`.
   - ✅ Response has auto `code` like `SUP-001`.
2. `POST /suppliers/{id}/contacts`, `/categories`, `/evaluations` — each returns 201.
3. `GET /suppliers?q=<name>` → supplier appears. `POST /suppliers/search` (keyword + semantic) → appears.
4. `POST /suppliers/ask` with a question about the supplier → returns an answer (AI track).

**Record:** `SUPPLIER_ID`.

---

## 2. Material Master / Item catalog  (`material_management`)

1. `POST /materials/categories` (tree), `POST /materials/units` (e.g. `PCS`).
2. `POST /materials/items` — name, `category_id`, `unit_id`, `item_type` `Spare Part`,
   `is_critical=true`, `reorder_point` (set low, e.g. 5, so §8 low-stock triggers).
   - ✅ Auto `item_code`; `model_id` may be null.
3. (Optional) Bulk import: `POST /materials/items/import` with an `.xlsx` → **202 + task_id**;
   poll `GET /tasks/{task_id}` until `done`.
4. `GET /materials/items?q=&category=&item_type=` and `POST /materials/search` → item appears.

**Record:** `ITEM_ID`, `UNIT_ID`.

---

## 3. Requisition  (`requisition_management`)

1. `POST /requisitions` — `needed_by_date`, `priority`, one MR item with `item_id=ITEM_ID`,
   `quantity=10`, `unit_id`, optional `estimated_unit_cost` + `currency_id`.
   - ✅ Auto `mr_number` like `MR-2026-0001`; status `Draft`.
2. Transition: submit (`Draft → Submitted`), then approve (`Submitted → Approved`).
   - ✅ Each transition allowed only for the right role; status history recorded.
   - ❌ Try approving from `Draft` directly → should be rejected (catalogued error, not 500).

**Record:** `MR_ID`.

---

## 4. RFQ + Quotations  (`rfq_management`)

1. `POST /rfqs` — `mr_id=MR_ID`, title, `deadline_date`.
2. `POST /rfqs/{id}/suppliers` (`supplier_id=SUPPLIER_ID`), `POST /rfqs/{id}/items` (`item_id=ITEM_ID`).
3. Send the RFQ (`Draft → Sent`).
4. `POST /rfqs/{id}/responses` — a `QuotationResponse` with one item: `unit_price`, `currency_id`
   (use the **non-base** currency), `lead_time_days`.
   - ✅ **Money rule:** response item has `unit_price`, `currency_id`, `unit_price_base`,
     `exchange_rate_used` all populated; `unit_price_base` = price × rate, in base currency.
5. `GET /rfqs/{id}/comparison` → all supplier responses side-by-side.
6. Select winner (`approve`).

**Record:** `RFQ_ID`, winning `SUPPLIER_ID`/price.

---

## 5. Purchase Order  (`purchase_management`, from Phase 0)

1. Create a PO (or convert from the winning quotation) — header already exists from Phase 0.
   - ✅ `PurchaseOrder.supplier_id` is a **real FK** to `suppliers` (not free text).
   - ✅ PO line resolves to `item_id` → `items` (Phase-0 `item_name` may remain on legacy rows).
2. Confirm the source MR moved `Approved → Ordered`.

**Record:** `PO_ID`, `PO_PHASE_ID`, `PO_ITEM_ID`.

---

## 6. Goods Receipt (GRN)  (`goods_receipt_management`)

1. First create warehouse structure (needed for the GRN location fields) — see §7 steps 1–3, or
   do §7 first. You need a `WAREHOUSE_ID` and a `STORAGE_LOCATION_ID`.
2. `POST /goods-receipts` (Draft) — `po_id=PO_ID` (or phase), `warehouse_id`, and one GRN item:
   `item_id=ITEM_ID`, `received_quantity=10`, `accepted_quantity=8`, `rejected_quantity=2`,
   `rejection_reason`, `storage_location_id`.
   - ✅ Auto `grn_number` like `GRN-2026-0001`; status `Draft`.
   - ❌ Unbalanced quantities (accepted+rejected ≠ received) → rejected by validation.
3. **Post it:** `POST /goods-receipts/{id}/post` → status `Posted`. **Returns fast.**
   - ✅ This does **NOT** synchronously create stock — it emits a Celery event. (That's correct.)

**Record:** `GRN_ID`.

---

## 7. Warehouse + the async integration  (`warehouse_management`)

Setup (if not done in §6):
1. `POST /warehouse/warehouses` → `WAREHOUSE_ID`.
2. `POST /warehouse/{warehouse}/zones` → zone.
3. `POST /warehouse/zones/{zone}/locations` → `STORAGE_LOCATION_ID`.

**Verify the GRN → stock event (the most important assertion in this whole test):**
4. After posting the GRN in §6, **wait / poll** (the worker processes the event):
   `GET /warehouse/stock?item_id=ITEM_ID&location_id=STORAGE_LOCATION_ID`
   - ✅ A `StockItem` exists with `quantity_on_hand = 8` (the **accepted** qty, not received 10).
   - ✅ `unit_cost` set (weighted average) **with a currency** and `unit_cost_base`.
5. `GET /warehouse/movements?item_id=ITEM_ID`
   - ✅ A `StockMovement` of type `RECEIPT`, `reference_type=GRN`, `reference_id=GRN_ID`, qty 8.
   - ✅ Movements are **append-only** — there is no update/delete endpoint for them.
6. Back in procurement: the PO line `received_quantity` updated and PO status →
   `Partially Received` (since 8 < ordered) — not `Fully Received`.

**Negative + extra warehouse paths:**
7. ISSUE more than available: `POST /warehouse/movements` type `ISSUE`, qty `9999` → rejected
   (`quantity_available < requested`). Then ISSUE a valid qty → `quantity_on_hand` decreases.
8. Low stock: ensure on-hand ≤ `reorder_point` → `GET /warehouse/stock/low` includes the item.
9. Stock count: `POST /warehouse/counts` → add a line with a `counted_quantity` different from
   system → `POST /warehouse/counts/{id}/post` → ✅ a `COUNT_ADJUSTMENT` movement is created for
   the variance.

---

## 8. Export Engine  (`shared/export/`)

1. `POST /warehouse/stock/export` body `{ "format": "xlsx", "filters": {...}, "columns": [...] }`
   → **202 + task_id**. Poll `GET /tasks/{task_id}` → `done` with a `download_url`; open the file.
   - ✅ Headers styled, currency columns formatted.
2. Repeat with `"format": "csv"` (✅ opens cleanly, UTF-8 BOM) and `"format": "pdf"`
   (✅ title block + applied filters).
3. Repeat one export for each module endpoint: `/suppliers/export`, `/materials/items/export`,
   `/requisitions/export`, `/rfqs/export`, `/goods-receipts/export`, `/warehouse/movements/export`,
   `/purchase/orders/export`.
4. ❌ As the **limited user** (no `:export`) → expect `403`.
   - ✅ Each successful export wrote an `export_audit_logs` row.

---

## 9. Dashboards / KPI  (`shared/reporting/`)

1. `GET /kpi/warehouse_management` → cards `{key,label,value,unit,trend}`: stock value (base
   currency), # items below reorder, active warehouses.
2. `GET /kpi/purchase_management` → spend this period, open POs, avg procurement cycle time (MR→GRN).
3. `GET /reports/warehouse_management/{name}` and `/reports/purchase_management/{name}` →
   `{chart_type, x, series:[{name,data}], unit}`. Try `?from=&to=&group_by=&currency_id=`.

---

## 10. Multi-currency invariant (spot-check across the run)

For every monetary row created above (MR item, quotation item, GRN item, stock, movement):
- ✅ Four columns present and consistent: amount, `currency_id`, `*_base`, `exchange_rate_used`.
- ✅ All `*_base` values are in the company base currency, and dashboards total in base currency.

---

## 11. RBAC + error-catalog invariants

- ❌ Call any Phase 1 endpoint as the limited user lacking that permission → `403`.
- ❌ Fetch a non-existent id → catalogued `404`, **not** an uncaught 500.
- ✅ Every auto number matches `MODULE-YEAR-NNNN` (`SUP-001`, `MR-2026-0001`, `RFQ-2026-0001`,
  `GRN-2026-0001`, `MOV-2026-00001`).

---

## 12. DB-level cross-check (optional, psql)

```sql
-- stock equals accepted GRN qty
SELECT si.item_id, si.quantity_on_hand FROM stock_items si WHERE si.item_id = :ITEM_ID;
-- exactly one RECEIPT movement for the GRN
SELECT movement_type, reference_type, reference_id, quantity
FROM stock_movements WHERE reference_id = :GRN_ID;
-- money rule populated
SELECT unit_price, currency_id, unit_price_base, exchange_rate_used
FROM quotation_response_items;
```

---

## Pass criteria

The phase is behaving correctly if: the chain MR → RFQ → Quotation → PO → GRN runs end-to-end;
**posting the GRN asynchronously creates exactly the accepted qty as stock** with a `RECEIPT`
movement and updated PO status; ISSUE respects availability; export returns a file in all three
formats and 403s without `:export`; KPI/report endpoints return the correct shapes; and every
money row carries the 4 columns. Then run `pytest` + `alembic check` locally for the static side.
