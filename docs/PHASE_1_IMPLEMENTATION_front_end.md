# Phase 1 — Frontend Developer Guide
## Commerce & Warehouse (Supplier · Material Master · Procurement · Warehouse · Export)

> **Who this is for:** Frontend developers building UI for Phase 1 features.
> This document tells you what the backend now exposes, what the data models look like from your perspective,
> the API patterns you need to know, and what screens you need to build.

---

## What Phase 1 covers

Phase 1 builds the full procurement and warehouse workflow:

```
Material Requisition (MR) → RFQ → Purchase Order (PO, from Phase 0) → GRN → Stock
```

Six modules are implemented, in dependency order:

| # | Module | What it is |
|---|---|---|
| 1 | `supplier_management` | Vendor registry and performance tracking |
| 2 | `material_management` | Item / Material Master catalog — the universal stock entity |
| 3 | `requisition_management` | Material Requisitions + approval workflow |
| 4 | `rfq_management` | RFQs sent to suppliers + quotation comparison |
| 5 | `goods_receipt_management` | GRNs — what physically arrived against a PO |
| 6 | `warehouse_management` | Warehouses, locations, stock levels, movements |

Plus a shared **Export Engine** and **reporting dashboards** (Phase 1-R).

---

## Glossary — use these terms exactly

These words have precise meanings in the backend. Using the wrong one will lead to bugs.

| Term | Means |
|---|---|
| **item** | A stockable thing (material, spare part, consumable, tool, chemical, PPE). This is what goes on every PO line, MR line, RFQ line, GRN line, and in the warehouse. |
| **model** | An equipment-model type (manufacturer + model name + specs). NOT an AI model. An item may optionally reference a model (e.g. a spare part for a specific pump model). |
| **tag** | A functional process position (P&ID tag). Not a UI label. |
| **asset** | A physical installed unit with a serial number. Coming in Phase 2. |
| **stock** | The on-hand quantity of an item at a storage location. |
| **GRN** | Goods Receipt Note — the record of what physically arrived from a supplier against a PO. |
| **MR** | Material Requisition — an internal request to purchase something. |
| **RFQ** | Request for Quotation — sent to suppliers to get prices. |

---

## Global API patterns

These patterns apply across all Phase 1 modules. Learn them once.

### Authentication & permissions

Every route requires a valid session token and a specific permission. If the user lacks the permission, the API returns `403`. Show an appropriate "Access Denied" message — do not hide the menu item unless you know the user lacks the permission.

### Pagination

All list endpoints accept:
- `?page=` and `?page_size=` (or `limit`/`offset` — confirm in each module)
- `?q=` for keyword search inline with the list

### Search endpoint

Every module has a dedicated search endpoint:

```
POST /{module}/search
Body: { "query": "...", "ids": [], "mode": "hybrid|keyword|semantic", "limit": 20 }
```

Use this for autocomplete fields and advanced search. `mode: hybrid` is the default (keyword + semantic vector search combined).

### Export

Every list/search result can be exported:

```
POST /{module}/{entity}/export
Body: { "format": "xlsx|csv|pdf", "filters": {...}, "columns": ["col1", "col2"] }
Response: 202 { "task_id": "..." }
```

Then poll: `GET /tasks/{task_id}` until `status: done`, then download from `result.download_url`.

The `filters` and `columns` mirror whatever the list/search accepts — export is "run this search, then download it."

### Async tasks (202 pattern)

Heavy operations (bulk import, export, posting a GRN) return immediately with:
```json
{ "task_id": "abc-123" }
```

Poll `GET /tasks/{task_id}` until `status` is `done` or `failed`. Show a spinner/progress indicator during polling. On `done`, read `result`. On `failed`, show `error`.

### Money fields

Every price/cost on screen comes from four backend fields. Display `amount` in the transaction currency (`currency_id`), and `amount_base` in the company base currency (for aggregations/dashboards). Never compute totals by summing `amount` across different currencies — always use `amount_base`.

### Number series

Each entity has an auto-generated human-readable code:
- Suppliers: `SUP-001`, `SUP-002`, …
- Items: `ITM-001` (or `item_code` set manually/imported)
- MRs: `MR-2026-0001`
- RFQs: `RFQ-2026-0001`
- GRNs: `GRN-2026-0001`
- Stock Movements: `MOV-2026-00001`

These are read-only on the frontend — never let users edit them.

### Audit log

The backend logs every write automatically. You don't need to do anything for audit trail — just make sure your API calls carry the auth token so the backend can record `user_id`.

---

## Module 1 — Supplier Management

**Base path:** `/suppliers`

### Data shape (what you display)

```
Supplier
  id, code (SUP-001), name, type (Local/International/Manufacturer/Distributor)
  country, city, address, tax_id, website
  status: Pending | Approved | Blacklisted
  notes

SupplierContact
  id, supplier_id, name, email, phone, position, is_primary

SupplierCategory
  id, supplier_id, category_name  ← what they supply

SupplierDocument
  id, supplier_id, document_type (Contract/NDA/Catalog/Certificate/License), file download URL

SupplierEvaluation
  id, supplier_id, evaluated_by, date
  delivery_score, quality_score, price_score  (0–10 each)
  total_score (average), notes

SupplierPerformance
  total_orders, on_time_rate, rejection_rate  (derived, may be null until PO data exists)
```

### Key endpoints

| Method | Path | What it does |
|---|---|---|
| GET | `/suppliers` | List (supports `?q=`, `?status=`) |
| POST | `/suppliers` | Create supplier |
| GET | `/suppliers/{id}` | Supplier profile |
| PUT | `/suppliers/{id}` | Update |
| DELETE | `/suppliers/{id}` | Delete |
| GET | `/suppliers/{id}/contacts` | Contacts list |
| POST | `/suppliers/{id}/contacts` | Add contact |
| GET | `/suppliers/{id}/categories` | Categories |
| GET | `/suppliers/{id}/documents` | Documents + download links |
| GET | `/suppliers/{id}/evaluations` | Evaluations history |
| POST | `/suppliers/{id}/evaluations` | Submit evaluation |
| POST | `/suppliers/search` | Keyword + semantic search |
| POST | `/suppliers/ask` | AI Q&A on suppliers |

### Permissions needed

`supplier_management:read`, `supplier_management:create`, `supplier_management:update`, `supplier_management:delete`, `supplier_management:search`

### Screens to build

1. **Supplier list** — filterable by status, searchable, paginated
2. **Supplier profile** — tabs: Details / Contacts / Categories / Documents / Evaluations / Performance
3. **Evaluation form** — three sliders (0–10) + notes → POST to evaluations
4. **Document tab** — list with file type badges + download button

---

## Module 2 — Material Management (Item / Material Master)

**Base path:** `/materials`

This is the central catalog. Every PO line, MR line, RFQ line, and warehouse stock entry references an `item_id` from here.

### Data shape

```
ItemCategory
  id, parent_id (nullable — tree structure), code, name, description

Unit
  id, code (KG/L/PCS/M/BOX), name, unit_type (Mass/Volume/Length/Count/Area)

Item
  id, item_code (unique), name, description
  category_id → ItemCategory
  unit_id → Unit
  item_type: Material | Spare Part | Consumable | Tool | Chemical | PPE
  specs (JSON — free-form technical specs)
  barcode, qr_code
  is_active, is_critical, lead_time_days
  model_id (nullable) → equipment model (only for model-specific spares)

ItemAlternative
  id, item_id, alt_code, alt_name
  supplier_id → Supplier  (which supplier provides this alternative)

ItemDocument
  id, item_id, file download URL  (datasheets, Safety Data Sheets)
```

### Key endpoints

| Method | Path | What it does |
|---|---|---|
| GET | `/materials` | List (supports `?q=`, `?category=`, `?item_type=`) |
| POST | `/materials` | Create item |
| GET | `/materials/{id}` | Item detail |
| PUT | `/materials/{id}` | Update |
| DELETE | `/materials/{id}` | Delete |
| GET | `/materials/categories` | Full category tree |
| GET | `/materials/{id}/alternatives` | Alternatives list |
| GET | `/materials/{id}/documents` | Documents |
| POST | `/materials/search` | Keyword + semantic search |
| POST | `/materials/ask` | AI Q&A on items |
| POST | `/materials/import` | **Bulk Excel import** → 202 + task_id |

### Permissions needed

`material_management:read`, `material_management:create`, `material_management:update`, `material_management:delete`, `material_management:search`, `material_management:import`

### Screens to build

1. **Item list** — filterable by category (tree picker), item_type, active/inactive; searchable
2. **Item detail** — specs displayed as a key-value table (from JSON), linked model info if present, alternatives tab, documents tab
3. **Category tree** — sidebar or drawer component; parent–child navigation
4. **Bulk import screen** — upload Excel → 202 → poll progress → show errors/successes per row

---

## Module 3 — Requisition Management (Material Requisition)

**Base path:** `/requisitions`

Internal request to procure items. Has an approval workflow.

### Data shape

```
MaterialRequisition
  id, mr_number (MR-2026-0001)
  requested_by (user_id), department_id
  needed_by_date, reason
  priority: Normal | Urgent | Critical
  status: Draft | Submitted | Under Review | Approved | Rejected | Ordered | Closed
  notes

MRItem
  id, mr_id
  item_id → Item (display item_code + name via material service)
  quantity, unit_id
  estimated_unit_cost (optional), currency_id
  notes
```

### Status transitions (state machine)

```
Draft → Submitted          (by requester)
Submitted → Approved       (by dept_head or procurement_officer)
Submitted → Rejected       (by dept_head or procurement_officer)
Approved → Ordered         (automatic, when a PO is created from this MR)
```

Do not show transition buttons the current user cannot perform (check their permissions).

### Key endpoints

| Method | Path | What it does |
|---|---|---|
| GET | `/requisitions` | List |
| POST | `/requisitions` | Create MR (starts as Draft) |
| GET | `/requisitions/{id}` | MR detail with items |
| PUT | `/requisitions/{id}` | Update (Draft only) |
| POST | `/requisitions/{id}/submit` | Draft → Submitted |
| POST | `/requisitions/{id}/approve` | Submitted → Approved |
| POST | `/requisitions/{id}/reject` | Submitted → Rejected |
| POST | `/requisitions/search` | Search |

### Permissions needed

`requisition_management:read`, `requisition_management:create`, `requisition_management:update`, `requisition_management:approve`

### Screens to build

1. **MR form** — item picker (search items by code/name), quantity, priority, needed-by date
2. **MR approval inbox** — list of MRs in `Submitted` / `Under Review` status; approve/reject buttons
3. **MR detail** — status badge + timeline, item lines, action buttons based on status + user role

---

## Module 4 — RFQ Management (Request for Quotation)

**Base path:** `/rfqs`

Sent to suppliers to collect pricing before creating a PO.

### Data shape

```
RequestForQuotation (RFQ)
  id, rfq_number (RFQ-2026-0001)
  mr_id (optional) → MaterialRequisition
  title, description, deadline_date
  status: Draft | Sent | Closed | Cancelled

RFQSupplier
  id, rfq_id, supplier_id → Supplier
  sent_at, response_status

RFQItem
  id, rfq_id, item_id → Item
  quantity, unit_id, specifications (text)

QuotationResponse       ← one per supplier who responded
  id, rfq_id, supplier_id → Supplier
  received_at, valid_until, payment_terms, delivery_days, notes

QuotationResponseItem   ← one per RFQItem in that response
  id, response_id, rfq_item_id
  unit_price, currency_id, unit_price_base, exchange_rate_used
  lead_time_days, notes
```

### Key endpoints

| Method | Path | What it does |
|---|---|---|
| GET | `/rfqs` | List |
| POST | `/rfqs` | Create RFQ |
| GET | `/rfqs/{id}` | RFQ detail |
| POST | `/rfqs/{id}/send` | Draft → Sent (notifies suppliers) |
| POST | `/rfqs/{id}/close` | Sent → Closed |
| POST | `/rfqs/{id}/suppliers` | Add suppliers to RFQ |
| POST | `/rfqs/{id}/responses` | Record a quotation response |
| GET | `/rfqs/{id}/comparison` | **Side-by-side supplier comparison** |
| POST | `/rfqs/search` | Search |

### Permissions needed

`rfq_management:read`, `rfq_management:create`, `rfq_management:update`, `rfq_management:approve` (approve = select winning quotation)

### Screens to build

1. **RFQ form** — pick items (from Item catalog), add suppliers, set deadline
2. **RFQ detail** — status, suppliers list + their response status, record response button
3. **Quotation comparison table** — one column per supplier, one row per item; highlight lowest price per line; all prices shown in both transaction currency and base currency

---

## Module 5 — Goods Receipt Management (GRN)

**Base path:** `/grns`

Records what physically arrived against a PO. **Posting a GRN triggers stock creation** (via an async event — you don't call warehouse directly).

### Data shape

```
GoodsReceiptNote (GRN)
  id, grn_number (GRN-2026-0001)
  po_id → PurchaseOrder
  received_by (user_id), receipt_date, delivery_note_number
  status: Draft | Posted
  warehouse_id → Warehouse
  notes

GRNItem
  id, grn_id
  item_id → Item
  po_item_id → PO line
  received_quantity, accepted_quantity, rejected_quantity
  rejection_reason (required if rejected_quantity > 0)
  storage_location_id → StorageLocation (where to put accepted items)
```

### Posting behavior

When a GRN is posted (`Draft → Posted`), the backend asynchronously creates stock movements for all accepted items. This is a **202 response** — poll `GET /tasks/{task_id}` for completion. Show the user a "Processing..." state until done.

One PO can have multiple GRNs (partial deliveries). The PO status automatically updates to `Partially Received` or `Fully Received`.

### Key endpoints

| Method | Path | What it does |
|---|---|---|
| GET | `/grns` | List |
| POST | `/grns` | Create GRN (Draft) |
| GET | `/grns/{id}` | GRN detail |
| PUT | `/grns/{id}` | Update (Draft only) |
| POST | `/grns/{id}/post` | Post GRN → creates stock movements (202 + task_id) |
| POST | `/grns/search` | Search |

### Permissions needed

`goods_receipt_management:read`, `goods_receipt_management:create`, `goods_receipt_management:update`, `goods_receipt_management:approve`

### Screens to build

1. **GRN entry screen** — select PO, auto-fill expected items; enter received/accepted/rejected quantities + rejection reasons; pick storage location per line
2. **Receiving dashboard** — GRNs in Draft, recently Posted; pending receipts (POs without a GRN)

---

## Module 6 — Warehouse Management

**Base path:** `/warehouse`

Physical locations, current stock levels, movement history, and stock counting.

### Data shape

```
Warehouse
  id, code, name, type (Main/Secondary/Field/Transit)
  location/address, manager_id

Zone
  id, warehouse_id, code, name, description

StorageLocation       ← the actual shelf/bin
  id, zone_id, code, name
  capacity_unit, capacity_value
  is_active

StockItem             ← current state: one row per item per location
  id, item_id → Item, storage_location_id → StorageLocation
  quantity_on_hand, quantity_reserved, quantity_available
  min_level, max_level, reorder_point
  unit_cost, unit_cost_currency_id  (weighted average cost)
  unit_cost_base

StockMovement         ← append-only history, never edited
  id, movement_number (MOV-2026-00001)
  movement_type: RECEIPT | ISSUE | TRANSFER_OUT | TRANSFER_IN | ADJUSTMENT | RETURN | COUNT_ADJUSTMENT
  item_id → Item
  from_location_id (nullable), to_location_id (nullable)
  quantity, unit_cost, currency_id, unit_cost_base, exchange_rate_used
  reference_type: GRN | WORK_ORDER | MANUAL | STOCK_COUNT
  reference_id (id of the GRN or work order etc.)
  performed_by, movement_date, notes

StockCount
  id, count_number, warehouse_id, status (Open/In Progress/Posted), performed_by

StockCountLine
  id, count_id, item_id, location_id
  system_quantity (what backend says), counted_quantity (what staff counted), variance
```

### Key endpoints

| Method | Path | What it does |
|---|---|---|
| GET | `/warehouse/warehouses` | List warehouses |
| GET | `/warehouse/warehouses/{id}/zones` | Zones in warehouse |
| GET | `/warehouse/zones/{id}/locations` | Storage locations in zone |
| GET | `/warehouse/stock` | Stock list (filterable by warehouse/location/item) |
| GET | `/warehouse/stock/low` | Items at or below reorder point |
| GET | `/warehouse/movements` | Movement history |
| POST | `/warehouse/movements` | Manual stock movement |
| GET | `/warehouse/counts` | Stock count list |
| POST | `/warehouse/counts` | Start a stock count |
| POST | `/warehouse/counts/{id}/post` | Post count → creates COUNT_ADJUSTMENT movements |
| POST | `/warehouse/items/search` | Search stock |
| POST | `/warehouse/ask` | AI Q&A on warehouse |

### Permissions needed

`warehouse_management:locations:read`, `warehouse_management:locations:manage`, `warehouse_management:stock:read`, `warehouse_management:stock:manage`, `warehouse_management:movements:read`, `warehouse_management:movements:create`, `warehouse_management:search`, `warehouse_management:summary`

### Screens to build

1. **Warehouse map/tree** — expandable: Warehouse → Zone → Storage Location; click to see stock at that location
2. **Item stock view** — for a given item: all locations holding it, quantities, reorder status
3. **Movement history** — filterable by item, location, movement type, date range; links to source (GRN, etc.)
4. **Low-stock list** — items at or below `reorder_point`; quick action to create MR
5. **Stock-count screen** — start count → enter counted quantities per line → compare vs system → post

---

## Export Engine (shared across all modules)

Every list/search result supports export. The pattern is always:

```
POST /{module}/{entity}/export
Body:
{
  "format": "xlsx",          // or "csv" or "pdf"
  "filters": { ... },        // same shape as the list/search filters
  "columns": ["col1", ...]   // which columns to include
}

Response: 202
{ "task_id": "abc-123" }
```

Poll `GET /tasks/{task_id}` → when `status: done`, download from `result.download_url`.

Add an **Export button** to every list/search screen. On click, open a small modal to pick format and columns, then trigger the export and show progress.

The user needs both `{module}:read` and `{module}:export` permissions to export.

---

## Phase 1-R — Reporting Dashboards

Two summary dashboards expose chart data for managers.

### Chart data API pattern (same for all modules)

```
GET /kpi/{module}
Response: [ { key, label, value, unit, trend } ]

GET /reports/{module}/{chart_name}
Query params: ?from=&to=&group_by=&currency_id=
Response: { chart_type, x, series: [ { name, data[] } ], unit }
```

### Inventory dashboard (`warehouse_management:summary`)

- KPI cards: total stock value (base currency), number of items below reorder point, warehouses active
- Stock value over time → **line chart**
- Low-stock items → **table / KPI badges**

### Procurement dashboard (`purchase_management:summary`)

- KPI cards: total spend this period, open POs, avg. procurement cycle time (MR → GRN)
- Spend by supplier → **horizontal bar chart**
- Procurement cycle time → **bar chart**
- GRN vs PO variance (received vs ordered) → **bar or table**

Each dashboard has a filter bar (date range, currency) and an **Export button** connected to the Export Engine.

---

## Key things NOT to build (handled by backend)

- Do not compute `quantity_available` — the backend provides it (`on_hand - reserved`)
- Do not compute weighted-average cost — backend updates it on every receipt
- Do not convert currencies — always display what the backend returns; use `amount_base` for totals
- Do not manually update PO status after a GRN — the backend does this automatically
- Do not directly trigger stock movements when posting a GRN — the backend handles this asynchronously; just poll the task

---

## Summary of screens to build

| Module | Screens |
|---|---|
| Supplier | Supplier list, Supplier profile (tabs), Evaluation form |
| Material | Item list, Item detail, Category tree, Bulk import |
| Requisition | MR form, MR approval inbox, MR detail |
| RFQ | RFQ form, RFQ detail, Quotation comparison table |
| GRN | GRN entry screen, Receiving dashboard |
| Warehouse | Warehouse map/tree, Item stock view, Movement history, Low-stock list, Stock-count screen |
| Dashboards | Inventory dashboard, Procurement dashboard |
| Shared | Export modal + polling component (reused everywhere) |
