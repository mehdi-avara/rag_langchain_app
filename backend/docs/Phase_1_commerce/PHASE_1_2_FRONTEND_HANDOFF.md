# Phase 1.2 Frontend Handoff

## Normalized Purchase Orders, Delivery Splits, and Commercial Amendments

This document is the frontend implementation contract for Porsa Phase 1.2.

The backend implementation is complete, tested, migrated, and deployed. The frontend must replace the legacy purchase-order UI and API assumptions with the normalized Phase 1.2 contract described here.

Related backend documents:

```text
backend/docs/Phase_1_commerce/PHASE_1_2_EDIT.md
backend/docs/Phase_1_commerce/PHASE_1_2_BACKEND_CLOSURE.md
```

---

## 1. Backend Deployment Baseline

```text
Backend commit:
c08b0655cd97251fecfe48dce01f24782fc1c1f4

Production Alembic revision:
d3e4f5a6b7c8

Backend regression:
572 passed
1 skipped
63 existing warnings
```

The backend and Celery services are running with the current Phase 1.2 images.

The deployed OpenAPI document is available from:

```text
GET /openapi.json
```

OpenAPI is the source of truth for exact request optionality, response nullability, validation structure, and HTTP status codes.

---

## 2. Main Breaking Changes

### 2.1 A purchase order must contain products

A new manual purchase order cannot be created as a header-only record.

```text
Old behavior:
PO header could be created without products.

New behavior:
PO header, lines, Phase 1, and Phase 1 allocations are created atomically.
```

The frontend must disable the Create action until at least one complete line exists.

### 2.2 Supplier is selected by ID

The frontend must send:

```text
supplier_id
```

The frontend must not use free-text `supplier_name` as the supplier input. `supplier_name` may appear in responses as a derived display field.

### 2.3 Commercial data belongs to PO lines

These values belong to `PurchaseOrderLine`:

```text
item
unit
ordered quantity
line description
unit price
currency
exchange rate
base price
notes
```

They must not be treated as phase-level or duplicated PO-header fields.

### 2.4 Delivery products are allocations

The legacy `PurchasePhaseItem` contract is removed.

Use:

```text
PurchaseOrderLine
PurchasePhase
PurchasePhaseAllocation
```

An allocation points to a PO line. It is not another product record.

### 2.5 Phase 1 is automatic

Every valid PO creation flow automatically creates Phase 1 and allocates the full ordered quantity of every line to it.

The frontend must not call a separate phase-creation endpoint after PO creation.

### 2.6 New phases are created through split

There is no public Add Empty Phase workflow in Phase 1.2.

New phases are created through:

```text
POST /purchase/orders/{po_id}/phases/split
```

### 2.7 Approved commercial changes require amendments

These changes require the amendment workflow after approval:

```text
supplier
line addition
line removal
ordered quantity
unit
unit price
currency
exchange rate
commercial costs
```

Editing a phase title, description, or expected delivery date is a delivery schedule change and is not a commercial amendment by itself.

---

## 3. Normalized Data Ownership

```text
PO source and supplier       -> PurchaseOrder
Ordered item and price       -> PurchaseOrderLine
Delivery schedule            -> PurchasePhase
Quantity assigned to phase   -> PurchasePhaseAllocation
Quantity actually received   -> posted goods receipt items
Commercial amendment history -> PurchaseOrderAmendment
```

The frontend must not recreate legacy duplicated ownership.

---

## 4. Purchase Order Read Contract

A purchase-order detail response follows this hierarchy:

```text
PurchaseOrder
  lines[]
  phases[]
    allocations[]
```

Important header fields:

```text
id
company_id
reference_number
title
source_rfq_id
source_material_requisition_id
supplier_id
supplier_name
status
approval_status
description
created_by_user_id
approved_by_user_id
created_at
updated_at
active_amendment_id
active_amendment_status
amendment_count
```

Source modes:

```text
Manual PO:
  source_rfq_id = null
  source_material_requisition_id = null

RFQ-based PO:
  source_rfq_id is set
  source_material_requisition_id = null

Direct-MR PO:
  source_rfq_id = null
  source_material_requisition_id is set
```

Removed or obsolete assumptions:

```text
winning_quotation_response_id on PO
rfq_item_id on PO line
quotation_response_item_id on PO line
material_requisition_item_id on PO line
source IDs on phases
source IDs on allocations
```

For an RFQ created from an MR, the MR relationship is reached through the RFQ. It is not copied onto the PO.

---

## 5. Purchase Order Line Contract

```text
id
purchase_order_id
line_number
item_id
ordered_quantity
unit_id
line_description
unit_price
currency_id
unit_price_base
exchange_rate_used
notes
created_at
updated_at
allocations[]
```

Resolved display projections may include:

```text
item_code
item_name
item_description
unit_code
currency_code
```

These display fields must not be sent back as independently editable stored facts.

Calculated values:

```text
line_total = ordered_quantity * unit_price
line_total_base = ordered_quantity * unit_price_base
```

The frontend may display totals, but should not send them as independent commercial inputs unless OpenAPI explicitly requires them.

All lines of one PO must use the same `currency_id` and `exchange_rate_used`.

---

## 6. Purchase Phase Contract

```text
id
purchase_order_id
phase_number
title
description
status
expected_delivery_date
created_at
updated_at
allocations[]
```

A phase does not own:

```text
item
unit
price
currency
supplier
MR
RFQ
quotation
received quantity
```

Products shown in a phase must be resolved through phase allocations and PO lines.

---

## 7. Purchase Phase Allocation Contract

```text
id
phase_id
purchase_order_line_id
allocated_quantity
created_at
updated_at
```

An allocation does not own an independent item, unit, price, currency, supplier, or source document.

The backend exposes receipt-related projections:

```text
posted_received_quantity
movable_quantity
```

Formula:

```text
movable_quantity =
allocated_quantity - posted_received_quantity
```

The frontend must not allow a split quantity above `movable_quantity`.

---

## 8. Decimal and Date Handling

Quantities, prices, totals, and exchange rates must use decimal-safe handling.

Do not use native JavaScript floating-point arithmetic for commercial calculations.

Recommended libraries:

```text
decimal.js
big.js
```

Recommended representation:

```text
API Decimal -> string
Form Decimal -> string
Calculation  -> decimal library
Request      -> decimal string or generated API type
```

Dates must use ISO 8601.

Example:

```text
2026-08-15T00:00:00
```

---

## 9. Active Purchase API Routes

```text
GET    /purchase/orders
POST   /purchase/orders
POST   /purchase/orders/export
POST   /purchase/orders/search

POST   /purchase/orders/from-rfq/{rfq_id}
POST   /purchase/orders/from-mr/{mr_id}

GET    /purchase/orders/{po_id}
PATCH  /purchase/orders/{po_id}
DELETE /purchase/orders/{po_id}

POST   /purchase/orders/{po_id}/submit
PATCH  /purchase/orders/{po_id}/approval

GET    /purchase/orders/{po_id}/summary

POST   /purchase/orders/{po_id}/lines
PATCH  /purchase/orders/{po_id}/lines/{line_id}
DELETE /purchase/orders/{po_id}/lines/{line_id}

GET    /purchase/orders/{po_id}/phases
PATCH  /purchase/orders/{po_id}/phases/{phase_id}

GET    /purchase/orders/{po_id}/split-candidates
POST   /purchase/orders/{po_id}/phases/split

GET    /purchase/orders/{po_id}/amendments
POST   /purchase/orders/{po_id}/amendments
GET    /purchase/orders/{po_id}/amendments/{amendment_id}
POST   /purchase/orders/{po_id}/amendments/{amendment_id}/submit
PATCH  /purchase/orders/{po_id}/amendments/{amendment_id}/approval

POST   /purchase/orders/{po_id}/costs
PATCH  /purchase/orders/{po_id}/costs/{cost_id}
DELETE /purchase/orders/{po_id}/costs/{cost_id}

POST   /purchase/orders/{po_id}/receipt-links
```

Remove all calls to legacy phase-item routes.

Do not call a public empty-phase creation route.

---

## 10. Manual PO Creation

Endpoint:

```text
POST /purchase/orders
```

Permission:

```text
purchase_management:orders:create
```

Example request:

```json
{
  "title": "Manual pump purchase",
  "supplier_id": 55,
  "description": "Purchase for the process unit",
  "expected_delivery_date": "2026-08-01T00:00:00",
  "lines": [
    {
      "item_id": 99,
      "ordered_quantity": "10",
      "unit_id": 1,
      "line_description": "API 610 process pump",
      "unit_price": "1200",
      "currency_id": 1,
      "exchange_rate_used": "1",
      "notes": "Original manufacturer required"
    }
  ]
}
```

Do not send:

```text
supplier_name
unit_price_base
base_currency_id on each line
line_total
line_total_base
phase data
allocation data
```

The backend creates these records atomically:

```text
PurchaseOrder
PurchaseOrderLine rows
Phase 1
Phase 1 allocations
```

Manual form requirements:

```text
Header:
  title optional
  supplier required
  description optional
  expected delivery date optional

Each line:
  item required
  ordered quantity > 0
  unit required
  line description optional
  unit price >= 0
  currency required
  exchange rate > 0
  notes optional
```

The line editor must support multiple lines.

---

## 11. RFQ-Based PO Creation

Endpoint:

```text
POST /purchase/orders/from-rfq/{rfq_id}
```

Permissions:

```text
purchase_management:orders:create
rfq_management:read
```

Frontend flow:

1. Load the RFQ and winning quotation.
2. Show the selected supplier and quotation lines as read-only source data.
3. Explain that the PO becomes an independent commercial record.
4. Call the creation endpoint.
5. Navigate to the returned PO detail.

Backend requirements:

```text
RFQ must be closed.
RFQ must have one valid winner.
Winning quotation must cover all required RFQ lines.
RFQ must not already have another active PO.
The selected winner becomes immutable after PO creation.
```

Handle the conflict returned when an RFQ is already linked to a PO.

---

## 12. Direct Purchase From MR

Endpoint:

```text
POST /purchase/orders/from-mr/{mr_id}
```

Permissions:

```text
purchase_management:orders:create
requisition_management:read
```

Example request:

```json
{
  "supplier_id": 55,
  "title": "Direct purchase from approved MR",
  "description": "Urgent direct purchase",
  "expected_delivery_date": "2026-08-01T00:00:00",
  "lines": [
    {
      "requisition_item_id": 501,
      "line_description": "Commercial specification",
      "unit_price": "250",
      "currency_id": 1,
      "exchange_rate_used": "1",
      "notes": "Supplier quotation reference"
    }
  ]
}
```

Frontend responsibilities:

1. Load the approved MR.
2. Display approved MR products.
3. Allow selection of one or more MR items.
4. Prevent duplicate `requisition_item_id` values.
5. Ask only for missing commercial information.
6. Require one common currency and exchange rate.
7. Submit the normalized request.

The backend resolves item, quantity, and unit from the selected MR item.

Do not send:

```text
item_id as a substitute for requisition_item_id
ordered quantity that conflicts with the MR selection
MR IDs on generated PO lines
```

---

## 13. Purchase Order Detail Page

Recommended tabs:

```text
Overview
Products
Deliveries
Costs
Amendments
Receipts
Audit or activity
```

### Overview

Display:

```text
reference number
title
supplier
source type
source link
PO status
approval status
commercial totals
active amendment status
created and approved metadata
```

### Products

Display one row per PO line:

```text
line number
item code
item name
line description
ordered quantity
unit
unit price
currency
line total
base total
notes
```

Do not automatically group lines that use the same Item.

### Deliveries

Display phases separately from commercial lines.

Phase header:

```text
phase number
title
status
expected delivery date
description
```

Allocation row:

```text
PO line
item
allocated quantity
posted received quantity
movable quantity
unit
```

Do not show phase-level price or currency inputs.

---

## 14. Phase Schedule Editing

Endpoint:

```text
PATCH /purchase/orders/{po_id}/phases/{phase_id}
```

Permission:

```text
purchase_management:phases:manage
```

Editable fields:

```text
title
description
expected_delivery_date
```

Do not send product, allocation, price, supplier, currency, or source data in this request.

---

## 15. Split Candidates

Endpoint:

```text
GET /purchase/orders/{po_id}/split-candidates
```

Permission:

```text
purchase_management:phases:split
```

Optional query parameters:

```text
source_phase_id
q
```

Example response:

```json
[
  {
    "from_phase_allocation_id": 501,
    "source_phase_id": 10,
    "source_phase_number": 1,
    "purchase_order_line_id": 77,
    "item_id": 99,
    "item_code": "PUMP-001",
    "item_name": "Centrifugal Pump",
    "unit_code": "pcs",
    "ordered_quantity": "10",
    "allocated_quantity": "10",
    "posted_received_quantity": "2",
    "movable_quantity": "8"
  }
]
```

Use this endpoint immediately before opening and confirming a split. Do not derive candidates from stale PO detail data.

---

## 16. Delivery Split

Endpoint:

```text
POST /purchase/orders/{po_id}/phases/split
```

Permission:

```text
purchase_management:phases:split
```

Required header:

```text
Idempotency-Key
```

One confirmed split operation must use one stable key.

A retry caused by timeout or connection failure must reuse the same key.

A new split must use a new key.

Example request:

```json
{
  "title": "Later delivery",
  "expected_delivery_date": "2026-08-15T00:00:00",
  "reason": "Supplier confirmed a split delivery",
  "moves": [
    {
      "from_phase_allocation_id": 501,
      "quantity": "6"
    }
  ]
}
```

Validation rules:

```text
expected_delivery_date is required
reason is required
at least one move is required
quantity must be > 0
an allocation cannot appear twice
quantity cannot exceed movable_quantity
closed or cancelled POs cannot be split
received quantity cannot be moved
blocked operational allocations cannot be moved
```

Example response:

```json
{
  "phase": {
    "id": 20,
    "purchase_order_id": 15,
    "phase_number": 2,
    "title": "Later delivery",
    "description": null,
    "status": "draft",
    "expected_delivery_date": "2026-08-15T00:00:00",
    "created_at": "2026-07-19T10:00:00",
    "updated_at": "2026-07-19T10:00:00",
    "allocations": []
  },
  "replayed": false,
  "audit_event_id": 100
}
```

When a retry replays an existing split:

```text
replayed = true
```

Treat replay as success.

Split dialog fields:

```text
new expected delivery date
optional title
required reason
candidate table
quantity to move
```

For each candidate show:

```text
allocated
received
movable
entered move
remaining after move
```

The user enters only the amount to move.

After success, invalidate:

```text
PO detail
phases
split candidates
PO list row
summary
activity feed
```

---

## 17. Submission Workflow

Endpoint:

```text
POST /purchase/orders/{po_id}/submit
```

Permission:

```text
purchase_management:orders:submit
```

Before enabling Submit, verify:

```text
at least one line exists
at least one phase exists
all line quantities are positive
all line commercial fields are complete
all lines use one currency and exchange rate
every phase has allocations
allocation totals match ordered quantities
no incomplete active edit exists
```

Backend validation remains authoritative.

Display structured backend validation errors instead of only a generic failure.

---

## 18. Approval Workflow

Endpoint:

```text
PATCH /purchase/orders/{po_id}/approval
```

Permission:

```text
purchase_management:orders:approve
```

Payload follows OpenAPI and includes:

```text
action
note
```

Known actions:

```text
approve
reject
```

Use `approval_status` from the backend response as authoritative state.

---

## 19. Commercial Amendment Workflow

Approved POs cannot be commercially edited as ordinary drafts.

Routes:

```text
GET  /purchase/orders/{po_id}/amendments
POST /purchase/orders/{po_id}/amendments

GET  /purchase/orders/{po_id}/amendments/{amendment_id}

POST /purchase/orders/{po_id}/amendments/{amendment_id}/submit

PATCH /purchase/orders/{po_id}/amendments/{amendment_id}/approval
```

Permissions:

```text
purchase_management:orders:read
purchase_management:orders:amend
purchase_management:orders:submit
purchase_management:orders:approve
```

### Open amendment

Minimum request:

```json
{
  "reason": "Supplier changed the accepted price"
}
```

Only one active amendment may exist for a PO.

### Amendment UI

Display:

```text
active_amendment_id
active_amendment_status
amendment_count
reason
amendment number
before snapshot
proposed snapshot
created by
submitted by
decided by
timestamps
decision note
```

Recommended sections:

```text
Original approved values
Proposed amended values
Calculated differences
Approval history
```

### Editing during amendment

While a draft amendment is active, authorized commercial mutations may use standard PO header, line, and cost endpoints.

Reload the active amendment after every commercial mutation.

### Submit amendment

```text
POST /purchase/orders/{po_id}/amendments/{amendment_id}/submit
```

Permission:

```text
purchase_management:orders:submit
```

After submission, the amendment becomes non-editable until a decision.

### Approve or reject amendment

```text
PATCH /purchase/orders/{po_id}/amendments/{amendment_id}/approval
```

Permission:

```text
purchase_management:orders:approve
```

On rejection, display required decision note validation.

### Rollback behavior

When an amendment is rejected, the backend restores the previously approved commercial state.

Fully refetch:

```text
PO detail
lines
costs
summary
amendment detail
PO list
```

Do not restore values only from local state.

---

## 20. Line Mutations

```text
POST   /purchase/orders/{po_id}/lines
PATCH  /purchase/orders/{po_id}/lines/{line_id}
DELETE /purchase/orders/{po_id}/lines/{line_id}
```

Permission:

```text
purchase_management:orders:update
```

Use normalized IDs:

```text
item_id
unit_id
currency_id
```

Do not send copied display fields as source data.

After mutation, reload:

```text
PO detail
summary
phases
split candidates
active amendment
```

The backend rejects changes that violate PO state, receipt protection, commercial invariants, or amendment requirements.

---

## 21. Costs

```text
POST   /purchase/orders/{po_id}/costs
PATCH  /purchase/orders/{po_id}/costs/{cost_id}
DELETE /purchase/orders/{po_id}/costs/{cost_id}
```

Permission:

```text
purchase_management:costs:manage
```

Cost types:

```text
freight
customs
tax
insurance
other
```

Allocation methods:

```text
per_item
per_value
manual
```

Commercial cost changes on an approved PO may require an active amendment.

---

## 22. Summary

Endpoint:

```text
GET /purchase/orders/{po_id}/summary
```

Permission:

```text
purchase_management:summary
```

Important fields:

```text
purchase_order_id
reference_number
phase_count
item_count
total_in_currency
total_in_base
currency_id
base_currency_id
additional_costs_base
grand_total_base
```

Use this endpoint for authoritative summary totals.

---

## 23. Permission-Based UI

Use the authenticated user's permissions. Do not infer access only from role names.

```text
View orders
purchase_management:orders:read

Create manual, RFQ, or direct-MR PO
purchase_management:orders:create

Edit header and lines
purchase_management:orders:update

Submit PO or amendment
purchase_management:orders:submit

Open amendment
purchase_management:orders:amend

Cancel PO
purchase_management:orders:delete

Approve or reject
purchase_management:orders:approve

Search
purchase_management:orders:search

AI question
purchase_management:orders:ask

Edit phase schedule
purchase_management:phases:manage

Split delivery
purchase_management:phases:split

Manage costs
purchase_management:costs:manage

View summary
purchase_management:summary

Export
purchase_management:export
```

Additional source permissions:

```text
RFQ creation:
rfq_management:read

Direct-MR creation:
requisition_management:read
```

Buttons and actions should be hidden or disabled without permission, but backend authorization remains authoritative.

---

## 24. Error Response Handling

Business errors use:

```json
{
  "detail": {
    "code": "PURCHASE_ORDER_LINES_REQUIRED",
    "message": "Purchase order must contain at least one line"
  }
}
```

Also support FastAPI/Pydantic validation responses where `detail` is an array.

Recommended normalized frontend error type:

```ts
type ApiError = {
  status: number;
  code?: string;
  message: string;
  fields?: Record<string, string[]>;
};
```

Important codes:

```text
PURCHASE_ORDER_NOT_FOUND
PURCHASE_ORDER_LINES_REQUIRED
PURCHASE_ORDER_SUPPLIER_REQUIRED
PURCHASE_ORDER_INVALID_STRUCTURE
PURCHASE_ORDER_COMMERCIAL_TERMS_MISMATCH
PURCHASE_ORDER_COMMERCIAL_FIELDS_IMMUTABLE
PURCHASE_ORDER_CURRENCY_INVALID
PURCHASE_ORDER_BASE_CURRENCY_NOT_CONFIGURED
PURCHASE_ORDER_RFQ_ALREADY_LINKED
PURCHASE_ORDER_RFQ_INVALID_WINNER
PURCHASE_ORDER_NOT_RECEIVABLE

PURCHASE_PHASE_NOT_FOUND
PURCHASE_PHASE_ALLOCATION_NOT_FOUND
PURCHASE_PHASE_ALLOCATION_OVER_RECEIPT

PURCHASE_PHASE_SPLIT_IDEMPOTENCY_REQUIRED
PURCHASE_PHASE_SPLIT_IDEMPOTENCY_CONFLICT
PURCHASE_PHASE_SPLIT_NOT_ALLOWED
PURCHASE_PHASE_SPLIT_INVALID_MOVE
PURCHASE_PHASE_SPLIT_QUANTITY_EXCEEDS_MOVABLE
PURCHASE_PHASE_SPLIT_ALLOCATION_BLOCKED

PURCHASE_ORDER_AMENDMENT_NOT_FOUND
PURCHASE_ORDER_AMENDMENT_ALREADY_OPEN
PURCHASE_ORDER_AMENDMENT_NOT_ALLOWED
PURCHASE_ORDER_AMENDMENT_NOT_EDITABLE
PURCHASE_ORDER_AMENDMENT_INVALID_TRANSITION
PURCHASE_ORDER_AMENDMENT_REASON_REQUIRED
PURCHASE_ORDER_AMENDMENT_POSTED_RECEIPTS_EXIST
```

Status guidance:

```text
400 -> malformed business input
403 -> permission denied
404 -> tenant-scoped record not found
409 -> conflict or idempotency conflict
422 -> validation or invalid business transition
```

Show the backend message and localize known codes.

---

## 25. Legacy Header-Only Purchase Orders

Historical line-less POs remain for audit integrity.

Detect them using:

```text
lines.length === 0
```

Recommended warning:

```text
This is a historical purchase order created before normalized PO lines were
required. Some commercial and delivery actions are unavailable until the order
is normalized.
```

Rules:

```text
A new PO can never be line-less.

A draft or rejected historical PO may be normalized by adding valid lines and
allocations before submission.

An approved historical PO must use the amendment workflow for commercial
changes.

A line-less PO cannot be submitted as a valid normalized PO.

A goods receipt cannot be created without valid phase allocations.
```

Do not hardcode behavior based on IDs.

---

## 26. Removed Frontend Assumptions

Remove any logic that assumes:

```text
supplier_name is the supplier input
currency belongs to the PO header
exchange rate belongs only to the PO header
a phase directly owns products
an allocation directly owns item_id
received quantity is stored on an allocation
an empty phase can be created
phase items can be added through legacy routes
RFQ, MR, or quotation IDs exist on every PO line
winning quotation response ID exists on the PO
line totals are stored input fields
the frontend creates Phase 1 after PO creation
```

---

## 27. Recommended Client State Model

```ts
type PurchaseOrder = {
  id: number;
  referenceNumber: string;
  supplierId: number;
  supplierName?: string | null;
  sourceRfqId?: number | null;
  sourceMaterialRequisitionId?: number | null;
  status: string;
  approvalStatus: string;
  lines: PurchaseOrderLine[];
  phases: PurchasePhase[];
  activeAmendmentId?: number | null;
  activeAmendmentStatus?: string | null;
  amendmentCount: number;
};

type PurchaseOrderLine = {
  id: number;
  lineNumber: number;
  itemId: number;
  orderedQuantity: string;
  unitId: number;
  unitPrice: string;
  currencyId: number;
  unitPriceBase: string;
  exchangeRateUsed: string;
};

type PurchasePhase = {
  id: number;
  phaseNumber: number;
  status: string;
  expectedDeliveryDate?: string | null;
  allocations: PurchasePhaseAllocation[];
};

type PurchasePhaseAllocation = {
  id: number;
  phaseId: number;
  purchaseOrderLineId: number;
  allocatedQuantity: string;
};
```

Generated OpenAPI types take precedence.

---

## 28. Cache Invalidation

After creating a PO:

```text
invalidate PO list
store returned PO
navigate to PO detail
```

After header or line mutation:

```text
invalidate PO detail
invalidate PO list
invalidate summary
invalidate phases
invalidate split candidates
invalidate active amendment
```

After phase update or split:

```text
invalidate PO detail
invalidate phases
invalidate split candidates
invalidate activity history
```

After submit or approval:

```text
invalidate PO detail
invalidate PO list
invalidate amendments
invalidate user task or approval queues
```

After amendment decision:

```text
invalidate every cached PO commercial projection
```

---

## 29. Required Screens and Components

```text
Purchase order list
Purchase order detail
Manual PO creation
RFQ-to-PO confirmation
MR-to-direct-PO form
PO line editor
Products tab
Deliveries tab
Phase schedule editor
Split delivery dialog
Summary panel
Costs panel
Amendment list
Amendment detail and comparison
Amendment open dialog
Amendment submit action
Amendment approval/rejection action
Legacy PO warning
Permission-aware action toolbar
Structured backend error renderer
```

---

## 30. Frontend Implementation Order

### Step 1: API contract regeneration

```text
Regenerate API types from OpenAPI.
Remove obsolete purchase types.
Add normalized line, phase, allocation, split, and amendment types.
Add structured error handling.
```

### Step 2: API service layer

```text
Update purchase CRUD calls.
Add manual normalized creation.
Add RFQ creation.
Add direct-MR creation.
Add line mutation calls.
Add phase update calls.
Add split-candidate and split calls.
Add submit and approval calls.
Add amendment calls.
```

### Step 3: Read-only screens

```text
Update PO list.
Update PO detail.
Separate products and deliveries.
Display normalized summary and source information.
Support legacy line-less POs.
```

### Step 4: Creation forms

```text
Implement manual line table.
Implement RFQ confirmation.
Implement direct-MR selection and commercial fields.
```

### Step 5: Delivery management

```text
Implement phase schedule editing.
Implement split candidates.
Implement idempotent split dialog.
```

### Step 6: Amendment workflow

```text
Open amendment.
Display snapshots and differences.
Edit proposed commercial data.
Submit amendment.
Approve or reject amendment.
Refetch restored or approved state.
```

### Step 7: Permission and error integration

```text
Gate every action by permission.
Render catalogue errors.
Render field validation errors.
Handle conflicts and idempotency replays.
```

### Step 8: Tests and production build

```text
Unit tests
API client tests
form validation tests
permission tests
split tests
amendment tests
legacy PO tests
production frontend build
```

---

## 31. Required Frontend Tests

```text
manual creation requires at least one line
manual creation sends normalized fields only
mixed line currencies are rejected
mixed exchange rates are rejected
RFQ creation sends no duplicated source IDs
direct-MR selection prevents duplicate requisition items
automatic Phase 1 is rendered
legacy phase-item UI is absent
products and deliveries are separate
phase update sends schedule fields only
split quantity cannot exceed movable quantity
split retries reuse the same Idempotency-Key
idempotency replay is treated as success
received quantity cannot be moved
approved commercial edit requires amendment
only one active amendment can be opened
rejected amendment triggers full PO refetch
permission-restricted actions are hidden or disabled
structured error codes are displayed
Pydantic errors map to form fields
legacy line-less PO displays a warning
decimal totals do not use floating-point arithmetic
```

---

## 32. Frontend Acceptance Criteria

Frontend Phase 1.2 is complete when:

- Manual PO creation cannot submit without a valid line.
- Supplier selection sends `supplier_id`.
- Header-level legacy money inputs are removed.
- PO lines use normalized Item, unit, currency, quantity, exchange-rate, and price fields.
- Every creation flow renders automatic Phase 1.
- No legacy phase-item API remains.
- No public empty-phase UI exists.
- Products and deliveries are separate.
- Split candidates come from the backend endpoint.
- Split requests include a stable `Idempotency-Key`.
- Split quantity is limited to `movable_quantity`.
- Replay responses are treated as success.
- Posted received quantities cannot be moved.
- Approved commercial changes use amendments.
- Amendment snapshots and status are visible.
- Amendment rejection reloads restored backend state.
- Permission checks control every action.
- Catalogue and validation errors are rendered clearly.
- Historical line-less POs do not crash the UI.
- Commercial arithmetic uses decimal-safe handling.
- Frontend tests pass.
- Production frontend build passes.
- No obsolete purchase contract remains in the active API layer.

---

## 33. Backend Guarantees

The frontend may rely on the backend to enforce:

```text
tenant isolation
RBAC
valid supplier ownership
valid Item and unit references
common line currency and exchange rate
atomic PO creation
automatic Phase 1
complete initial allocations
allocation sum invariants
split row locking
split idempotency
receipt protection
split rollback
RFQ winner immutability
commercial amendment state
amendment rollback
shared money rounding
catalogued business errors
```

Frontend validation improves UX but does not replace backend validation.

---

## 34. Deferred Work

Not included in this handoff:

```text
delivery recipe or template builder
new shipment subsystem
Phase 2 configurable workflow orchestration
removal of preserved historical PO records
general deprecation-warning cleanup
```

---

## 35. Completion Record

Backend Phase 1.2 is formally closed.

Frontend work starts from this document and the deployed OpenAPI contract.

Frontend closure must be recorded separately after:

```text
frontend implementation
frontend tests
production build
backend integration tests
permission verification
manual end-to-end validation
deployment
```
