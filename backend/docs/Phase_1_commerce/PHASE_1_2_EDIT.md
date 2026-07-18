# Phase 1.2 Edit - Normalized PO Lines and Delivery Splits

Phase 1 is already finished. This file defines the Phase 1.2 changes that must
be implemented on top of the existing commerce flow.

## 1. Required Business Behavior

A purchase order must contain at least one product. A header without a product
is not a valid PO.

Every PO is created with one automatic delivery phase. Initially, the full
ordered quantity of every PO line is allocated to Phase 1. Later, a user can
split unreceived quantities into a newly created phase.

```text
PO line: Pump, ordered quantity 10

At creation:
  Phase 1 -> Pump: 10

After split:
  Phase 1 -> Pump: 4
  Phase 2 -> Pump: 6

PO ordered quantity remains 10
```

## 2. Normalization Rule

Each business fact has exactly one owner:

```text
PO source and supplier       -> PurchaseOrder
Ordered item and price       -> PurchaseOrderLine
Delivery date and phase      -> PurchasePhase
Quantity assigned to phase   -> PurchasePhaseAllocation
Quantity actually received   -> posted warehouse receipt lines
```

A foreign key is a relationship, not duplicated business data. Derived display
fields may appear in API responses, but they must not be stored again in the
phase or allocation tables.

Copying an approved MR or winning quotation into a PO creates a new commercial
fact. The MR contains a requested quantity, the quotation contains an offered
price, and the PO line contains the quantity and price actually ordered. Equal
values across those documents do not mean they have the same business meaning.

Audit records are also not a second source of current state. They are immutable
history describing who performed an operation and when.

## 3. Target Data Model

```text
PurchaseOrder
  -> PurchaseOrderLine
  -> PurchasePhase
      -> PurchasePhaseAllocation
          -> PurchaseOrderLine
```

### 3.1 PurchaseOrder

`PurchaseOrder` owns header-level and source-document facts:

```text
id
company_id
reference_number
title nullable
supplier_id
source_rfq_id nullable
source_material_requisition_id nullable
status
approval_status
description nullable
created_by_user_id
approved_by_user_id nullable
created_at
updated_at
```

Source rules:

```text
Manual PO:
  source_rfq_id = null
  source_material_requisition_id = null

RFQ-based PO:
  source_rfq_id = RFQ.id
  source_material_requisition_id = null

Direct-MR PO:
  source_rfq_id = null
  source_material_requisition_id = MaterialRequisition.id
```

Add a database check constraint that prevents both source fields from being set
at the same time.

For an RFQ-based PO, the selected winning quotation is reached through the RFQ.
After a PO is created, the RFQ winner must be immutable. Do not also store
`winning_quotation_response_id` on the PO, and do not store RFQ, MR, quotation,
or source-line IDs on PO lines, phases, or allocations.

If the RFQ was created from an MR, the source chain is resolved as:

```text
PurchaseOrder.source_rfq_id
  -> RFQ.mr_id
      -> MaterialRequisition
```

Do not copy the RFQ's `mr_id` onto the PO.

`supplier_name` is not part of the normalized target model because the PO has a
real `supplier_id`. Existing free-text supplier data must be migrated before the
legacy field is removed.

### 3.2 PurchaseOrderLine

`PurchaseOrderLine` is the only owner of ordered-product and commercial line
facts:

```text
id
purchase_order_id
line_number
item_id
ordered_quantity
unit_id
line_description nullable
unit_price
currency_id
unit_price_base
exchange_rate_used
notes nullable
created_at
updated_at
```

Rules:

- `item_id` is a real FK to the shared Item catalog.
- `unit_id` is the unit used for this purchase. It is not assumed to remain the
  same as the Item catalog's default unit.
- `line_description` contains only PO-specific specifications or commercial
  wording. It must not copy `Item.description` automatically.
- `item_code`, `item_name`, `item_description`, and `unit_code` are resolved for
  display through `material_management` and unit services. They are not stored
  on the PO line.
- `source_type`, `rfq_item_id`, `quotation_response_item_id`, and
  `material_requisition_item_id` are not stored on the PO line. Source ownership
  is at the PO header.
- `line_total` and `line_total_base` are calculated values and are not stored.

Calculations:

```text
line_total = ordered_quantity * unit_price
line_total_base = ordered_quantity * unit_price_base
```

Use Decimal arithmetic and the shared currency rounding rules. Each line price
keeps the canonical money fields: transaction amount, currency, base amount,
and frozen exchange rate. `base_currency_id` is resolved from the company and
is not repeated on every line.

The current business rule requires all lines of one PO to use the same currency
and exchange rate. Validate that invariant in the creation and amendment
services. The PO total and currency summary are derived from its lines instead
of stored again on the PO header.

### 3.3 PurchasePhase

`PurchasePhase` owns only delivery grouping and scheduling facts:

```text
id
purchase_order_id
phase_number
title
description nullable
status
expected_delivery_date nullable
created_at
updated_at
```

Do not store these fields on a phase:

```text
item_id
MR/RFQ/quotation IDs
supplier information
currency_id
exchange_rate_used
price or totals
```

Those facts already belong to the PO or PO line. Actual receipt dates are
derived from posted receipt lines; do not store a second `actual_delivery_date`
unless a future workflow defines it as a separate manually confirmed event.

### 3.4 PurchasePhaseAllocation

Rename the Phase 1 concept `PurchasePhaseItem` to
`PurchasePhaseAllocation`. It is an allocation, not another product record.

```text
id
phase_id
purchase_order_line_id
allocated_quantity
created_at
updated_at
```

Do not store `item_id` on the allocation. Although `item_id + quantity` appears
simple, it repeats the item already owned by `PurchaseOrderLine` and becomes
ambiguous if a PO contains more than one line for the same Item. Resolve it as:

```text
PurchasePhaseAllocation.purchase_order_line_id
  -> PurchaseOrderLine.item_id
```

Do not store item names, item codes, unit, price, currency, source IDs, totals,
or `received_quantity` on the allocation.

The received quantity is calculated from posted warehouse receipt lines linked
to the allocation:

```text
received_quantity = SUM(posted receipt line quantities for allocation)
movable_quantity = allocated_quantity - received_quantity
```

Required constraints:

- Unique `(phase_id, purchase_order_line_id)`.
- `allocated_quantity > 0`.
- Phase and PO line must belong to the same PO.
- Sum of allocations for a PO line must equal its ordered quantity before
  submission and after every completed split.

Because the same-parent rule spans two FKs, enforce it in the purchase service
inside the transaction and add a database trigger in the Alembic migration for
defense in depth. Do not repeat `purchase_order_id` on the allocation merely to
make this check easier.

## 4. Creation Flows

All creation paths write the PO, at least one PO line, Phase 1, and all Phase 1
allocations in one database transaction. A failure rolls back everything.

### 4.1 PO Created From RFQ

```text
POST /purchase/orders/from-rfq/{rfq_id}
```

Required source state:

- RFQ is closed and has one selected winning quotation.
- Winning quotation covers every selected RFQ line.
- RFQ is not already linked to another active PO.

The service reads the RFQ through `rfq_management` and creates:

```text
PurchaseOrder.source_rfq_id = rfq_id
PurchaseOrder.supplier_id = winning supplier
PurchaseOrderLine rows = products, quantities, units, and accepted prices
Phase 1 = automatic initial delivery
Phase 1 allocations = full ordered quantity of every PO line
```

The PO line values become the commercial source of truth. Later changes to the
RFQ or quotation must not rewrite the PO. The selected RFQ winner becomes locked
after PO creation.

### 4.2 Manual PO

```text
POST /purchase/orders
```

Example request:

```json
{
  "title": "Manual pump purchase",
  "supplier_id": 55,
  "expected_delivery_date": "2026-08-01T00:00:00",
  "lines": [
    {
      "item_id": 99,
      "ordered_quantity": 10,
      "unit_id": 1,
      "line_description": "API 610 process pump",
      "unit_price": 1200,
      "currency_id": 1,
      "unit_price_base": 1200,
      "exchange_rate_used": 1
    }
  ]
}
```

`expected_delivery_date` is a command input used to create Phase 1. It is not
stored on both the PO and phase.

The request must contain at least one line. Every Item and unit is validated
through its owning service. Product names and descriptions are never accepted
as substitutes for `item_id`.

### 4.3 Direct Purchase From MR

```text
POST /purchase/orders/from-mr/{mr_id}
```

The MR must be approved and eligible for direct purchase. The request selects
one or more approved MR products and supplies the commercial fields not owned by
the MR, such as supplier and accepted unit price.

The resulting PO stores only `source_material_requisition_id = mr_id` at the
header. It does not repeat MR IDs on lines, phases, or allocations.

After commit, requisition status changes are requested through the existing
Celery event boundary. Purchase code must not write requisition tables directly.

### 4.4 Breaking-Change Notice

This is a breaking change to the current header-only manual PO endpoint and the
current phase-item model. Backend and frontend deployment must be coordinated.
If a staged rollout is required, add versioned creation/read contracts, migrate
the frontend, migrate existing data, and only then remove legacy fields.

## 5. Submission and Amendment Validation

Before submission for approval, verify:

```text
PO has at least one line
PO has exactly one valid source mode: manual, RFQ, or direct MR
PO has at least one phase
every line has ordered_quantity > 0
every line has valid money fields
all lines use the PO's required common currency and exchange rate
every phase contains at least one allocation
every allocation has allocated_quantity > 0
sum(allocations for each line) == line.ordered_quantity
```

Changing only phase delivery dates or splitting an unchanged ordered quantity
does not change the commercial PO. Adding a line, changing ordered quantity,
unit, price, currency, supplier, or source after approval is an amendment and
must trigger the configured reapproval workflow.

## 6. Automatic Initial Phase

Every creation path automatically creates Phase 1. The frontend does not call a
separate phase-creation route.

```text
phase_number = 1
title = "Initial delivery"
status = draft
expected_delivery_date = creation command value or calculated supplier date
allocations = full ordered quantity of every PO line
```

There is no public empty-phase creation flow in Phase 1.2.

## 7. One-Step Delivery Split

Splitting is the only Phase 1.2 operation that creates another phase:

```text
POST /purchase/orders/{po_id}/phases/split
```

Example request:

```json
{
  "title": "Later delivery",
  "expected_delivery_date": "2026-08-15T00:00:00",
  "reason": "Supplier confirmed a split delivery",
  "moves": [
    {
      "from_phase_allocation_id": 501,
      "quantity": 6
    }
  ]
}
```

The user enters only the quantity to move. The backend calculates the remaining
source quantity.

```text
Before:
  Phase 1 allocation -> PO line 77 -> quantity 10

Move:
  quantity 6

After:
  Phase 1 allocation -> PO line 77 -> quantity 4
  Phase 2 allocation -> PO line 77 -> quantity 6
```

The split transaction must:

1. Lock the PO, source allocations, and PO lines.
2. Read posted received quantities through the warehouse service.
3. Validate every requested move before writing anything.
4. Create the next numbered phase.
5. Reduce source allocation quantities.
6. Create new allocations pointing to the same PO lines.
7. Keep each PO line's total allocation unchanged.
8. Recalculate workflow statuses where required.
9. Write an audit event containing phase IDs, allocation IDs, quantities,
   reason, user, and timestamp.
10. Commit all changes together.

If any move fails, the entire transaction rolls back, including the new phase.
Use an idempotency key so retries and double clicks cannot create duplicate
phases.

Maximum movable quantity:

```text
movable_quantity = allocated_quantity - posted_received_quantity
```

Received quantities and allocations linked to non-reschedulable shipments
cannot be moved. If all unreceived quantity is moved and the source allocation
has received quantity, reduce it only to the received quantity. If it has no
receipts or operational links, a full move may remove the source allocation.

Closed and cancelled POs cannot be split.

## 8. Split Candidates

```text
GET /purchase/orders/{po_id}/split-candidates
```

Optional query parameters:

```text
source_phase_id
q
```

The response is a projection assembled from PO lines, phase allocations, the
Item service, and posted warehouse receipts. Display fields in this response are
not duplicated storage columns.

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
    "ordered_quantity": 10,
    "allocated_quantity": 10,
    "posted_received_quantity": 0,
    "movable_quantity": 10
  }
]
```

Do not return or store MR, RFQ, quotation, supplier, price, or currency data for
each phase allocation. The PO detail endpoint already exposes header and line
commercial information.

## 9. Frontend Behavior

### 9.1 Create PO

The manual PO form has a required line table. The Create PO button remains
disabled until at least one valid Item, quantity, unit, and price is present.

For RFQ-created POs, show winning quotation lines as read-only source data. For
direct-MR POs, show approved MR products and ask only for missing commercial
information. The backend remains authoritative and creates normalized PO lines.

### 9.2 Manage Phases

Show PO commercial lines separately from phase allocations:

```text
Products tab:
  PO line, Item, ordered quantity, unit, price

Deliveries tab:
  Phase, expected date, allocated quantity, received quantity, movable quantity
```

Available phase actions:

```text
Split delivery
Edit phase title or expected delivery date
```

The Split delivery dialog asks for a new delivery date, optional title, reason,
and quantities to move. It never asks the user to edit both source and target
counts.

## 10. Recipe / Template Support

A delivery recipe is optional and is not currently implemented. If added, it
must call the same normalized split service. It may create delivery schedules,
but it cannot create new PO products, prices, source links, or arbitrary phase
items.

## 11. Cross-Module Rules

- Material display and validation use `material_management` services.
- RFQ reads use `rfq_management` services.
- MR reads use `requisition_management` services.
- Posted receipt totals use the warehouse receipt service.
- No purchase module code imports another module's SQLAlchemy models, routes, or
  Pydantic schemas.
- Cross-module state changes are emitted through Celery events.
- Every new route is permission-protected and its permission is seeded.
- All errors use the shared catalogued error codes.

## 12. Migration and Compatibility

The migration must be staged and reversible:

1. Add `purchase_order_lines`.
2. Add normalized PO source fields and constraints.
3. Build one PO line for each existing logical commercial line. Group old phase
   items only when PO, Item, unit, unit price, currency, and exchange rate are
   identical; otherwise keep separate PO lines.
4. Rename or replace `purchase_phase_items` with
   `purchase_phase_allocations` containing only phase FK, PO-line FK, and
   allocated quantity.
5. Link existing receipt lines to the new allocation IDs and reconcile their
   posted totals against legacy `received_quantity` before removing that column.
6. Remove source, Item, unit, price, currency, total, and snapshot fields from
   phase allocations after backfill verification.
7. Remove phase-level currency and exchange-rate fields.
8. Move all line money facts to PO lines, then remove duplicated PO-header money
   fields from the target contract.
9. Migrate valid free-text suppliers to `supplier_id`, then remove
   `supplier_name` from the target contract.
10. Expose derived legacy response fields during a frontend deprecation period;
    do not keep duplicate database columns merely to preserve response shape.

Alembic owns every schema change. Register the new model and include migration
tests for populated databases. Do not drop a legacy column until all rows are
backfilled and verified.

## 13. Acceptance Criteria

Phase 1.2 is complete when:

- Manual PO creation rejects an empty line list.
- RFQ and direct-MR creation store source IDs only on the PO header.
- RFQ-based POs do not duplicate MR IDs from their RFQ.
- PO lines do not store source-document IDs or Item catalog display copies.
- PO line totals are calculated, not stored independently.
- Phase rows contain no product, source, supplier, or money fields.
- Phase allocations contain only phase reference, PO-line reference, allocated
  quantity, and technical timestamps/ID.
- Received quantity is derived from posted warehouse receipt lines.
- Every PO creation path atomically creates Phase 1 and complete allocations.
- Submission rejects allocation totals that differ from ordered quantities.
- One split action atomically creates a phase and moves selected unreceived
  quantities without changing PO lines.
- A failed split leaves no new phase or partial quantity changes.
- Received quantities cannot be moved or deleted.
- Split retries are idempotent and concurrent splits cannot over-allocate.
- Existing PO, source, receipt, and approval history survives migration.
- Tests cover model constraints, all creation paths, source normalization,
  calculated totals, automatic Phase 1, split success, rollback, idempotency,
  concurrency, receipt protection, permissions, and migration results.
